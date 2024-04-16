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
        cloud_services = []
        error_responses = []
        for data_set in big_query_conn.list_dataset():
            try:
                updated_bq_tables = []
                data_refer = data_set.get("datasetReference", {})
                data_set_id = data_refer.get("datasetId", "")
                bq_dataset = big_query_conn.get_dataset(data_set_id)
                creation_time = bq_dataset.get("creationTime", "")
                last_modified_time = bq_dataset.get("lastModifiedTime")
                region = self._get_region(bq_dataset.get("location", ""))
                exp_partition_ms = bq_dataset.get("defaultPartitionExpirationMs")
                exp_table_ms = bq_dataset.get("defaultTableExpirationMs")

                bq_tables = big_query_conn.list_tables(data_set_id)
                if bq_tables:
                    updated_bq_tables = self._preprocess_bigquery_tables_info(bq_tables)

                labels = self.convert_labels_format(bq_dataset.get("labels", {}))
                google_cloud_monitoring_filters = [
                    {"key": "resource.labels.dataset_id", "value": data_set_id}
                ]

                bq_dataset.update(
                    {
                        "name": data_set_id,
                        "project": project_id,
                        "tables": updated_bq_tables,
                        "region": region,
                        "creationTime": self._convert_unix_timestamp(creation_time),
                        "lastModifiedTime": self._convert_unix_timestamp(
                            last_modified_time
                        ),
                        "defaultPartitionExpirationMsDisplay": self._convert_milliseconds_to_minutes(
                            exp_partition_ms
                        ),
                        "defaultTableExpirationMsDisplay": self._convert_milliseconds_to_minutes(
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
                cloud_services.append(
                    make_cloud_service(
                        name=data_set_id,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=bq_dataset,
                        region_code=region,
                        reference={
                            "resource_id": data_set_id,
                            "external_link": f"https://console.cloud.google.com/bigquery?project={project_id}&p={project_id}&page=dataset&d={data_set_id}",
                        },
                    )
                )
            except Exception as e:
                _LOGGER.error(
                    f"[create_cloud_service] Error on BigQuery Workspace {data_set.get('datasetId')}: {e}"
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

    def _get_region(self, location):
        matched_info = self.match_region_info(location)
        return matched_info.get("region_code") if matched_info else "global"

    def _preprocess_bigquery_tables_info(self, bq_tables):
        preprocessed_bq_tables = []
        for bq_table in bq_tables:
            table_id = bq_table.get("id")
            name = bq_table.get("tableReference", {}).get("tableId")
            table_type = bq_table.get("type")
            creation_time = bq_table.get("creationTime")
            expiration_time = bq_table.get("expirationTime")
            last_modified_time = bq_table.get("lastModifiedTime")

            bq_table.update(
                {
                    "id": table_id,
                    "name": name,
                    "type": table_type,
                    "creationTime": self._convert_unix_timestamp(creation_time),
                    "expirationTime": self._convert_unix_timestamp(expiration_time),
                    "lastModifiedTime": self._convert_unix_timestamp(
                        last_modified_time
                    ),
                }
            )
            preprocessed_bq_tables.append(bq_table)

        return preprocessed_bq_tables

    @staticmethod
    def _convert_milliseconds_to_minutes(milliseconds):
        if milliseconds:
            minutes = (int(milliseconds) / 1000) / 60
            return minutes
        else:
            return None

    @staticmethod
    def _convert_unix_timestamp(unix_timestamp):
        if unix_timestamp:
            try:
                return datetime.fromtimestamp(int(unix_timestamp) / 1000).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )
            except Exception as e:
                _LOGGER.error(f"[_convert_unix_timestamp] {e}")
        return None

    def _get_region(self, location):
        matched_info = self.match_region_info(location)
        return matched_info.get("region_code") if matched_info else "global"
