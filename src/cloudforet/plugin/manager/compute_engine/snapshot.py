import logging
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.compute_engine.snapshot import SnapshotConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class SnapshotManager(ResourceManager):
    service = "ComputeEngine"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "ComputeEngine"
        self.cloud_service_type = "Snapshot"
        self.metadata_path = "plugin/metadata/compute_engine/snapshot.yaml"

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
        snapshot_id = ""
        snapshot_conn = SnapshotConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        snapshots = snapshot_conn.list_snapshot()

        cloud_services = []
        error_responses = []
        for snapshot in snapshots:
            try:
                snapshot_id = snapshot.get("id")
                region = self.get_matching_region(snapshot.get("storageLocations"))
                region_code = region.get("regionCode")
                labels = snapshot.get("labels", {})

                snapshot.update(
                    {
                        "project": project_id,
                        "disk": self.get_disk_info(snapshot),
                        "creationType": "Scheduled"
                        if snapshot.get("autoCreated")
                        else "Manual",
                        "encryption": self.get_disk_encryption_type(
                            snapshot.get("snapshotEncryptionKey")
                        ),
                        "labels": labels,
                    }
                )

                _name = snapshot.get("name", "")

                self.set_region_code(region_code)
                cloud_services.append(
                    make_cloud_service(
                        name=_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        tags=labels,
                        data=snapshot,
                        region_code=region_code,
                        reference={
                            "resource_id": snapshot.get("selfLink", ""),
                            "external_link": f"https://console.cloud.google.com/compute/snapshotsDetail/projects/{project_id}/global/snapshots/{_name}?authuser=2&project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Snapshot {snapshot_id}: {e}", exc_info=True)

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def get_matching_region(self, svc_location):
        region_code = svc_location[0] if svc_location else "global"
        matched_info = self.match_region_info(region_code)
        return (
            {"regionCode": region_code, "location": "regional"}
            if matched_info
            else {"regionCode": "global", "location": "multi"}
        )

    def get_disk_info(self, snapshot):
        """
        source_disk = StringType()
        source_disk_display = StringType()
        source_disk_id = StringType()
        diskSizeGb = IntType()
        disk_size_display = StringType()
        storage_bytes = IntType()
        storage_bytes_display = StringType()
        """
        disk_gb = snapshot.get("diskSizeGb", 0.0)
        st_byte = snapshot.get("storageBytes", 0)
        size = self._get_bytes(int(disk_gb))
        return {
            "sourceDisk": snapshot.get("sourceDisk", ""),
            "sourceDiskDisplay": self.get_param_in_url(
                snapshot.get("sourceDisk", ""), "disks"
            ),
            "sourceDiskId": snapshot.get("sourceDiskId", ""),
            "diskSize": float(size),
            "storageBytes": int(st_byte),
        }

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
