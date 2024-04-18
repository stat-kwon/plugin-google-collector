import logging
import ipaddress
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.networking.route import RouteConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class RouteManager(ResourceManager):
    service = "Networking"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Networking"
        self.cloud_service_type = "Route"
        self.metadata_path = "plugin/metadata/networking/route.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            service_code="Networking",
            tags={"spaceone:icon": f"{ASSET_URL}/Route.svg"},
            labels=["Networking"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        route_conn = RouteConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        routes = route_conn.list_routes()
        compute_vms = route_conn.list_instance()
        region = "global"
        route_id = ""

        cloud_services = []
        error_responses = []
        for route in routes:
            try:
                display = {
                    "networkDisplay": self.get_param_in_url(
                        route.get("network", ""), "networks"
                    ),
                    "nextHop": self._get_next_hop(route),
                    "instanceTagsOnList": self._get_tags_display(route, "list"),
                    "instanceTags": self._get_tags_display(route, "not list"),
                }

                route.update(
                    {
                        "display": display,
                        "project": secret_data["project_id"],
                        "applicableInstance": self._get_matched_instance(
                            route, secret_data["project_id"], compute_vms
                        ),
                    }
                )

                _name = route.get("name", "")
                route_id = route.get("id", "")

                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=route,
                        region_code=region,
                        reference={
                            "resource_id": route.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/networking/routes/details/{_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Route {route_id}: {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

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

    def _get_next_hop(self, route):
        next_hop = ""
        if "nextHopInstance" in route:
            url_next_hop_instance = route.get("nextHopInstance", "")
            target = self.get_param_in_url(
                url_next_hop_instance, "instances"
            ).capitalize()
            zone = self.get_param_in_url(url_next_hop_instance, "zones").capitalize()
            next_hop = f"Instance {target} (zone  {zone})"

        elif "nextHopIp" in route:
            # IP address
            target = route.get("nextHopIp", "")
            next_hop = f"IP address lie within {target}"

        elif "nextHopNetwork" in route:
            url_next_hop_network = route.get("nextHopNetwork", "")
            target = self.get_param_in_url(url_next_hop_network, "networks")
            next_hop = f"Virtual network {target}"

        elif "nextHopGateway" in route:
            url_next_hop_gateway = route.get("nextHopGateway")
            target = self.get_param_in_url(url_next_hop_gateway, "gateways")
            next_hop = f"{target} internet gateway"

        elif "nextHopIlb" in route:
            # Both ip address and Url string are possible value
            next_hop_ilb = route.get("nextHopIlb", "")
            if self.check_is_ipaddress(next_hop_ilb):
                target = next_hop_ilb
            else:
                target = self.get_param_in_url(next_hop_ilb, "forwardingRules")
            next_hop = f"Loadbalancer on {target}"

        elif "nextHopPeering" in route:
            target = route.get("nextHopPeering", "")
            next_hop = f"Peering : {target}"

        return next_hop

    @staticmethod
    def check_is_ipaddress(string_to_check):
        try:
            ip = ipaddress.ip_address(string_to_check)
            return True
        except ValueError:
            return False

    @staticmethod
    def _get_tags_display(route, flag):
        contents = (
            []
            if flag == "list"
            else ["This route applies to all instances within the specified network"]
        )
        return contents if not route.get("tags", []) else route.get("tags", [])

    def _get_matched_instance(self, route, project_id, instances_over_region):
        matched_instances = []

        for instance in instances_over_region:
            network_interfaces = instance.get("networkInterfaces", [])
            zone = self.get_param_in_url(instance.get("zone", ""), "zones")
            region = self.parse_region_from_zone(zone)

            for network_interface in network_interfaces:
                if self._check_instance_is_matched(route, instance):
                    instance_name = instance.get("name")
                    url_subnetwork = instance.get("subnetwork", "")
                    instance = {
                        "id": instance.get("id"),
                        "name": instance_name,
                        "zone": zone,
                        "region": region,
                        "address": network_interface.get("networkIP"),
                        "subnetwork": self.get_param_in_url(
                            url_subnetwork, "subnetworks"
                        ),
                        "project": project_id,
                        "serviceAccounts": self._get_service_accounts(
                            instance.get("serviceAccounts", [])
                        ),
                        "creationTimestamp": instance.get("creationTimestamp"),
                        "labels": self.convert_labels_format(
                            instance.get("labels", {})
                        ),
                        "labelsDisplay": self._get_label_display(
                            instance.get("labels", {})
                        ),
                        "tags": instance.get("tags", {}).get("items", []),
                    }
                    matched_instances.append(instance)
        return matched_instances

    @staticmethod
    def parse_region_from_zone(zone):
        """
        EX> zone = 'ap-northeast2-a'
        """
        parsed_zone = zone.split("-")
        if len(parsed_zone) >= 2:
            return f"{parsed_zone[0]}-{parsed_zone[1]}"

        else:
            return ""

    @staticmethod
    def _check_instance_is_matched(route, instance):
        """
        - instance network is matched to route network(VPC network)
        - instance tags is matched to route tags
        """
        matched = False
        route_network = route.get("network")
        network_interfaces = instance.get("networkInterfaces", [])

        for network_interface in network_interfaces:
            if route_network == network_interface.get("network"):
                if "tags" in route:
                    if instance.get("tags", {}).get("items", []) in route.get(
                        "tags", []
                    ):
                        matched = True
                    else:
                        matched = False
                else:
                    matched = True

        return matched

    @staticmethod
    def _get_service_accounts(service_accounts):
        service_accounts_list = []
        for service_account in service_accounts:
            service_accounts_list.append(service_account.get("email"))

        if not service_accounts_list:
            service_accounts_list.append("None")
        return service_accounts_list

    @staticmethod
    def _get_label_display(labels):
        displays = []
        for label in labels:
            value = labels.get(label, "")
            displays.append(f"{label}: {value}")
        return displays
