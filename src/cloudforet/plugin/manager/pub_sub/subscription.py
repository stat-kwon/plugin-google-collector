import logging
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.pub_sub.subscription import SubscriptionConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class SubscriptionManager(ResourceManager):
    service = "Pub/Sub"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Pub/Sub"
        self.cloud_service_type = "Subscription"
        self.metadata_path = "plugin/metadata/pub_sub/subscription.yaml"

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
        subscription_connector = SubscriptionConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        cloud_services = []
        error_responses = []
        for subscription in subscription_connector.list_subscriptions():
            try:
                subscription_name = subscription.get("name")
                subscription_id = self._make_subscription_id(
                    subscription_name, project_id
                )
                push_config = subscription.get("pushConfig")
                bigquery_config = subscription.get("bigqueryConfig")

                subscription_display = {
                    "deliveryType": self._make_delivery_type(
                        push_config, bigquery_config
                    ),
                    "messageOrdering": self._change_boolean_to_enabled_or_disabled(
                        subscription.get("enableMessageOrdering")
                    ),
                    "exactlyOnceDelivery": self._change_boolean_to_enabled_or_disabled(
                        subscription.get("enableExactlyOnceDelivery")
                    ),
                    "attachment": self._make_enable_attachment(
                        subscription.get("topic")
                    ),
                    "retainAckedMessages": self._make_retain_yes_or_no(
                        subscription.get("retainAckedMessages")
                    ),
                }

                if message_reduction_duration := subscription.get(
                    "messageRetentionDuration"
                ):
                    subscription_display.update(
                        {
                            "retentionDuration": self._make_time_to_dhms_format(
                                message_reduction_duration
                            )
                        }
                    )

                if expiration_policy := subscription.get("expirationPolicy"):
                    ttl = self._make_time_to_dhms_format(expiration_policy.get("ttl"))
                    subscription_display.update(
                        {
                            "ttl": ttl,
                            "subscriptionExpiration": self._make_expiration_description(
                                ttl
                            ),
                        }
                    )

                if ack_deadline_seconds := subscription.get("ackDeadlineSeconds"):
                    subscription_display.update(
                        {
                            "ackDeadlineSeconds": self._make_time_to_dhms_format(
                                ack_deadline_seconds
                            )
                        }
                    )

                if retry_policy := subscription.get("retryPolicy"):
                    subscription_display.update(
                        {
                            "retryPolicy": {
                                "description": "Retry after exponential backoff delay",
                                "minimumBackoff": self._make_time_to_dhms_format(
                                    retry_policy.get("minimumBackoff")
                                ),
                                "maximumBackoff": self._make_time_to_dhms_format(
                                    retry_policy.get("maximumBackoff")
                                ),
                            }
                        }
                    )
                else:
                    subscription_display.update(
                        {"retryPolicy": {"description": "Retry immediately"}}
                    )

                subscription.update(
                    {
                        "id": subscription_id,
                        "project": project_id,
                        "display": subscription_display,
                    }
                )

                subscription.update(
                    {
                        "google_cloud_logging": self.set_google_cloud_logging(
                            "Pub/Sub", "Subscription", project_id, subscription_name
                        )
                    }
                )

                cloud_services.append(
                    make_cloud_service(
                        name=subscription_name,
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        tags=subscription.get("labels", []),
                        data=subscription,
                        region_code="global",
                        instance_type="",
                        instance_size=0,
                        reference={
                            "resource_id": subscription_id,
                            "external_link": f"https://console.cloud.google.com/cloudpubsub/subscription/detail/{subscription_id}?project={project_id}",
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on Subscription {subscription.get('name')}: {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def _make_time_to_dhms_format(self, duration):
        if isinstance(duration, int):
            return self._display_time(duration)
        if isinstance(duration, str):
            seconds, _ = duration.split("s")
            return self._display_time(int(seconds))

    @staticmethod
    def _display_time(seconds, granularity=2):
        result = []
        intervals = (
            ("days", 86400),
            ("hr", 3600),
            ("min", 60),
            ("seconds", 1),
        )
        for name, count in intervals:
            value = seconds // count
            if value:
                seconds -= value * count
                if value == 1:
                    name = name.rstrip("s")
                result.append(f"{value} {name}")
        return " ".join(result[:granularity])

    @staticmethod
    def _make_delivery_type(push_config, bigquery_config):
        if push_config:
            delivery_type = "Push"
        elif bigquery_config:
            delivery_type = "BigQuery"
        else:
            delivery_type = "Pull"
        return delivery_type

    @staticmethod
    def _make_subscription_id(subscription_name, project_id):
        path, topic_id = subscription_name.split(
            f"projects/{project_id}/subscriptions/"
        )
        return topic_id

    @staticmethod
    def _change_boolean_to_enabled_or_disabled(boolean_field):
        if boolean_field:
            return "Enabled"
        else:
            return "Disabled"

    @staticmethod
    def _make_enable_attachment(topic):
        if topic == "_deleted-topic_":
            return "Unattached"
        else:
            return "Attached"

    @staticmethod
    def _make_retain_yes_or_no(retain_acked_messages):
        if retain_acked_messages:
            return "Yes"
        else:
            return "No"

    @staticmethod
    def _make_expiration_description(ttl):
        return f"Subscription expires in {ttl} if there is no activity"
