import logging
from datetime import datetime, timedelta

from spaceone.inventory.plugin.collector.lib import *
from cloudforet.plugin.manager import ResourceManager
from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.cloud_functions.function_gen1 import (
    FunctionGen1Connector,
)

_LOGGER = logging.getLogger(__name__)


class FunctionGen1Manager(ResourceManager):
    service = "CloudFunctions"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "CloudFunctions"
        self.cloud_service_type = "Function"
        self.metadata_path = "plugin/metadata/cloud_functions/function_gen1.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="Cloud Functions",
            tags={
                "spaceone:icon": f"{ASSET_URL}/cloud_functions.svg",
                "spaceone:display_name": "CloudFunctions",
            },
            labels=["Compute"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        function_conn = FunctionGen1Connector(
            options=options, secret_data=secret_data, schema=schema
        )

        cloud_services = []
        error_responses = []
        for function in function_conn.list_functions():
            try:
                function_name = function.get("name")
                location, function_id = self._make_location_and_id(
                    function_name, project_id
                )
                self.set_region_code(location)
                labels = function.get("labels")

                display = {
                    "state": function.get("status"),
                    "region": location,
                    "environment": "1st gen",
                    "functionId": function_id,
                    "lastDeployed": self._make_last_deployed(function["updateTime"]),
                    "runtime": self._make_runtime_for_readable(function["runtime"]),
                    "timeout": self._make_timeout(function["timeout"]),
                    "executedFunction": function.get("entryPoint"),
                    "memoryAllocated": self._make_memory_allocated(
                        function["availableMemoryMb"]
                    ),
                    "ingressSettings": self._make_ingress_setting_readable(
                        function["ingressSettings"]
                    ),
                    "vpcConnectorEgressSettings": self._make_vpc_egress_readable(
                        function.get("vpcConnectorEgressSettings")
                    ),
                }

                if http_trigger := function.get("httpsTrigger"):
                    display.update({"trigger": "HTTP", "httpUrl": http_trigger["url"]})

                if event_trigger := function.get("eventTrigger"):
                    trigger = self._get_display_name(event_trigger.get("service"))
                    display.update({"trigger": trigger, "eventProvider": trigger})

                if runtime_environment_variables := function.get(
                    "environmentVariables"
                ):
                    display.update(
                        {
                            "runtimeEnvironmentVariables": self._dict_to_list_of_dict(
                                runtime_environment_variables
                            )
                        }
                    )
                if build_environment_variables := function.get(
                    "buildEnvironmentVariables"
                ):
                    display.update(
                        {
                            "buildEnvironmentVariables": self._dict_to_list_of_dict(
                                build_environment_variables
                            )
                        }
                    )

                function.update({"project": project_id, "display": display})

                function.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "CloudFunctions", "Function", project_id, function_id
                        )
                    }
                )

                cloud_services.append(
                    make_cloud_service(
                        name=function_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=function,
                        region_code=location,
                        instance_type="",
                        instance_size=0,
                        reference={
                            "resource_id": function_name,
                            "external_link": f"https://console.cloud.google.com/functions/details/{location}/{function_id}?env=gen1&project={project_id}",
                        },
                        tags=labels,
                    )
                )
            except Exception as e:
                _LOGGER.error(f"Error on Function {function.get('name')}: {e}")

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
    def _make_location_and_id(function_name, project_id):
        project_path, location_and_id_path = function_name.split(
            f"projects/{project_id}/locations/"
        )
        location, function, function_id = location_and_id_path.split("/")
        return location, function_id

    @staticmethod
    def _make_last_deployed(update_time):
        update_time, microseconds = update_time.split(".")
        updated_time = datetime.strptime(update_time, "%Y-%m-%dT%H:%M:%S")
        korea_time = updated_time + timedelta(hours=9)
        return f'{korea_time.strftime("%m/%d, %Y,%I:%M:%S %p")} GMT+9'

    @staticmethod
    def _make_runtime_for_readable(runtime):
        runtime_map = {
            "dotnet6": ".NET 6.0",
            "dotnet3": ".NET Core 3.1",
            "go119": "Go 1.19",
            "go118": "Go 1.18",
            "go116": "Go 1.16",
            "go113": "Go 1.13",
            "java17": "Java 17",
            "java11": "Java 11",
            "nodejs12": "Node.js 12",
            "nodejs14": "Node.js 14",
            "nodejs16": "Node.js 16",
            "nodejs18": "Node.js 18",
            "php81": "PHP 8.1",
            "php74": "PHP 7.4",
            "python38": "Python 3.8",
            "python39": "Python 3.9",
            "python310": "Python 3.10",
            "ruby30": "Ruby 3.0",
            "ruby27": "Ruby 2.7",
            "ruby26": "Ruby 2.6",
        }
        return runtime_map.get(runtime, "Not Found")

    @staticmethod
    def _make_timeout(timeout):
        return f"{timeout[:-1]} seconds"

    @staticmethod
    def _make_memory_allocated(memory):
        return f"{memory} MiB"

    @staticmethod
    def _make_ingress_setting_readable(ingress_settings):
        ingress_settings = ingress_settings.replace("_", " ").lower()
        return ingress_settings[0].upper() + ingress_settings[1:]

    @staticmethod
    def _make_vpc_egress_readable(egress_settings):
        if egress_settings:
            egress_settings = egress_settings.replace("_", " ").lower()
            first_character, other_character = egress_settings[0:3], egress_settings[1:]

            if first_character == "vpc":
                first_character = "VPC"
            elif first_character == "all":
                first_character = "All"
            else:
                first_character = "Pri"
            return first_character + other_character
        else:
            return ""

    @staticmethod
    def _get_display_name(trigger_service):
        try:
            service, path = trigger_service.split(".googleapis.com")
        except ValueError:
            service = "analytics"
        service_map = {
            "storage": "Cloud Storage",
            "pubsub": "Cloud Pub/Sub",
            "firestore": "Cloud Firestore",
            "firebaseauth": "Firebase Authentication",
            "firebasestorage": "Cloud Storage for Firebase",
            "firebaseremoteconfig": "Firebase Remote Config",
            "analytics": "Google Analytics for Firebase",
        }
        return service_map[service]

    @staticmethod
    def _dict_to_list_of_dict(dict_variables: dict) -> list:
        variables = []
        for key, value in dict_variables.items():
            variables.append({"key": key, "value": value})
        return variables
