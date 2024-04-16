import logging
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.cloud_sql.instance import CloudSQLInstanceConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class CloudSQLManager(ResourceManager):
    service = "CloudSQL"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "CloudSQL"
        self.cloud_service_type = "Instance"
        self.metadata_path = "plugin/metadata/cloud_sql/instance.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="Cloud SQL",
            tags={"spaceone:icon": f"{ASSET_URL}/Cloud_SQL.svg"},
            labels=["Database"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        cloud_sql_conn = CloudSQLInstanceConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        cloud_services = []
        error_responses = []
        for instance in cloud_sql_conn.list_instances():
            try:
                instance_name = instance["name"]
                region = instance["region"]

                if self._check_sql_instance_is_available(instance):
                    databases = cloud_sql_conn.list_databases(instance_name)
                    users = cloud_sql_conn.list_users(instance_name)
                else:
                    databases = []
                    users = []

                monitoring_resource_id = f"{project_id}:{instance_name}"
                instance.update(
                    {
                        "google_cloud_monitoring": self.set_google_cloud_monitoring(
                            project_id,
                            "cloudsql.googleapis.com/database",
                            monitoring_resource_id,
                            [
                                {
                                    "key": "resource.labels.database_id",
                                    "value": monitoring_resource_id,
                                }
                            ],
                        ),
                        "displayState": self._get_display_state(instance),
                        "databases": [database for database in databases],
                        "users": [user for user in users],
                    }
                )

                instance.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "CloudSQL", "Instance", project_id, monitoring_resource_id
                        )
                    }
                )

                self.set_region_code(region)

                cloud_services.append(
                    make_cloud_service(
                        name=instance_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=instance,
                        region_code=region,
                        reference={
                            "resource_id": instance_name,
                            "external_link": f"https://console.cloud.google.com/sql/instances/{instance_name}/overview?authuser=1&project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(
                    f"Error on Instance of Cloud SQL {instance.get('name')}: {e}"
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
