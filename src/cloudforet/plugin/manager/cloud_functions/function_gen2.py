import logging
from datetime import datetime, timedelta

from spaceone.inventory.plugin.collector.lib import *
from cloudforet.plugin.manager import ResourceManager
from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.cloud_functions.function_gen2 import (
    FunctionGen2Connector,
)
from cloudforet.plugin.connector.cloud_functions.eventarc import EventarcConnector

_LOGGER = logging.getLogger(__name__)


class FunctionGen2Manager(ResourceManager):
    service = "CloudFunctions"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "CloudFunctions"
        self.cloud_service_type = "Function"
        self.metadata_path = "plugin/metadata/cloud_functions/function_gen2.yaml"

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
        function_conn = FunctionGen2Connector(
            options=options, secret_data=secret_data, schema=schema
        )
        trigger_provider_map = self._create_trigger_provider_map(
            options, secret_data, schema
        )

        functions = [
            function
            for function in function_conn.list_functions()
            if function.get("environment") == "GEN_2"
        ]

        cloud_services = []
        error_responses = []
        for function in functions:
            try:
                function_name = function.get("name")
                location, function_id = self._make_location_and_id(
                    function_name, project_id
                )
                self.set_region_code(location)
                labels = function.get("labels")

                display = {
                    "state": function.get("state"),
                    "region": location,
                    "environment": self._make_readable_environment(
                        function["environment"]
                    ),
                    "functionId": function_id,
                    "lastDeployed": self._make_last_deployed(function["updateTime"]),
                    "runtime": self._make_runtime_for_readable(
                        function["buildConfig"]["runtime"]
                    ),
                    "timeout": self._make_timeout(
                        function["serviceConfig"]["timeoutSeconds"]
                    ),
                    "executedFunction": function["buildConfig"].get("entryPoint"),
                    "memoryAllocated": self._make_memory_allocated(
                        function["serviceConfig"]["availableMemory"]
                    ),
                    "ingressSettings": self._make_ingress_setting_readable(
                        function["serviceConfig"].get("ingressSettings")
                    ),
                    "vpcConnectorEgressSettings": self._make_vpc_egress_readable(
                        function["serviceConfig"].get("vpcConnectorEgressSettings")
                    ),
                }

                if trigger_data := function.get("eventTrigger"):
                    trigger = self._get_event_provider_from_trigger_map(
                        trigger_data.get("eventType"), trigger_provider_map
                    )
                    display.update(
                        {
                            "trigger": trigger,
                            "eventProvider": trigger,
                            "triggerName": self._make_trigger_name(
                                trigger_data.get("trigger")
                            ),
                            "retryPolicy": self._make_retry_policy(
                                trigger_data.get(
                                    "retryPolicy", "RETRY_POLICY_UNSPECIFIED"
                                )
                            ),
                        }
                    )
                else:
                    display.update({"trigger": "HTTP"})

                if runtime_environment_variables := function["serviceConfig"].get(
                    "environmentVariables", {}
                ):
                    display.update(
                        {
                            "runtimeEnvironmentVariables": self._dict_to_list_of_dict(
                                runtime_environment_variables
                            )
                        }
                    )
                if build_environment_variables := function["buildConfig"].get(
                    "environmentVariables", {}
                ):
                    display.update(
                        {
                            "buildEnvironmentVariables": self._dict_to_list_of_dict(
                                build_environment_variables
                            )
                        }
                    )

                function.update(
                    {
                        # 'function_id': function_id,
                        "project": project_id,
                        "display": display,
                    }
                )

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
                            "external_link": f"https://console.cloud.google.com/functions/details/{location}/{function_id}?env=gen2&project={project_id}",
                        },
                        tags=labels,
                    )
                )
            except Exception as e:
                _LOGGER.error(
                    f"Error on Gen2 Cloud Functions {function.get('name')}: {e}"
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

    @staticmethod
    def _list_providers_from_eventarc(options, secret_data, schema):
        eventarc_conn = EventarcConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        providers = eventarc_conn.list_providers()
        return providers

    def _create_trigger_provider_map(self, options, secret_data, schema):
        providers = self._list_providers_from_eventarc(options, secret_data, schema)

        trigger_provider_map = {}
        for provider in providers:
            display_name = provider["displayName"]

            event_types = []
            for event_type in provider["eventTypes"]:
                if display_name in trigger_provider_map:
                    if event_type not in trigger_provider_map[display_name]:
                        event_types.append(event_type["type"])
                else:
                    event_types.append(event_type["type"])
            trigger_provider_map[display_name] = event_types
        return trigger_provider_map

    @staticmethod
    def _make_location_and_id(function_name, project_id):
        project_path, location_and_id_path = function_name.split(
            f"projects/{project_id}/locations/"
        )
        location, function, function_id = location_and_id_path.split("/")
        return location, function_id

    @staticmethod
    def _make_readable_environment(environment):
        environment_map = {
            "GEN_1": "1st gen",
            "GEN_2": "2nd gen",
            "ENVIRONMENT_UNSPECIFIED": "unspecified",
        }
        return environment_map[environment]

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
        return f"{timeout} seconds"

    @staticmethod
    def _make_memory_allocated(memory):
        try:
            number, unit = memory.split("Mi")
            return f"{number} MiB"
        except ValueError:
            number, unit = memory.split("M")
            return f"{number} MiB"
        except Exception:
            number, unit = memory.split("Gi")
            return f"{number} GiB"

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
    def _get_event_provider_from_trigger_map(event_type, trigger_provider_map):
        for display_name, event_types in trigger_provider_map.items():
            if event_type in event_types:
                return display_name
        return "Not Found"

    @staticmethod
    def _make_trigger_name(trigger_id):
        path, trigger_name = trigger_id.split("triggers/")
        return trigger_name

    @staticmethod
    def _make_retry_policy(retry_policy):
        if retry_policy == "RETRY_POLICY_RETRY":
            return "Enabled"
        elif retry_policy == "RETRY_POLICY_DO_NOT_RETRY":
            return "Disabled"
        else:
            return "Unspecified"

    @staticmethod
    def _dict_to_list_of_dict(dict_variables: dict) -> list:
        variables = []
        for key, value in dict_variables.items():
            variables.append({"key": key, "value": value})
        return variables
