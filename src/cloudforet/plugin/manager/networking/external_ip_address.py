import logging
from ipaddress import ip_address, IPv4Address
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.networking.external_ip_address import (
    ExternalIPAddressConnector,
)
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class ExternalIPAddressManager(ResourceManager):
    service = "Networking"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Networking"
        self.cloud_service_type = "ExternalIPAddress"
        self.metadata_path = "plugin/metadata/networking/external_ip_address.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            service_code="Networking",
            tags={"spaceone:icon": f"{ASSET_URL}/External_IP_Address.svg"},
            labels=["Networking"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        exp_conn = ExternalIPAddressConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        all_addresses = exp_conn.list_addresses()
        vm_instances = exp_conn.list_instance_for_networks()
        forwarding_rule_address = exp_conn.list_forwarding_rule()

        # External IP contains, reserved IP(static) + vm IP(ephemeral) + forwarding rule IP
        all_external_ip_addresses = self._get_external_ip_addresses(
            all_addresses, vm_instances, forwarding_rule_address
        )
        external_ip_addr_id = ""

        cloud_services = []
        error_responses = []
        for external_ip_addr in all_external_ip_addresses:
            try:
                region = (
                    external_ip_addr.get("region")
                    if external_ip_addr.get("region", "")
                    else "global"
                )
                external_ip_addr_id = external_ip_addr.get("id", "")

                external_ip_addr.update(
                    {
                        "project": secret_data["project_id"],
                        "statusDisplay": external_ip_addr.get("status", "")
                        .replace("_", " ")
                        .title(),
                    }
                )

                if self_link := external_ip_addr.get("selfLink") is None:
                    external_ip_addr.update(
                        {
                            "selfLink": self._get_external_self_link_when_its_empty(
                                external_ip_addr
                            )
                        }
                    )

                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=external_ip_addr.get("name", ""),
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=external_ip_addr,
                        region_code=region,
                        reference={
                            "resource_id": self_link,
                            "external_link": f"https://console.cloud.google.com/networking/addresses/list/project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(
                    f"Error on External IP Address {external_ip_addr_id}: {e}"
                )

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def _get_external_ip_addresses(
        self, all_addresses, all_instances, forwarding_rules
    ):
        """
        Aggregates public ip address from different resource types
        - Static IP : all_addresses
        - Ephermeral IP : all_instances
        - Forwarding Rule(LoadBalancer) IP : forwarding_rules
        """
        all_ip_addr_vos = []
        all_ip_addr_only_check_dup = []

        for ip_addr in all_addresses:
            if "EXTERNAL" == ip_addr.get("addressType"):
                url_region = ip_addr.get("region", "")
                users = ip_addr.get("users", [])
                ip_addr.update(
                    {
                        "region": self.get_param_in_url(url_region, "regions")
                        if url_region == ""
                        else "global",
                        "usedBy": self._get_parse_users(users),
                        "ipVersionDisplay": self._get_ip_address_version(
                            ip_addr.get("address")
                        ),
                        "networkTierDisplay": ip_addr.get(
                            "networkTier", ""
                        ).capitalize(),
                        "isEphemeral": "Static",
                    }
                )
                all_ip_addr_only_check_dup.append(ip_addr.get("address"))
                all_ip_addr_vos.append(ip_addr)

        for forwarding_rule in forwarding_rules:
            forwarding_ip_addr = forwarding_rule.get("IPAddress")
            if (
                forwarding_rule.get("loadBalancingScheme") == "EXTERNAL"
                and forwarding_ip_addr not in all_ip_addr_only_check_dup
            ):
                rule_name = forwarding_rule.get("name")
                url_region = forwarding_rule.get("region", "")
                forwarding_rule.update(
                    {
                        "isEphemeral": "Ephemeral",
                        "ipVersionDisplay": self._get_ip_address_version(
                            forwarding_ip_addr
                        ),
                        "networkTierDisplay": forwarding_rule.get(
                            "networkTier", ""
                        ).capitalize(),
                        "addressType": forwarding_rule.get("loadBalancingScheme"),
                        "address": forwarding_ip_addr,
                        "region": self.get_param_in_url(url_region, "regions")
                        if url_region != ""
                        else "global",
                        "status": "IN_USE",
                        "users": [forwarding_rule.get("selfLink", "")],
                        "usedBy": [f"Forwarding rule {rule_name}"],
                    }
                )
                all_ip_addr_only_check_dup.append(forwarding_ip_addr)
                all_ip_addr_vos.append(forwarding_rule)

        for instance in all_instances:
            network_interfaces = instance.get("networkInterfaces", [])
            zone = self.get_param_in_url(instance.get("zone", ""), "zones")
            region = self.parse_region_from_zone(zone)
            for network_interface in network_interfaces:
                external_ip_infos = network_interface.get("accessConfigs", [])
                for external_ip_info in external_ip_infos:
                    if (
                        "natIP" in external_ip_info
                        and external_ip_info.get("natIP")
                        not in all_ip_addr_only_check_dup
                    ):
                        instance_name = instance.get("name")
                        external_ip = {
                            "id": instance.get("id"),
                            "address": external_ip_info.get("natIP"),
                            "zone": zone,
                            "region": region,
                            "addressType": "EXTERNAL",
                            "isEphemeral": "Ephemeral",
                            "networkTier": external_ip_info.get("networkTier"),
                            "networkTierDisplay": external_ip_info.get(
                                "networkTier", ""
                            ).capitalize(),
                            "status": "IN_USE",
                            "ipVersionDisplay": self._get_ip_address_version(
                                external_ip_info.get("natIP")
                            ),
                            "creationTimestamp": instance.get("creationTimestamp"),
                            "users": [instance.get("selfLink", "")],
                            "usedBy": [f"Vm Instance {instance_name} ({zone})"],
                        }
                        all_ip_addr_only_check_dup.append(
                            external_ip_info.get("natIP", "")
                        )
                        all_ip_addr_vos.append(external_ip)

        return all_ip_addr_vos

    @staticmethod
    def _get_ip_address_version(ip) -> str:
        try:
            return "IPv4" if type(ip_address(ip)) is IPv4Address else "IPv6"
        except ValueError:
            return "Invalid"

    def _get_parse_users(self, users):
        list_user = []
        for url_user in users:
            zone = self.get_param_in_url(url_user, "zones")
            instance = self.get_param_in_url(url_user, "instances")
            used_by = f"VM instance {instance} (Zone: {zone})"
            list_user.append(used_by)

        return list_user

    @staticmethod
    def _get_external_self_link_when_its_empty(external_ip):
        ip_address = external_ip.get("address", "")
        project_id = external_ip.get("project_id")
        zone = external_ip.get("zone")
        region = external_ip.get("region")
        return (
            f"https://console.cloud.google.com/networking/addresses/project={project_id}/zone={zone}/ip_address/{ip_address}"
            if zone
            else f"https://console.cloud.google.com/networking/addresses/project={project_id}/region/{region}/ip_address/{ip_address}"
        )

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
