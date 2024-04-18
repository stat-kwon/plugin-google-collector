import logging
from urllib.parse import urlparse
from ipaddress import ip_address, IPv4Address
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.networking.vpc_network import VPCNetworkConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class VPCNetworkManager(ResourceManager):
    service = "Networking"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Networking"
        self.cloud_service_type = "VPCNetwork"
        self.metadata_path = "plugin/metadata/networking/vpc_network.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            service_code="Networking",
            tags={
                "spaceone:icon": f"{ASSET_URL}/VPC.svg",
                "spaceone:display_name": "VPCNetwork",
            },
            labels=["Networking"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        network_id = ""
        project_id = secret_data["project_id"]
        vpc_conn = VPCNetworkConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        networks = vpc_conn.list_networks()
        firewalls = vpc_conn.list_firewall()
        subnets = vpc_conn.list_subnetworks()
        routes = vpc_conn.list_routes()
        regional_address = vpc_conn.list_regional_addresses()

        cloud_services = []
        error_responses = []
        for network in networks:
            try:
                network_id = network.get("id")
                network_identifier = network.get("selfLink")
                matched_firewall = self._get_matched_firewalls(
                    network_identifier, firewalls
                )
                matched_route = self.get_matched_route(network_identifier, routes)
                matched_subnets = self._get_matched_subnets(network_identifier, subnets)
                region = self.match_region_info("global")
                peerings = self.get_peering(network)

                network.update(
                    {
                        "mode": "Auto"
                        if network.get("autoCreateSubnetworks")
                        else "Custom",
                        "project": secret_data["project_id"],
                        "globalDynamicRoute": self._get_global_dynamic_route(
                            network, "not_mode"
                        ),
                        "dynamicRoutingMode": self._get_global_dynamic_route(
                            network, "mode"
                        ),
                        "subnetCreationMode": "Auto"
                        if network.get("autoCreateSubnetworks")
                        else "Custom",
                        "ipAddressData": self.get_internal_ip_address_in_use(
                            network, regional_address
                        ),
                        "peerings": peerings,
                        "routeData": {
                            "totalNumber": len(matched_route),
                            "route": matched_route,
                        },
                        "firewallData": {
                            "totalNumber": len(matched_firewall),
                            "firewall": matched_firewall,
                        },
                        "subnetworkData": {
                            "totalNumber": len(matched_subnets),
                            "subnets": matched_subnets,
                        },
                    }
                )

                _name = network.get("name", "")

                self.set_region_code(region.get("region_code"))
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=network,
                        region_code=region.get("region_code"),
                        reference={
                            "resource_id": network_identifier,
                            "external_link": f"https://console.cloud.google.com/networking/networks/details/{_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Network {network_id}: {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def get_internal_ip_address_in_use(self, network, regional_address):
        all_internal_addresses = []

        for ip_address in regional_address:
            ip_type = ip_address.get("addressType", "")
            subnetwork = ip_address.get("subnetwork", "")

            if ip_type == "INTERNAL" and subnetwork in network.get("subnetworks", []):
                url_region = ip_address.get("region")
                users = ip_address.get("users")
                ip_address.update(
                    {
                        "subnetName": network.get("name"),
                        "ipVersionDisplay": self._valid_ip_address(
                            ip_address.get("address")
                        ),
                        "region": self.get_param_in_url(url_region, "regions")
                        if url_region
                        else "global",
                        "usedBy": self._get_parse_users(users) if users else ["None"],
                        "isEphemeral": "Static",
                    }
                )

                all_internal_addresses.append(ip_address)

        return all_internal_addresses

    def get_peering(self, network):
        updated_peering = []
        for peer in network.get("peerings", []):
            url_network = peer.get("network", "")

            ex_custom = "None"
            if peer.get("exportCustomRoutes") and peer.get("importCustomRoutes"):
                ex_custom = "Import & Export custom routes"
            elif peer.get("exportCustomRoutes"):
                ex_custom = "Export custom routes"
            elif peer.get("importCustomRoutes"):
                ex_custom = "Import custom routes"

            ex_route = "None"
            if peer.get("exportSubnetRoutesWithPublicIp") and peer.get(
                "importSubnetRoutesWithPublicIp"
            ):
                ex_route = "Import & Export subnet routes with public IP"
            elif peer.get("exportSubnetRoutesWithPublicIp"):
                ex_route = "Export subnet routes with public IP"
            elif peer.get("importSubnetRoutesWithPublicIp"):
                ex_route = "Import subnet routes with public IP"

            display = {
                "yourNetwork": network.get("name", ""),
                "peeredNetwork": self.get_param_in_url(url_network, "networks"),
                "projectId": self.get_param_in_url(url_network, "projects"),
                "stateDisplay": peer.get("state").capitalize(),
                "exCustomRoute": ex_custom,
                "exRoutePublicIpDisplay": ex_route,
            }
            peer.update({"display": display})
            updated_peering.append(peer)
        return updated_peering

    def get_matched_route(self, network, routes):
        route_vos = []

        for route in routes:
            if network == route.get("network", ""):
                next_hop = ""
                if "nextHopInstance" in route:
                    url_next_hop_instance = route.get("nextHopInstance", "")
                    target = self.get_param_in_url(url_next_hop_instance, "instances")
                    zone = self.get_param_in_url(url_next_hop_instance, "zones")
                    next_hop = f"Instance {target} (zone  {zone})"

                elif "nextHopIp" in route:
                    target = route.get("nextHopIp")
                    next_hop = f"IP address lie within {target}"

                elif "nextHopNetwork" in route:
                    url_next_hop_network = route.get("nextHopNetwork", "")
                    target = self.get_param_in_url(url_next_hop_network, "networks")
                    next_hop = f"Virtual network {target}"

                elif "nextHopGateway" in route:
                    url_next_hop_gateway = route.get("nextHopGateway", "")
                    target = self.get_param_in_url(url_next_hop_gateway, "gateways")
                    next_hop = f"{target} internet gateway"

                elif "nextHopIlb" in route:
                    url_next_hop_ilb = route.get("nextHopIlb", "")
                    target = self.get_param_in_url(url_next_hop_ilb, "forwardingRules")
                    next_hop = f" Loadbalancer on {target}"

                elif "nextHopPeering" in route:
                    target = route.get("nextHopPeering")
                    next_hop = f"Peering : {target}"

                route.update(
                    {
                        "nextHop": next_hop,
                    }
                )
                route_vos.append(route)
        return route_vos

    def _get_matched_subnets(self, network, subnets):
        matched_subnet = []
        for subnet in subnets:
            if network == subnet.get("network", ""):
                log_config = subnet.get("logConfig", {})
                url_region = subnet.get("region")
                subnet.update(
                    {
                        "region": self.get_param_in_url(url_region, "regions"),
                        "googleAccess": "On"
                        if subnet.get("privateIpGoogleAccess")
                        else "Off",
                        "flowLog": "On" if log_config.get("enable") else "Off",
                    }
                )
                matched_subnet.append(subnet)
        return matched_subnet

    @staticmethod
    def _get_matched_firewalls(network, firewalls):
        firewall_vos = []

        for firewall in firewalls:
            if network == firewall.get("network", ""):
                target_tag = firewall.get("targetTags", [])
                filter_range = ", ".join(firewall.get("sourceRanges", ""))
                log_config = firewall.get("logConfig", {})

                protocol_port = []
                flag = "allowed" if "allowed" in firewall else "denied"
                for allowed in firewall.get(flag, []):
                    ip_protocol = allowed.get("IPProtocol", "")

                    for port in allowed.get("ports", []):
                        protocol_port.append(f"{ip_protocol}: {port}")

                display = {
                    "typeDisplay": "Ingress"
                    if firewall.get("direction") == "INGRESS"
                    else "Egress",
                    "targetDisplay": ["Apply to all"] if not target_tag else target_tag,
                    "filter": f"IP ranges: {filter_range}",
                    "protocolsPort": protocol_port,
                    "action": "Allow" if "allowed" in firewall else "Deny",
                    "logs": "On" if log_config.get("enable") else "Off",
                }

                firewall.update({"display": display})

                firewall_vos.append(firewall)
        return firewall_vos

    @staticmethod
    def _valid_ip_address(ip):
        try:
            return "IPv4" if type(ip_address(ip)) is IPv4Address else "IPv6"
        except ValueError:
            return "Invalid"

    @staticmethod
    def _get_global_dynamic_route(network, flag):
        routing_config = network.get("routingConfig", {})
        if flag == "mode":
            return "Regional" if routing_config == "REGIONAL" else "Global"
        else:
            return "Off" if routing_config == "REGIONAL" else "On"

    def _get_parse_users(self, users):
        parsed_used_by = []
        for url_user in users:
            zone = self.get_param_in_url(url_user, "zones")
            instance = self.get_param_in_url(url_user, "instances")
            used = f"VM instance {instance} (Zone: {zone})"
            parsed_used_by.append(used)

        return parsed_used_by

    @staticmethod
    def get_param_in_url(url, key):
        param = ""
        raw_path = urlparse(url).path
        list_path = raw_path.split("/")
        # Google cloud resource representation rules is /{key}/{value}/{key}/{value}
        if key in list_path:
            index_key = list_path.index(key)
            index_value = index_key + 1
            param = list_path[index_value]
        return param
