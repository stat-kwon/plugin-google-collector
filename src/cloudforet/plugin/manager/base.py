import abc
import logging
from spaceone.core.error import *
from spaceone.core.manager import BaseManager
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import CLOUD_LOGGING_RESOURCE_TYPE_MAP

_LOGGER = logging.getLogger(__name__)

__all__ = ["ResourceManager"]


class ResourceManager(BaseManager):
    service = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.provider = "google_cloud"
        self.cloud_service_group = ""
        self.cloud_service_type = ""

    @classmethod
    def list_managers(cls):
        return cls.__subclasses__()

    @classmethod
    def get_manager_by_service(cls, service):
        for manager in cls.list_managers():
            if manager.service == service:
                yield manager
            else:
                raise ERROR_INVALID_PARAMETER(
                    key="service", reason="Not supported service"
                )

    def collect_resources(self, options, secret_data, schema):
        _LOGGER.debug(
            f"[collect_resources] collect Field resources (options: {options})"
        )
        try:
            yield from self.collect_cloud_service_type()
            yield from self.collect_cloud_service(options, secret_data, schema)
        except Exception as e:
            yield make_error_response(
                error=e,
                provider=self.provider,
                cloud_service_group=self.cloud_service_group,
                cloud_service_type=self.cloud_service_type,
            )

    def collect_cloud_service_type(self):
        cloud_service_type = self.create_cloud_service_type()
        yield make_response(
            cloud_service_type=cloud_service_type,
            match_keys=[["name", "group", "provider"]],
            resource_type="inventory.CloudServiceType",
        )

    def collect_cloud_service(self, options, secret_data, schema):
        cloud_services = self.create_cloud_service(options, secret_data, schema)
        for cloud_service in cloud_services:
            yield make_response(
                cloud_service=cloud_service,
                match_keys=[
                    [
                        "reference.resource_id",
                        "provider",
                        "cloud_service_type",
                        "cloud_service_group",
                    ]
                ],
            )

    @staticmethod
    def set_google_cloud_logging(service, cloud_service_type, project_id, resource_id):
        cloud_logging_info = CLOUD_LOGGING_RESOURCE_TYPE_MAP[service][
            cloud_service_type
        ]
        resource_type = cloud_logging_info.get("resource_type", [])
        labels_key = cloud_logging_info.get("labels_key", [])
        return {
            "name": f"projects/{project_id}",
            "resource_id": resource_id,
            "filters": [
                {
                    "resource_type": resource_type,
                    "labels": [{"key": labels_key, "value": resource_id}],
                }
            ],
        }

    @abc.abstractmethod
    def create_cloud_service_type(self):
        raise NotImplementedError(
            "method `create_cloud_service_type` should be implemented"
        )

    @abc.abstractmethod
    def create_cloud_service(self, options, secret_data, schema):
        raise NotImplementedError("method `create_cloud_service` should be implemented")