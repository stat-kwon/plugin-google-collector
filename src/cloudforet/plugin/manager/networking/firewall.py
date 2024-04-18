import logging
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.networking.firewall import FirewallConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class FirewallManager(ResourceManager):
    service = "Networking"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Networking"
        self.cloud_service_type = "Firewall"
        self.metadata_path = "plugin/metadata/networking/firewall.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            service_code="Networking",
            tags={"spaceone:icon": f"{ASSET_URL}/Firewall_Rule.svg"},
            labels=["Networking"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        firewall_conn = FirewallConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        firewall_id = ""
        firewalls = firewall_conn.list_firewall()
        all_instances = firewall_conn.list_instance_for_networks()
        region = "global"

        cloud_services = []
        error_responses = []
        for firewall in firewalls:
            try:
                firewall_id = firewall.get("id")
                target_tag = firewall.get("targetTags", [])
                filter_range = ", ".join(firewall.get("sourceRanges", ""))
                log_config = firewall.get("log_config", {})

                protocol_port = []
                flag = "allowed" if "allowed" in firewall else "denied"
                for allowed in firewall.get(flag, []):
                    ip_protocol = allowed.get("IPProtocol", "")

                    for port in allowed.get("ports", []):
                        protocol_port.append(f"{ip_protocol}: {port}")

                display = {
                    "enforcement": "Disabled"
                    if firewall.get("disabled")
                    else "Enabled",
                    "networkDisplay": self.get_param_in_url(
                        firewall.get("network", ""), "networks"
                    ),
                    "directionDisplay": "Ingress"
                    if firewall.get("direction") == "INGRESS"
                    else "Egress",
                    "targetDisplay": ["Apply to all"] if not target_tag else target_tag,
                    "filter": f"IP ranges: {filter_range}",
                    "protocolsPort": protocol_port,
                    "action": "Allow" if "allowed" in firewall else "Deny",
                    "logs": "On" if log_config.get("enable") else "Off",
                }

                firewall.update(
                    {
                        "project": secret_data["project_id"],
                        "applicableInstance": self._get_matched_instance(
                            firewall, secret_data["project_id"], all_instances
                        ),
                        "display": display,
                    }
                )

                # No Labels on API
                _name = firewall.get("data", "")

                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=firewall,
                        region_code=region,
                        reference={
                            "resource_id": firewall.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/networking/firewalls/details/{_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Firewall {firewall_id}: {e}")

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

    def _get_matched_instance(self, firewall, project_id, all_instances):
        matched_instances_vos = []
        firewall_network = firewall.get("network")
        for instance in all_instances:
            network_interfaces = instance.get("networkInterfaces", [])
            zone = self.get_param_in_url(instance.get("zone", ""), "zones")
            region = self.parse_region_from_zone(zone)
            for network_interface in network_interfaces:
                if firewall_network == network_interface.get("network", ""):
                    instance = {
                        "id": instance.get("id"),
                        "name": instance.get("name"),
                        "zone": zone,
                        "region": region,
                        "address": network_interface.get("networkIP"),
                        "subnetwork": self.get_param_in_url(
                            network_interface.get("subnetwork", ""), "subnetworks"
                        ),
                        "tags": instance.get("tags", {}).get("items", []),
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
                    }
                    matched_instances_vos.append(instance)
        return matched_instances_vos

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
