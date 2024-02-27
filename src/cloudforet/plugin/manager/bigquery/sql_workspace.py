import logging
from datetime import datetime
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.bigquery.sql_workspace import SQLWorkspaceConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger(__name__)


class SQLWorkspaceManager(ResourceManager):
    service = "BigQuery"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "BigQuery"
        self.cloud_service_type = "SQLWorkspace"
        self.metadata_path = "plugin/metadata/bigquery/sql_workspace.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="BigQuery",
            tags={"spaceone:icon": f"{ASSET_URL}/Big_Query.svg"},
            labels=["Analytics"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        big_query_conn = SQLWorkspaceConnector(
            options=options, secret_data=secret_data, schema=schema
        )
        projects = big_query_conn.list_projects()
        for data_set in big_query_conn.list_dataset():
            update_bq_dt_tables = []
            table_schemas = []
            print(data_set)

            data_refer = data_set.get("datasetReference", {})
            data_set_id = data_refer.get("datasetId", "")
            dataset_project_id = data_refer.get("projectId")
            bq_dataset = big_query_conn.get_dataset(data_set_id)
            creation_time = bq_dataset.get("creationTime", "")
            last_modified_time = bq_dataset.get("lastModifiedTime")
            region = self._get_region(bq_dataset.get("location", ""))
            exp_partition_ms = bq_dataset.get("defaultPartitionExpirationMs")
            exp_table_ms = bq_dataset.get("defaultTableExpirationMs")

            labels = self.convert_labels_format(bq_dataset.get("labels", {}))
            google_cloud_monitoring_filters = [
                {"key": "resource.labels.dataset_id", "value": data_set_id}
            ]

            bq_dataset.update(
                {
                    "name": data_set_id,
                    "project": project_id,
                    "tables": update_bq_dt_tables,
                    "table_schemas": table_schemas,
                    "region": region,
                    "visible_on_console": self._get_visible_on_console(data_set_id),
                    "matching_projects": self._get_matching_project(
                        dataset_project_id, projects
                    ),
                    "creationTime": self._convert_unix_timestamp(creation_time),
                    "lastModifiedTime": self._convert_unix_timestamp(
                        last_modified_time
                    ),
                    "default_partition_expiration_ms_display": self._convert_milliseconds_to_minutes(
                        exp_partition_ms
                    ),
                    "default_table_expiration_ms_display": self._convert_milliseconds_to_minutes(
                        exp_table_ms
                    ),
                    "labels": labels,
                    "google_cloud_monitoring": self.set_google_cloud_monitoring(
                        project_id,
                        "bigquery.googleapis.com",
                        data_set_id,
                        google_cloud_monitoring_filters,
                    ),
                }
            )

            self.set_region_code(region)
            yield make_cloud_service(
                name=data_set_id,
                cloud_service_type=self.cloud_service_type,
                cloud_service_group=self.cloud_service_group,
                provider=self.provider,
                account=project_id,
                data=bq_dataset,
                region_code=region,
                reference={
                    "resource_id": data_set_id,
                    "external_link": f"https://console.cloud.google.com/bigquery?project={project_id}&p={self.dataset_reference.project_id}&page=dataset&d={data_set_id}",
                },
            )

    def _check_sql_instance_is_available(self, instance):
        power_state = self._get_display_state(instance)
        create_state = instance.get("state", "")

        if create_state == "RUNNABLE" and power_state == "RUNNING":
            return True
        else:
            instance_name = instance.get("name", "")
            _LOGGER.debug(
                f"[_check_sql_instance_is_available] instance {instance_name} is not available"
            )
            return False

    @staticmethod
    def _get_display_state(instance):
        activation_policy = instance.get("settings", {}).get(
            "activationPolicy", "UNKNOWN"
        )

        if activation_policy in ["ALWAYS"]:
            if instance.get("state") == "PENDING_CREATE":
                return "CREATING"
            elif instance.get("state") == "RUNNABLE":
                return "RUNNING"
        elif activation_policy in ["NEVER"]:
            return "STOPPED"
        elif activation_policy in ["ON_DEMAND"]:
            return "ON-DEMAND"

        return "UNKNOWN"

    def _get_region(self, location):
        matched_info = self.match_region_info(location)
        return matched_info.get("region_code") if matched_info else "global"

    @staticmethod
    def _get_visible_on_console(dataset_id):
        return False if dataset_id.startswith("_") else True

    @staticmethod
    def _get_matching_project(project_id, projects):
        _projects = []
        for project in projects:
            if project_id == project.get("id"):
                _projects.append(ProjectModel(project, strict=False))
        return _projects

    @staticmethod
    def _convert_unix_timestamp(unix_timestamp):
        if unix_timestamp:
            try:
                return datetime.fromtimestamp(int(unix_timestamp) / 1000)
            except Exception as e:
                _LOGGER.error(f"[_convert_unix_timestamp] {e}")

        return None

    @staticmethod
    def _convert_milliseconds_to_minutes(milliseconds):
        if milliseconds:
            minutes = (int(milliseconds) / 1000) / 60
            return minutes
        else:
            return None
