import logging
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.pub_sub.schema import SchemaConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class SchemaManager(ResourceManager):
    service = "Pub/Sub"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Pub/Sub"
        self.cloud_service_type = "Schema"
        self.metadata_path = "plugin/metadata/pub_sub/schema.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="Cloud Pub/Sub",
            tags={"spaceone:icon": f"{ASSET_URL}/cloud_pubsub.svg"},
            labels=["Application Integration"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        schema_connector = SchemaConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        cloud_services = []
        error_responses = []
        for schema_name in schema_connector.list_schema_names():
            try:
                schema = schema_connector.get_schema(schema_name)
                schema_id = self._make_schema_id(schema_name, project_id)

                display = {"outputDisplay": "show"}

                schema.update(
                    {
                        "id": schema_id,
                        "project": project_id,
                        "schemaType": schema.get("type"),
                        "display": display,
                    }
                )
                self.set_region_code("global")
                cloud_services.append(
                    make_cloud_service(
                        name=schema_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=schema,
                        region_code="global",
                        instance_type="",
                        instance_size=0,
                        reference={
                            "resource_id": schema_name,
                            "external_link": f"https://console.cloud.google.com/cloudpubsub/schema/detail/{schema_name}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Schema {schema_name}: {e}")

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
    def _make_schema_id(schema_name, project_id):
        path, schema_id = schema_name.split(f"projects/{project_id}/schemas/")
        return schema_id
