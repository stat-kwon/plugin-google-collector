import logging
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.pub_sub.snapshot import SnapshotConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger(__name__)


class SnapshotManager(ResourceManager):
    service = "Pub/Sub"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Pub/Sub"
        self.cloud_service_type = "Snapshot"
        self.metadata_path = "plugin/metadata/pub_sub/snapshot.yaml"

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
        snapshot_connector = SnapshotConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        for snapshot in snapshot_connector.list_snapshots():
            snapshot_name = snapshot.get("name")
            snapshot_id = self._make_snapshot_id(snapshot_name, project_id)
            snapshot.update(
                {
                    "id": snapshot_id,
                    "project": project_id,
                    "google_cloud_logging": self.set_google_cloud_logging(
                        "Pub/Sub", "Snapshot", project_id, snapshot_name
                    ),
                }
            )

            yield make_cloud_service(
                name=snapshot_name,
                cloud_service_type=self.cloud_service_type,
                cloud_service_group=self.cloud_service_group,
                provider=self.provider,
                account=project_id,
                tags=snapshot.get("labels", []),
                data=snapshot,
                region_code="Global",
                instance_type="",
                instance_size=0,
                reference={
                    "resource_id": snapshot_id,
                    "external_link": f"https://console.cloud.google.com/cloudpubsub/snapshot/detail/{snapshot_id}?project={project_id}",
                },
            )

    @staticmethod
    def _make_snapshot_id(snapshot_name, project_id):
        path, snapshot_id = snapshot_name.split(f"projects/{project_id}/snapshots/")
        return snapshot_id
