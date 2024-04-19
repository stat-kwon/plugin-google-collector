import logging
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.instance_group import (
    InstanceGroupConnector,
)
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class InstanceGroupManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "InstanceGroup"
        self.metadata_path = "plugin/metadata/compute_engine/instance_group.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            service_code="Compute Engine",
            tags={"spaceone:icon": f"{ASSET_URL}/Compute_Engine.svg"},
            labels=["Compute"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        instance_group_conn = InstanceGroupConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        instance_groups = instance_group_conn.list_instance_groups()
        instance_group_managers = instance_group_conn.list_instance_group_managers()
        autoscalers = instance_group_conn.list_autoscalers()
        instance_templates = instance_group_conn.list_instance_templates()

        cloud_services = []
        error_responses = []
        for instance_group in instance_groups:
            try:
                instance_group_id = instance_group.get("id")

                instance_group.update({"project": secret_data["project_id"]})

                scheduler = (
                    {"type": "zone"} if "zone" in instance_group else {"type": "region"}
                )

                if match_instance_group_manager := self.match_instance_group_manager(
                    instance_group_managers, instance_group.get("selfLink")
                ):
                    instance_group_type = self._get_instance_group_type(
                        match_instance_group_manager
                    )
                    scheduler.update({"instanceGroupType": instance_group_type})

                    # Managed
                    match_instance_group_manager.update(
                        {
                            "statefulPolicy": {
                                "preservedState": {
                                    "disks": self._get_stateful_policy(
                                        match_instance_group_manager
                                    )
                                }
                            }
                        }
                    )

                    instance_group.update(
                        {
                            "instanceGroupType": instance_group_type,
                            "instanceGroupManager": match_instance_group_manager,
                        }
                    )

                    if match_autoscaler := self.match_autoscaler(
                        autoscalers, match_instance_group_manager
                    ):
                        scheduler.update(
                            self._get_auto_policy_for_scheduler(match_autoscaler)
                        )

                        instance_group.update(
                            {
                                "autoscaler": match_autoscaler,
                                "autoscalingDisplay": self._get_autoscaling_display(
                                    match_autoscaler.get("autoscalingPolicy", {})
                                ),
                            }
                        )

                    match_instance_template = self.match_instance_template(
                        instance_templates,
                        match_instance_group_manager.get("instanceTemplate"),
                    )

                    if match_instance_template:
                        instance_group.update({"template": match_instance_template})

                else:
                    # Unmanaged
                    instance_group.update({"instanceGroupType": "UNMANAGED"})
                    scheduler.update({"instanceGroupType": "UNMANAGED"})

                location_type = self._check_instance_group_is_zonal(instance_group)
                location = self._get_location(instance_group)
                region = (
                    self.parse_region_from_zone(location)
                    if location_type == "zone"
                    else location
                )
                instances = instance_group_conn.list_instances(
                    instance_group.get("name"), location, location_type
                )

                display_loc = (
                    {"region": location, "zone": ""}
                    if location_type == "region"
                    else {
                        "region": self.parse_region_from_zone(location),
                        "zone": location,
                    }
                )

                google_cloud_monitoring_filters = [
                    {
                        "key": "resource.labels.instance_group_name",
                        "value": instance_group.get("name"),
                    }
                ]

                instance_group.update(
                    {
                        "powerScheduler": scheduler,
                        "instances": self.get_instances(instances),
                        "instanceCounts": len(instances),
                        "displayLocation": display_loc,
                        "google_cloud_monitoring": self.set_google_cloud_monitoring(
                            project_id,
                            "compute.googleapis.com/instance_group",
                            instance_group.get("name"),
                            google_cloud_monitoring_filters,
                        ),
                    }
                )

                _name = instance_group.get("name", "")
                instance_group.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "ComputeEngine",
                            "InstanceGroup",
                            project_id,
                            instance_group_id,
                        )
                    }
                )

                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=instance_group,
                        region_code=region,
                        reference={
                            "resource_id": instance_group.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/compute/instanceGroups/details/{instance_group.get('zone')}/{_name}?authuser=1&project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(
                    f'Error on Instance Group {instance_group.get("name")}: {str(e)}'
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

    def _get_location(self, instance_group):
        if "zone" in instance_group:
            url_zone = instance_group.get("zone")
            location = self.get_param_in_url(url_zone, "zones")
        else:
            # zone or region key must be existed
            url_region = instance_group.get("region")
            location = self.get_param_in_url(url_region, "regions")

        return location

    def get_instances(self, instances):
        _instances = []
        for instance in instances:
            url_instance = instance.get("instance", "")
            instance.update({"name": self.get_param_in_url(url_instance, "instances")})
            _instances.append(instance)

        return _instances

    @staticmethod
    def _check_instance_group_is_zonal(instance_group):
        instance_group_type = "zone" if "zone" in instance_group else "region"
        return instance_group_type

    @staticmethod
    def match_instance_template(instance_templates, instance_template_self_link):
        for instance_template in instance_templates:
            if instance_template["selfLink"] == instance_template_self_link:
                return instance_template

        return None

    @staticmethod
    def match_instance_group_manager(instance_group_managers, instance_group_name):
        for instance_group_manager in instance_group_managers:
            if instance_group_manager["instanceGroup"] == instance_group_name:
                return instance_group_manager

        return None

    @staticmethod
    def match_autoscaler(autoscalers, instance_group_manager):
        match_autoscaler_name = instance_group_manager.get("status", {}).get(
            "autoscaler"
        )

        if match_autoscaler_name:
            for autoscaler in autoscalers:
                if match_autoscaler_name == autoscaler["selfLink"]:
                    return autoscaler

        return None

    @staticmethod
    def _get_stateful_policy(match_instance_group_manager):
        disks_vos = []
        stateful_policy = match_instance_group_manager.get("statefulPolicy")
        if stateful_policy:
            preserved_state = stateful_policy.get("preservedState")
            if preserved_state:
                for key, val in preserved_state.get("disks", {}).items():
                    disks_vos.append({"key": key, "value": val})

        return disks_vos

    @staticmethod
    def _get_instance_group_type(instance_group_manager):
        if (
            instance_group_manager.get("status", {})
            .get("stateful", {})
            .get("hasStatefulConfig")
        ):
            return "STATEFUL"
        else:
            return "STATELESS"

    def _get_autoscaling_display(self, autoscaling_policy):
        display_string = f'{autoscaling_policy.get("mode")}: Target '

        policy_display_list = []

        if "cpuUtilization" in autoscaling_policy:
            policy_display_list.append(
                f'CPU utilization {(autoscaling_policy.get("cpuUtilization", {}).get("utilizationTarget")) * 100}%'
            )

        if "loadBalancingUtilization" in autoscaling_policy:
            policy_display_list.append(
                f'LB capacity fraction {(autoscaling_policy.get("loadBalancingUtilization", {}).get("utilizationTarget")) * 100}%'
            )

        for custom_metric in autoscaling_policy.get("customMetricUtilizations", []):
            policy_display_list.append(
                f'{custom_metric.get("metric", "")} {custom_metric.get("utilizationTarget", "")}{self._get_custom_metric_target_type(custom_metric.get("utilizationTargetType"))}'
            )

        if policy_display_list:
            policy_join_str = ", ".join(policy_display_list)
            return f"{display_string}{policy_join_str}"
        else:
            return ""

    @staticmethod
    def _get_custom_metric_target_type(util_target_type):
        if util_target_type == "GAUGE":
            return ""
        elif util_target_type == "DELTA_PER_SECOND":
            return "/s"
        elif util_target_type == "DELTA_PER_MINUTE":
            return "/m"
        else:
            return ""

    @staticmethod
    def _get_auto_policy_for_scheduler(matched_scheduler) -> dict:
        auto_policy = matched_scheduler.get("autoscalingPolicy", {})

        if auto_policy != {}:
            return {
                "recommendSize": matched_scheduler.get("recommendedSize", 1),
                "originMinSize": auto_policy.get("minNumReplicas"),
                "originMaxSize": auto_policy.get("maxNumReplicas"),
                "mode": auto_policy.get("mode"),
            }
        else:
            return {}

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
