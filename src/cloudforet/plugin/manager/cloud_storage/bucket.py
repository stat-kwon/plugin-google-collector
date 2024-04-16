import logging
from datetime import datetime, timedelta
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.cloud_storage import (
    MonitoringConnector,
    StorageConnector,
)
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class BucketManager(ResourceManager):
    service = "CloudStorage"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "CloudStorage"
        self.cloud_service_type = "Bucket"
        self.metadata_path = "plugin/metadata/cloud_storage/bucket.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="CloudStorage",
            tags={
                "spaceone:icon": f"{ASSET_URL}/Cloud_Storage.svg",
                "spaceone:display_name": "CloudStorage",
            },
            labels=["Storage", "Volume"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        storage_conn = StorageConnector(
            options=options,
            secret_data=secret_data,
            schema=schema,
        )
        monitoring_conn = MonitoringConnector(
            options=options,
            secret_data=secret_data,
            schema=schema,
        )

        cloud_services = []
        error_responses = []
        for bucket in storage_conn.list_buckets():
            try:
                bucket_name = bucket.get("name", "")
                bucket_id = bucket.get("id")

                object_count = self._get_object_total_count(
                    monitoring_conn, bucket_name
                )
                object_size = self._get_bucket_total_size(monitoring_conn, bucket_name)
                iam_policy = storage_conn.list_iam_policy(bucket_name)
                st_class = bucket.get("storageClass").lower()
                region = self.get_matching_region(bucket)
                labels = self.convert_labels_format(bucket.get("labels", {}))

                bucket.update(
                    {
                        "project": project_id,
                        "encryption": self._get_encryption(bucket),
                        "requesterPays": self._get_requester_pays(bucket),
                        "retentionPolicyDisplay": self._get_retention_policy_display(
                            bucket
                        ),
                        "links": self._get_config_link(bucket),
                        "size": object_size,
                        "defaultEventBasedHold": "Enabled"
                        if bucket.get("defaultEventBasedHold")
                        else "Disabled",
                        "iamPolicy": iam_policy,
                        "iamPolicyBinding": self._get_iam_policy_binding(iam_policy),
                        "objectCount": object_count,
                        "objectTotalSize": object_size,
                        "lifecycleRule": self._get_lifecycle_rule(bucket),
                        "location": self.get_location(bucket),
                        "defaultStorageClass": st_class.capitalize(),
                        "accessControl": self._get_access_control(bucket),
                        "publicAccess": self._get_public_access(bucket, iam_policy),
                        "labels": labels,
                    }
                )

                bucket.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "CloudStorage", "Bucket", project_id, bucket_name
                        ),
                    }
                )
                region_code = region.get("region_code")
                self.set_region_code(region_code)
                cloud_services.append(
                    make_cloud_service(
                        name=bucket_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        instance_type="",
                        instance_size=bucket.get("size"),
                        data=bucket,
                        region_code=region_code,
                        reference={
                            "resource_id": bucket_id,
                            "external_link": f"https://console.cloud.google.com/storage/browser/{bucket_name}",
                        },
                    )
                )
            except Exception as e:
                _LOGGER.error(f"Error on Bucket {bucket.get('name')}: {e}")
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
    def _get_object_total_count(monitoring_conn, bucket_name):
        metric = "storage.googleapis.com/storage/object_count"
        start = datetime.now() - timedelta(days=1)
        end = datetime.now()
        response = monitoring_conn.get_metric_data(bucket_name, metric, start, end)

        if response.get("points", []):
            object_total_count = (
                response.get("points", [])[0].get("value", {}).get("int64Value", "")
            )
        else:
            object_total_count = None

        return object_total_count

    @staticmethod
    def _get_bucket_total_size(monitoring_conn, bucket_name):
        metric = "storage.googleapis.com/storage/total_bytes"
        start = datetime.now() - timedelta(days=1)
        end = datetime.now()
        response = monitoring_conn.get_metric_data(bucket_name, metric, start, end)

        if response.get("points", []):
            object_total_size = (
                response.get("points", [])[0].get("value", {}).get("doubleValue", "")
            )
        else:
            object_total_size = None

        return object_total_size

    def get_matching_region(self, bucket):
        location_type_ref = ["multi-region", "dual-region"]
        location = bucket.get("location", "").lower()
        location_type = bucket.get("locationType", "")
        region_code = "global" if location_type in location_type_ref else location
        return self.match_region_info(region_code)

    @staticmethod
    def convert_labels_format(labels):
        convert_labels = []
        for k, v in labels.items():
            convert_labels.append({"key": k, "value": v})
        return convert_labels

    @staticmethod
    def _get_encryption(bucket):
        encryption = bucket.get("encryption", {})
        return "Google-managed" if encryption == {} else "Customer-managed"

    @staticmethod
    def _get_requester_pays(bucket):
        pays = "OFF"
        billing = bucket.get("billing", {})
        if billing.get("requesterPays", False):
            pays = "ON"
        return pays

    @staticmethod
    def _get_retention_policy_display(bucket):
        display = ""
        policy = bucket.get("retentionPolicy")
        if policy:
            retention_period = int(policy.get("retentionPeriod", 0))
            rp_in_days = retention_period / 86400
            day_month = "days" if rp_in_days < 91 else "months"
            period = rp_in_days if rp_in_days < 91 else rp_in_days / 31
            display = f"{str(int(period))} {day_month}"
        return display

    @staticmethod
    def _get_config_link(bucket):
        name = bucket.get("name")
        return {
            "linkUrl": f"https://console.cloud.google.com/storage/browser/{name}",
            "gsutilLink": f"gs://{name}",
        }

    @staticmethod
    def _get_iam_policy_binding(iam_policy):
        iam_policy_binding = []
        if "bindings" in iam_policy:
            bindings = iam_policy.get("bindings")
            for binding in bindings:
                members = binding.get("members")
                role = binding.get("role", "")
                for member in members:
                    iam_policy_binding.append(
                        {
                            "member": member,
                            "role": role,
                        }
                    )

        return iam_policy_binding

    @staticmethod
    def _get_lifecycle_rule(bucket):
        life_cycle = bucket.get("lifecycle", {})
        rules = life_cycle.get("rule", [])
        num_of_rule = len(rules)

        if num_of_rule == 0:
            display = "None"
        elif num_of_rule == 1:
            display = f"{num_of_rule} rule"
        else:
            display = f"{num_of_rule} rules"

        life_cycle_rule = []
        for rule in life_cycle.get("rule", []):
            action_header = (
                "Set to" if rule.get("type") == "SetStorageClass" else "Delete"
            )
            action_footer = (
                rule.get("storage_class", "").capitalize()
                if rule.get("type") == "SetStorageClass"
                else "object"
            )

            condition_display = ""
            formatter = "%Y-%m-%d"
            condition_vo = rule.get("condition", {})
            if "customTimeBefore" in condition_vo:
                f = "Object's custom time is on or before"
                target = datetime.strptime(
                    condition_vo.get("customTimeBefore"), formatter
                ) + timedelta(days=1)
                tar_date = target.strftime("%B %d, %Y")
                condition_display = f"{f} {tar_date}"

            elif "daysSinceCustomTime" in condition_vo:
                f = "days since object's custom time"
                target = condition_vo.get("daysSinceCustomTime")
                condition_display = f"{target}+ {f}"

            elif "matchesStorageClass" in condition_vo:
                f = "Storage Class matches"
                condition_target = [
                    s.title().replace("_", " ")
                    for s in condition_vo.get("matchesStorageClass", [])
                ]
                target = ", ".join(condition_target)
                condition_display = f"{f} {target}"

            elif "age" in condition_vo:
                f = "days since object was updated"
                target = condition_vo.get("age")
                condition_display = f"{target}+ {f}"

            elif "numNewerVersions" in condition_vo:
                f = "newer versions"
                target = condition_vo.get("numNewerVersions")
                condition_display = f"{target}+ {f}"

            elif "daysSinceNoncurrentTime" in condition_vo:
                f = "days since object became noncurrent"
                target = condition_vo.get("daysSinceNoncurrentTime")
                condition_display = f"{target}+ {f}"

            elif "createdBefore" in condition_vo:
                f = "Created on or before"
                target = datetime.strptime(
                    condition_vo.get("createdBefore"), formatter
                ) + timedelta(days=1)
                tar_date = target.strftime("%B %d, %Y")
                condition_display = f"{f} {tar_date}"

            elif "isLive" in condition_vo:
                f = "Object is"
                targets_str = "live" if condition_vo.get("isLive") else "noncurrent"
                condition_display = f"{f} {targets_str}"

            elif "noncurrentTimeBefore" in condition_vo:
                f = "Object became noncurrent on or before"
                target = datetime.strptime(
                    condition_vo.get("noncurrentTimeBefore"), formatter
                ) + timedelta(days=1)
                tar_date = target.strftime("%B %d, %Y")
                condition_display = f"{f} {tar_date}"

            rule.update(
                {
                    "actionDisplay": f"{action_header} {action_footer}",
                    "conditionDisplay": condition_display,
                }
            )
            life_cycle_rule.append(rule)

        return {"lifecycleRuleDisplay": display, "rule": life_cycle_rule}

    def get_location(self, bucket):
        location_type_ref = ["multi-region", "dual-region"]
        location = bucket.get("location", "").lower()
        location_type = bucket.get("locationType", "")

        if location_type in location_type_ref:
            # Multi
            # US (Multiple Regions in United States)
            # Europe (Multiple Regions in European Union)
            # Asia Pacific (Multiple Regions in Asia)
            if location_type == "multi-region":
                location_display = (
                    f"{location} (Multiple Regions in {location.capitalize()})"
                )
            else:
                # Dual - choices
                # Americas nam4 (lowa and South Carolina)
                # Europe eur4 (Netherlands and Finland)
                # Asia Pacific asia1 (Tokyo and Osaka)

                dual_map = {
                    "nam4": "(lowa and South Carolina)",
                    "eur4": "(Netherlands and Finland)",
                    "asia1": "(Tokyo and Osaka)",
                }
                map_str = dual_map.get(location, "")
                location_display = f"{location} {map_str}"

        else:
            region = self.match_region_info(location)
            region_name = region.get("name", "")
            location_display = f"{location} | {region_name}"

        return {
            "location": location,
            "locationType": location_type.capitalize(),
            "locationDisplay": location_display,
        }

    @staticmethod
    def _get_access_control(bucket):
        access_control = "Fine-grained"
        iam_config = bucket.get("iamConfiguration", {})
        uniform = iam_config.get("uniformBucketLevelAccess", {})
        if uniform.get("enabled"):
            access_control = "Uniform"
        return access_control

    @staticmethod
    def _get_public_access(bucket, iam_policy):
        public_access_map = {
            "np": "Not public",
            "na": "Not Authorized",
            "pi": "Public to internet",
            "soa": "Subject to object ACLs",
        }

        binding_members = []
        iam_config = bucket.get("iamConfiguration", {})
        bucket_policy_only = iam_config.get("bucketPolicyOnly", {})
        uniform_bucket_level = iam_config.get("uniformBucketLevelAccess", {})
        [
            binding_members.extend(s.get("members"))
            for s in iam_policy.get("bindings", [])
        ]

        if not bucket_policy_only.get("enabled") and not uniform_bucket_level.get(
            "enabled"
        ):
            public_access = public_access_map.get("soa")
        elif "error_flag" in iam_policy:
            public_access = public_access_map.get(iam_policy.get("error_flag"))
        elif (
            "allUsers" in binding_members or "allAuthenticatedUsers" in binding_members
        ):
            public_access = public_access_map.get("pi")
        else:
            public_access = public_access_map.get("np")
        return public_access
