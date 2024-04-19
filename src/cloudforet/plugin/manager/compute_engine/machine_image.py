import logging
import math
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.machine_image import (
    MachineImageConnector,
)
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class MachineImageManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "MachineImage"
        self.metadata_path = "plugin/metadata/compute_engine/machine_image.yaml"

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
        machine_image_conn = MachineImageConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        machine_images = machine_image_conn.list_machine_images()

        cloud_services = []
        error_responses = []
        for machine_image in machine_images:
            try:
                _name = machine_image.get("name", "")
                machine_image_id = machine_image.get("id")
                properties = machine_image.get("instanceProperties", {})
                tags = properties.get("tags", {})
                boot_image = self.get_boot_image_data(properties)
                disks = self.get_disks(properties, boot_image)
                region = self.get_matching_region(machine_image.get("storageLocations"))

                machine_image.update(
                    {
                        "project": secret_data["project_id"],
                        "deletionProtection": properties.get(
                            "deletionProtection", False
                        ),
                        "machineType": self.get_machine_type(properties),
                        "networkTags": tags.get("items", []),
                        "diskDisplay": self._get_disk_type_display(disks, "disk_type"),
                        "image": self._get_disk_type_display(
                            disks, "source_image_display"
                        ),
                        "disks": disks,
                        "scheduling": self._get_scheduling(properties),
                        "networkInterfaces": self.get_network_interface(properties),
                        "totalStorage_bytes": float(
                            machine_image.get("totalStorageBytes", 0.0)
                        ),
                        "totalStorage_display": self._convert_size(
                            float(machine_image.get("totalStorageBytes", 0.0))
                        ),
                        "fingerprint": properties.get("metadata", {}).get(
                            "fingerprint", ""
                        ),
                        "location": properties.get("storageLocations", []),
                    }
                )

                svc_account = properties.get("serviceAccounts", [])
                if len(svc_account) > 0:
                    machine_image.update(
                        {"serviceAccount": self._get_service_account(svc_account)}
                    )

                machine_image.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "ComputeEngine",
                            "MachineImage",
                            project_id,
                            machine_image_id,
                        )
                    }
                )

                region = region.get("regionCode")
                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        tags=tags,
                        data=machine_image,
                        region_code=region,
                        reference={
                            "resource_id": machine_image.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/compute/machineImages/details/{_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(
                    f'Error on Machine Image {machine_image.get("name"): {e}}'
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

    def get_disks(self, instance, boot_image):
        disk_info = []
        # if there's another option for disk encryption
        # encryption_list = instance.get('sourceDiskEncryptionKeys', [])
        for disk in instance.get("disks", []):
            size = self._get_bytes(int(disk.get("diskSizeGb", 0)))
            single_disk = {
                "deviceIndex": disk.get("index"),
                "device": disk.get("deviceName"),
                "deviceType": disk.get("type", ""),
                "deviceMode": disk.get("mode", ""),
                "size": float(size),
                "tags": self.get_tags_info(disk),
            }
            if disk.get("boot", False):
                single_disk.update({"bootImage": boot_image, "isBootImage": True})

            # Check image is encrypted
            if "machineImageEncryptionKey" in instance:
                single_disk.update({"encryption": "Google managed"})
            elif "kmsKeyServiceAccount" in instance:
                single_disk.update({"encryption": "Customer managed"})
            else:
                single_disk.update({"encryption": "Customer supplied"})

            disk_info.append(single_disk)

        return disk_info

    def get_tags_info(self, disk):
        disk_size = float(disk.get("diskSizeGb", 0.0))
        disk_type = disk.get("diskType")
        return {
            "diskType": disk_type,
            "autoDelete": disk.get("autoDelete"),
            "readIops": self.get_iops_rate(disk_type, disk_size, "read"),
            "writeIops": self.get_iops_rate(disk_type, disk_size, "write"),
            "readThroughput": self.get_throughput_rate(disk_type, disk_size),
            "writeThroughput": self.get_throughput_rate(disk_type, disk_size),
        }

    def get_network_interface(self, instance):
        network_interface_info = []
        for idx, network_interface in enumerate(instance.get("networkInterfaces", [])):
            access_configs = network_interface.get("accessConfigs", [])
            alias_ip_ranges = network_interface.get("AliasIPRanges", [])
            network_interface_vo = {
                "name": network_interface.get("name", ""),
                "network": network_interface.get("network", ""),
                "networkTierDisplay": access_configs[0].get("networkTier")
                if len(access_configs) > 0
                else "STANDARD",
                "subnetwork": network_interface.get("subnetwork", ""),
                "networkDisplay": self.get_param_in_url(
                    network_interface.get("network", ""), "networks"
                ),
                "subnetworkDisplay": self.get_param_in_url(
                    network_interface.get("subnetwork", ""), "subnetworks"
                ),
                "primaryIpAddress": network_interface.get("networkIP", ""),
                "publicIpAddress": self._get_public_ip(access_configs),
                "accessConfigs": access_configs,
                "ipRanges": self._get_alias_ip_range(alias_ip_ranges),
                "aliasIpRanges": alias_ip_ranges,
                "kind": network_interface.get("kind", ""),
            }
            if idx == 0:
                ip_forward = "On" if instance.get("canIpForward", "") else "Off"
                network_interface_vo.update({"ipForward": ip_forward})

            network_interface_info.append(network_interface_vo)

        return network_interface_info

    def get_iops_rate(self, disk_type, disk_size, flag):
        const = self._get_iops_constant(disk_type, flag)
        return disk_size * const

    def get_throughput_rate(self, disk_type, disk_size):
        const = self._get_throughput_constant(disk_type)
        return disk_size * const

    def get_boot_image_data(self, instance):
        list_disk_info = instance.get("disks", [])
        bootdisk_info = self.get_boot_disk(list_disk_info)
        return bootdisk_info.get("deviceName", "")

    def get_matching_region(self, storage_location):
        region_code = storage_location[0] if len(storage_location) > 0 else "global"
        matched_info = self.match_region_info(region_code)
        return (
            {"regionCode": region_code, "location": "regional"}
            if matched_info
            else {"regionCode": "global", "location": "multi"}
        )

    # Returns first boot disk of instance
    @staticmethod
    def get_boot_disk(list_disk_info) -> dict:
        for disk_info in list_disk_info:
            if disk_info.get("boot", False):
                return disk_info
        return {}

    def get_machine_type(self, instance):
        machine_vo = {"machineType": instance.get("machineType", "")}
        disks = instance.get("disks", [])
        source_disk = disks[0] if len(disks) > 0 else {}
        url_source = source_disk.get("source", "")
        machine_vo.update(
            {"sourceImageFrom": self.get_param_in_url(url_source, "disks")}
        )

        return machine_vo

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
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number

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
    def _get_public_ip(access_configs):
        public_ip = ""
        if access_configs:
            public_ip = access_configs[0].get("natIP")
        return public_ip

    @staticmethod
    def _get_alias_ip_range(alias_ip_ranges):
        ip_range = []
        for ip in alias_ip_ranges:
            ip_range.append(ip.get("ipCidrRange", ""))
        return ip_range

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
    def _convert_size(size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])
