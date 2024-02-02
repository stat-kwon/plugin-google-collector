import logging

from spaceone.inventory.plugin.collector.lib.server import CollectorPluginServer

from cloudforet.plugin.manager import ResourceManager

app = CollectorPluginServer()

_LOGGER = logging.getLogger(__name__)


@app.route("Collector.init")
def collector_init(params: dict) -> dict:
    return _create_init_metadata()


@app.route("Collector.verify")
def collector_verify(params: dict) -> None:
    pass


@app.route("Collector.collect")
def collector_collect(params: dict) -> dict:
    options = params["options"]
    secret_data = params["secret_data"]
    schema = params.get("schema")

    if services := options.get("cloud_service_types"):
        for service in services:
            resource_mgrs = ResourceManager.get_manager_by_service(service)
            for resource_mgr in resource_mgrs:
                results = resource_mgr().collect_resources(options, secret_data, schema)
                for result in results:
                    yield result
    else:
        resource_mgrs = ResourceManager.list_managers()
        for manager in resource_mgrs:
            results = manager().collect_resources(options, secret_data, schema)

            for result in results:
                yield result


@app.route("Job.get_tasks")
def job_get_tasks(params: dict) -> dict:
    pass


def _create_init_metadata():
    return {
        "metadata": {
            "supported_resource_type": [
                "inventory.CloudService",
                "inventory.CloudServiceType",
                "inventory.Region",
                "inventory.ErrorResource",
            ],
            "options_schema": {},
        }
    }
