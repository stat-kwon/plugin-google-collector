import logging
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.vm_instance import VMInstanceConnector
from cloudforet.plugin.manager import ResourceManager
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.disk_helper import (
    DiskHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.firewall_helper import (
    FirewallHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.instance_group_helper import (
    InstanceGroupHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.load_balancer_helper import (
    LoadBalancerHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.nic_helper import (
    NICHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.vm_instance_helper import (
    VMInstanceHelper,
)
from cloudforet.plugin.manager.compute_engine.vm_instance_helper.vpc_helper import (
    VPCHelper,
)

_LOGGER = logging.getLogger("spaceone")


class VMInstanceManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "Instance"
        self.metadata_path = "plugin/metadata/compute_engine/vm_instance.yaml"
        self.instance_conn = None

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_major=True,
            is_primary=True,
            service_code="Compute Engine",
            tags={"spaceone:icon": f"{ASSET_URL}/Compute_Engine.svg"},
            labels=["Compute", "Server"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        vm_id = ""
        self.instance_conn = VMInstanceConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        all_resources = self.get_all_resources(project_id)
        compute_vms = self.instance_conn.list_instances()

        cloud_services = []
        error_responses = []
        for compute_vm in compute_vms:
            try:
                vm_id = compute_vm.get("id")
                zone, region = self._get_zone_and_region(compute_vm)
                zone_info = {"zone": zone, "region": region, "projectId": project_id}

                resource = self.get_vm_instance_resource(
                    project_id, zone_info, compute_vm, all_resources
                )
                path, instance_type = compute_vm.get("machineType").split(
                    "machineTypes/"
                )
                _name = compute_vm.get("name", "")
                labels = resource.get("googleCloud").get("labels", [])

                self.set_region_code(resource.get("region_code", ""))
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        instance_type=instance_type,
                        instance_size=resource.get("data", {})
                        .get("hardware", {})
                        .get("core", 0),
                        tags=self.convert_labels_to_dict(labels),
                        data=resource,
                        region_code=resource.get("region_code", ""),
                        reference={
                            "resource_id": resource["googleCloud"]["selfLink"],
                            "external_link": f"https://console.cloud.google.com/compute/instancesDetail/zones/{zone_info.get('zone')}/instances/{resource['name']}?project={resource['compute']['account']}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Instance: {vm_id} : {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def get_all_resources(self, project_id) -> dict:
        instance_group_helper = InstanceGroupHelper(self.instance_conn)

        return {
            "disk": self.instance_conn.list_disks(),
            "autoscaler": self.instance_conn.list_autoscalers(),
            "instance_type": self.instance_conn.list_machine_types(),
            "instance_group": self.instance_conn.list_instance_group_managers(),
            "public_images": self.instance_conn.list_images(project_id),
            "vpcs": self.instance_conn.list_vpcs(),
            "subnets": self.instance_conn.list_subnetworks(),
            "firewalls": self.instance_conn.list_firewall(),
            "forwarding_rules": self.instance_conn.list_forwarding_rules(),
            "target_pools": self.instance_conn.list_target_pools(),
            "urlMaps": self.instance_conn.list_url_maps(),
            "backendSvcs": self.instance_conn.list_back_end_services(),
            "managedInstancesInInstanceGroups": instance_group_helper.list_managed_instances_in_instance_groups(),
        }

    def _get_zone_and_region(self, instance) -> (str, str):
        url_zone = instance.get("zone", "")
        zone = self.get_param_in_url(url_zone, "zones")
        region = self.parse_region_from_zone(zone)
        return zone, region

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

    def get_vm_instance_resource(self, project_id, zone_info, instance, all_resources):
        """Prepare input params for call manager"""
        # VPC
        vpcs = all_resources.get("vpcs", [])
        subnets = all_resources.get("subnets", [])

        # All Public Images
        public_images = all_resources.get("publicImages", {})

        # URL Maps
        url_maps = all_resources.get("urlMaps", [])
        backend_svcs = all_resources.get("backendSvcs", [])
        target_pools = all_resources.get("targetPools", [])

        # Forwarding Rules
        forwarding_rules = all_resources.get("forwardingRules", [])

        # Firewall
        firewalls = all_resources.get("firewalls", [])

        # Get Instance Groups
        instance_group = all_resources.get("instanceGroup", [])

        # Get Machine Types
        instance_types = all_resources.get("instanceType", [])

        # Autoscaling group list
        autoscaler = all_resources.get("autoscaler", [])
        instance_in_managed_instance_groups = all_resources.get(
            "managedInstancesInInstanceGroups", []
        )

        # disks
        disks = all_resources.get("disk", [])

        """Get related resources from helpers"""
        vm_instance_helper: VMInstanceHelper = VMInstanceHelper(self.instance_conn)
        auto_scaler_helper: InstanceGroupHelper = InstanceGroupHelper(
            self.instance_conn
        )
        loadbalancer_helper: LoadBalancerHelper = LoadBalancerHelper()
        disk_helper: DiskHelper = DiskHelper()
        nic_helper: NICHelper = NICHelper()
        vpc_helper: VPCHelper = VPCHelper()
        firewall_helper: FirewallHelper = FirewallHelper()
        autoscaler_vo = auto_scaler_helper.get_autoscaler_info(
            instance, instance_group, autoscaler
        )
        load_balancer_vos = loadbalancer_helper.get_loadbalancer_info(
            instance,
            instance_group,
            backend_svcs,
            url_maps,
            target_pools,
            forwarding_rules,
        )
        disk_vos = disk_helper.get_disk_info(instance, disks)
        vpc_vo, subnet_vo = vpc_helper.get_vpc_info(instance, vpcs, subnets)
        nic_vos = nic_helper.get_nic_info(instance, subnet_vo)
        firewall_vos = firewall_helper.list_firewall_rules_info(instance, firewalls)

        firewall_names = [
            d.get("name") for d in firewall_vos if d.get("name", "") != ""
        ]
        server_data = vm_instance_helper.get_server_info(
            instance,
            instance_types,
            disks,
            zone_info,
            public_images,
            instance_in_managed_instance_groups,
        )
        google_cloud_filters = [
            {"key": "resource.labels.instance_id", "value": instance.get("id")}
        ]
        google_cloud = server_data.get("googleCloud", {})
        _name = instance.get("name", "")

        # Set GPU info
        if gpus_info := instance.get("guestAccelerators", []):
            gpus = self._get_gpu_info(gpus_info)
            server_data.update(
                {
                    "gpus": gpus,
                    "totalGpuCount": sum([gpu.get("gpuCount", 0) for gpu in gpus]),
                    "hasGpu": True,
                    "display": {
                        "gpus": self._change_human_readable(gpus),
                        "hasGpu": True,
                    },
                }
            )

        path, instance_type = instance.get("machineType").split("machineTypes/")

        """ Gather all resources information """
        """
        server_data.update({
            'nics': nic_vos,
            'disks': disk_vos,
        })
        """
        server_data.update(
            {
                "nics": nic_vos,
                "disks": disk_vos,
            }
        )
        server_data["compute"]["securityGroups"] = firewall_names
        server_data.update(
            {
                "loadBalancers": load_balancer_vos,
                "securityGroup": firewall_vos,
                "autoscaler": autoscaler_vo,
                "vpc": vpc_vo,
                "subnet": subnet_vo,
            }
        )

        server_data.update(
            {
                "google_cloud_monitoring": self.set_google_cloud_monitoring(
                    project_id,
                    "compute.googleapis.com/instance",
                    instance.get("id"),
                    google_cloud_filters,
                )
            }
        )

        server_data.update(
            {
                "google_cloud_logging": self.set_google_cloud_logging(
                    "ComputeEngine", "Instance", project_id, instance.get("id")
                )
            }
        )

        return server_data

    @staticmethod
    def _get_gpu_info(gpus_info):
        gpu_items = []
        for gpu_info in gpus_info:
            path, gpu_machine_type = gpu_info.get("acceleratorType").split(
                "acceleratorTypes/"
            )
            gpus = gpu_info.get("acceleratorCount")
            gpu_items.append({"gpuCount": gpus, "gpuMachineType": gpu_machine_type})
        return gpu_items

    @staticmethod
    def _change_human_readable(gpus: list) -> list:
        readable_gpus = []
        for gpu in gpus:
            readable_machine_type = gpu["gpuMachineType"].replace("-", " ").upper()
            readable_gpus.append(f"{gpu['gpuCount']}x{readable_machine_type}")
        return readable_gpus

    @staticmethod
    def convert_labels_to_dict(labels):
        return {label["key"]: label["value"] for label in labels}
