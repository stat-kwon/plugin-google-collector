import logging
from datetime import datetime
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.disk import DiskConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class DiskManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "Disk"
        self.metadata_path = "plugin/metadata/compute_engine/disk.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            service_code="Compute Engine",
            tags={"spaceone:icon": f"{ASSET_URL}/Compute_Engine.svg"},
            labels=["Compute", "Storage"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        disk_conn = DiskConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        disks = disk_conn.list_disks()
        resource_policies = disk_conn.list_resource_policies()
        disk_id = ""

        cloud_services = []
        error_responses = []
        for disk in disks:
            try:
                disk_id = disk.get("id")
                disk_type = self.get_param_in_url(disk.get("type", ""), "diskTypes")
                disk_size = float(disk.get("sizeGb", 0.0))
                zone = self.get_param_in_url(disk.get("zone", ""), "zones")
                region = self.parse_region_from_zone(zone)
                labels = self.convert_labels_format(disk.get("labels", {}))

                google_cloud_monitoring_filters = [
                    {"key": "resource.labels.device_name", "value": disk.get("name")}
                ]

                disk.update(
                    {
                        "project": secret_data["project_id"],
                        "id": disk_id,
                        "zone": zone,
                        "region": region,
                        "inUsedBy": self._get_in_used_by(disk.get("users", [])),
                        "sourceImageDisplay": self._get_source_image_display(disk),
                        "diskType": disk_type,
                        "snapshotSchedule": self._get_matched_snapshot_schedule_detail(
                            region, disk, resource_policies
                        ),
                        "snapshotScheduleDisplay": self._get_snapshot_schedule_name(
                            disk
                        ),
                        "encryption": self.get_disk_encryption_type(
                            disk.get("diskEncryptionKey")
                        ),
                        "size": float(self._get_bytes(int(disk.get("sizeGb", 0)))),
                        "readIops": self._get_iops_rate(disk_type, disk_size, "read"),
                        "writeIops": self._get_iops_rate(disk_type, disk_size, "write"),
                        "readThroughput": self._get_throughput_rate(
                            disk_type, disk_size
                        ),
                        "writeThroughput": self._get_throughput_rate(
                            disk_type, disk_size
                        ),
                        "labels": labels,
                        "google_cloud_monitoring": self.set_google_cloud_monitoring(
                            project_id,
                            "compute.googleapis.com/instance/disk",
                            disk.get("name"),
                            google_cloud_monitoring_filters,
                        ),
                    }
                )

                disk.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "ComputeEngine", "Disk", project_id, disk_id
                        )
                    }
                )

                self.set_region_code(region)
                cloud_services.append(
                    make_cloud_service(
                        name=disk.get("name", ""),
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=disk,
                        region_code=disk.get("region"),
                        reference={
                            "resource_id": disk.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/networking/routes/details/{disk.get('name', '')}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Disk {disk_id}: {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def _get_iops_rate(self, disk_type, disk_size, flag):
        const = self._get_iops_constant(disk_type, flag)
        return disk_size * const

    def _get_throughput_rate(self, disk_type, disk_size):
        const = self._get_throughput_constant(disk_type)
        return disk_size * const

    # Get disk snapshot detailed configurations
    def _get_matched_snapshot_schedule_detail(self, region, disk, resource_policies):
        matched_policies = []
        policy_self_links = disk.get("resourcePolicies", [])
        policies = resource_policies.get(region)

        for self_link in policy_self_links:
            for policy in policies:
                if policy.get("selfLink") == self_link:
                    snapshot_schedule_policy = policy.get("snapshotSchedulePolicy", {})
                    snapshot_prop = snapshot_schedule_policy.get(
                        "snapshotProperties", {}
                    )
                    retention = snapshot_schedule_policy.get("retentionPolicy", {})
                    retention.update(
                        {
                            "maxRetentionDaysDisplay": str(
                                retention.get("maxRetentionDays")
                            )
                            + " days"
                        }
                    )
                    policy_schedule = snapshot_schedule_policy.get("schedule", {})

                    policy.update(
                        {
                            "snapshotSchedulePolicy": {
                                "scheduleDisplay": self._get_schedule_display(
                                    policy_schedule
                                ),
                                "schedule": policy_schedule,
                                "retentionPolicy": retention,
                            },
                            "region": self.get_param_in_url(
                                policy.get("region", ""), "regions"
                            ),
                            "labels": self.convert_labels_format(
                                snapshot_prop.get("labels", {})
                            ),
                            "tags": self.convert_labels_format(
                                snapshot_prop.get("labels", {})
                            ),
                            "storageLocations": snapshot_prop.get(
                                "storageLocations", []
                            ),
                        }
                    )
                    matched_policies.append(policy)

        return matched_policies

    def _get_in_used_by(self, users):
        in_used_by = []
        for user in users:
            used_single = self.get_param_in_url(user, "instances")
            in_used_by.append(used_single)
        return in_used_by

    def _get_schedule_display(self, schedule):
        schedule_display = []
        if "weeklySchedule" in schedule:
            week_schedule = schedule.get("weeklySchedule", {})
            weeks = week_schedule.get("dayOfWeeks", [])
            for week in weeks:
                schedule_display.append(
                    week.get("day").title() + self._get_readable_time(week)
                )

        elif "dailySchedule" in schedule:
            daily = schedule.get("dailySchedule")
            schedule_display.append(f"Every day{self._get_readable_time(daily)}")

        elif "hourlySchedule" in schedule:
            hourly = schedule.get("hourlySchedule")
            cycle = str(hourly.get("hoursInCycle"))
            hourly_schedule = f"Every {cycle} hours"
            schedule_display.append(hourly_schedule)

        return schedule_display

    @staticmethod
    def _get_readable_time(day_of_weeks):
        start_time = day_of_weeks.get("startTime")
        time_frame = start_time.split(":")
        first = int(time_frame[0]) + 1
        second = int(time_frame[1])

        d = datetime.strptime(start_time, "%H:%M")
        start = d.strftime("%I:%M %p")
        e = datetime.strptime(f"{first}:{second}", "%H:%M")
        end = e.strftime("%I:%M %p")

        return f" between {start} and {end}"

    @staticmethod
    def _get_iops_constant(disk_type, flag):
        constant = 0
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
    def _get_throughput_constant(disk_type):
        constant = 0
        if disk_type == "pd-standard":
            constant = 0.12
        elif disk_type == "pd-balanced":
            constant = 0.28
        elif disk_type == "pd-ssd":
            constant = 0.48

        return constant

    def _get_source_image_display(self, disk):
        source_image_display = ""
        url_source_image = disk.get("sourceImage")
        if url_source_image:
            source_image_display = self.get_param_in_url(url_source_image, "images")
        return source_image_display

    # Get name of snapshot schedule
    def _get_snapshot_schedule_name(self, disk):
        snapshot_schedule = []
        policies = disk.get("resourcePolicies", [])
        for url_policy in policies:
            str_policy = self.get_param_in_url(url_policy, "resourcePolicies")
            snapshot_schedule.append(str_policy)

        return snapshot_schedule

    @staticmethod
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number

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

    @staticmethod
    def get_disk_encryption_type(dict_encryption_info):
        encryption_type = "Google managed"
        if dict_encryption_info:
            if (
                "kmsKeyName" in dict_encryption_info
                or "kmsKeyServiceAccount" in dict_encryption_info
            ):
                encryption_type = "Customer managed"
            else:
                encryption_type = "Customer supplied"

        return encryption_type
