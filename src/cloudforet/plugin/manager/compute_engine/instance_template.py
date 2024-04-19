import logging
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.instance_template import (
    InstanceTemplateConnector,
)
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class InstanceTemplateManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "InstanceTemplate"
        self.metadata_path = "plugin/metadata/compute_engine/instance_template.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            service_code="Compute Engine",
            tags={"spaceone:icon": f"{ASSET_URL}/Compute_Engine.svg"},
            labels=["Compute"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        instance_template_conn = InstanceTemplateConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        instance_templates = instance_template_conn.list_instance_templates()
        instance_groups = instance_template_conn.list_instance_group_managers()

        cloud_services = []
        error_responses = []
        for inst_template in instance_templates:
            try:
                inst_template_id = inst_template.get("id")
                properties = inst_template.get("properties", {})
                tags = properties.get("tags", {})

                in_used_by, matched_instance_group = self._match_instance_group(
                    inst_template, instance_groups
                )
                disks = self._get_disks(properties)
                labels = self.convert_labels_format(properties.get("labels", {}))

                inst_template.update(
                    {
                        "project": secret_data["project_id"],
                        "inUsedBy": in_used_by,
                        "ipForward": properties.get("canIpForward", False),
                        "machineType": properties.get("machineType", ""),
                        "networkTags": tags.get("items", []),
                        "scheduling": self._get_scheduling(properties),
                        "diskDisplay": self._get_disk_type_display(disks, "disk_type"),
                        "image": self._get_disk_type_display(
                            disks, "source_image_display"
                        ),
                        "instanceGroups": matched_instance_group,
                        "networkInterfaces": self._get_network_interface(properties),
                        "fingerprint": self._get_properties_item(
                            properties, "metadata", "fingerprint"
                        ),
                        "labels": labels,
                        "disks": disks,
                    }
                )

                svc_account = properties.get("serviceAccounts", [])
                if len(svc_account) > 0:
                    inst_template.update(
                        {"serviceAccount": self._get_service_account(svc_account)}
                    )
                _name = inst_template.get("name", "")

                inst_template.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "ComputeEngine",
                            "InstanceTemplate",
                            project_id,
                            inst_template_id,
                        )
                    }
                )

                self.set_region_code("global")
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        tags=tags,
                        data=inst_template,
                        region_code="global",
                        reference={
                            "resource_id": inst_template.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/compute/instanceTemplates/details/{_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(
                    f'Error on Instance Template {inst_template.get("name")}: {e}'
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

    def _get_disks(self, instance):
        disk_info = []
        for disk in instance.get("disks", []):
            init_param = disk.get("initializeParams", {})
            """
            # initializeParams: {diskSizeGb: ""} can be Null
            if init_param.get('diskSizeGb') is not None:
                size = self._get_bytes(int(init_param.get('diskSizeGb')))
            else:
                size = 0
            """
            disk_info.append(
                {
                    "deviceIndex": disk.get("index"),
                    "device": disk.get("deviceName"),
                    "deviceType": disk.get("type", ""),
                    "deviceMode": disk.get("mode", ""),
                    "size": self._get_disk_size(init_param),
                    "tags": self._get_tags_info(disk),
                }
            )
        return disk_info

    def _get_tags_info(self, disk):
        init_param = disk.get("initializeParams", {})
        disk_size = self._get_disk_size(init_param)
        disk_type = init_param.get("diskType")
        sc_image = init_param.get("sourceImage", "")
        return {
            "diskType": init_param.get("diskType"),
            "sourceImage": sc_image,
            "sourceImageDisplay": self.get_param_in_url(sc_image, "images"),
            "autoDelete": disk.get("autoDelete"),
            "readIops": self._get_iops_rate(disk_type, disk_size, "read"),
            "writeIops": self._get_iops_rate(disk_type, disk_size, "write"),
            "readThroughput": self._get_throughput_rate(disk_type, disk_size),
            "writeThroughput": self._get_throughput_rate(disk_type, disk_size),
        }

    def _get_network_interface(self, instance):
        network_interface_info = []
        for network_interface in instance.get("networkInterfaces", []):
            configs, tiers = self._get_access_configs_type_and_tier(
                network_interface.get("accessConfigs", [])
            )
            network_interface_info.append(
                {
                    "idxName": network_interface.get("name", ""),
                    "network": network_interface.get("network", ""),
                    "networkDisplay": self.get_param_in_url(
                        network_interface.get("network", ""), "networks"
                    ),
                    "configs": configs,
                    "networkTier": tiers,
                    "accessConfigs": network_interface.get("accessConfigs", []),
                    "kind": network_interface.get("kind", []),
                }
            )

        return network_interface_info

    def _get_iops_rate(self, disk_type, disk_size, flag):
        const = self._get_iops_constant(disk_type, flag)
        return disk_size * const

    def _get_throughput_rate(self, disk_type, disk_size):
        const = self._get_throughput_constant(disk_type)
        return disk_size * const

    def _get_disk_size(self, init_param) -> float:
        # initializeParams: {diskSizeGb: ""} can be Null
        if init_param.get("diskSizeGb") is not None:
            disk_size = self._get_bytes(int(init_param.get("diskSizeGb")))
        else:
            disk_size = 0
        return disk_size

    @staticmethod
    def _get_access_configs_type_and_tier(access_configs):
        configs = []
        tiers = []
        for access_config in access_configs:
            ac_name = access_config.get("name", "")
            ac_type = access_config.get("type", "")
            configs.append(f" {ac_name} : {ac_type}")
            tiers.append(access_config.get("networkTier", ""))
        return configs, tiers

    # Returns matched instance group and user(instance) related to instance template.
    @staticmethod
    def _match_instance_group(instance_template, instance_group_managers: list):
        in_used_by = []
        instance_group_infos = []
        for instance_group in instance_group_managers:
            template_self_link_source = instance_template.get("selfLink", "")
            template_self_link_target = instance_group.get("instanceTemplate", "")
            if (
                template_self_link_source != ""
                and template_self_link_target != ""
                and template_self_link_source == template_self_link_target
            ):
                in_used_by.append(instance_group.get("name", ""))
                instance_group_infos.append(instance_group)

        return in_used_by, instance_group_infos

    @staticmethod
    def _get_service_account(svc_account):
        service_account = svc_account[0]
        return {
            "email": service_account.get("email", ""),
            "scopes": service_account.get("scopes", []),
        }

    @staticmethod
    def _get_iops_constant(disk_type, flag):
        constant = 0.0
        if flag == "read":
            if disk_type == "pd-standard":
                constant = 0.75
            elif disk_type == "pd-balanced":
                constant = 6.0
            elif disk_type == "pd-ssd":
                constant = 30.0
        else:
            if disk_type == "pd-standard":
                constant = 1.5
            elif disk_type == "pd-balanced":
                constant = 6.0
            elif disk_type == "pd-ssd":
                constant = 30.0
        return constant

    @staticmethod
    def _get_disk_type_display(disk, key):
        if len(disk) > 0:
            tag = disk[0].get("tags", {})
            disk_type = tag.get(key, "")
            return disk_type
        else:
            return ""

    @staticmethod
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number

    @staticmethod
    def _get_properties_item(properties: dict, item_key: str, key: str):
        item = properties.get(item_key)
        selected_prop_item = item.get(key) if item else ""
        return selected_prop_item

    @staticmethod
    def _get_scheduling(properties):
        scheduling = properties.get("scheduling", {})
        return {
            "onHostMaintenance": scheduling.get("onHostMaintenance", "MIGRATE"),
            "automaticRestart": "On"
            if scheduling.get("automaticRestart", False)
            else "Off",
            "preemptibility": "On" if scheduling.get("preemptible", False) else "Off",
        }

    @staticmethod
    def _get_throughput_constant(disk_type):
        constant = 0.0
        if disk_type == "pd-standard":
            constant = 0.12
        elif disk_type == "pd-balanced":
            constant = 0.28
        elif disk_type == "pd-ssd":
            constant = 0.48

        return constant

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

    def _get_disk_size(self, init_param: dict) -> float:
        # initializeParams: {diskSizeGb: ""} can be Null
        if init_param.get("diskSizeGb") is not None:
            disk_size = self._get_bytes(int(init_param.get("diskSizeGb")))
        else:
            disk_size = 0
        return disk_size

    @staticmethod
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number
