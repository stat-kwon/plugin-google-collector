import logging
from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.pub_sub.topic import TopicConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger(__name__)


class TopicManager(ResourceManager):
    service = "Pub/Sub"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Pub/Sub"
        self.cloud_service_type = "Topic"
        self.metadata_path = "plugin/metadata/pub_sub/topic.yaml"

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
        topic_connector = TopicConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        for topic in topic_connector.list_topics():
            topic_name = topic.get("name")
            topic_id = self._make_topic_id(topic_name, project_id)
            labels = topic.get("labels")
            message_retention_duration = topic.get("messageRetentionDuration")

            subscriptions = []
            subscription_names = topic_connector.list_subscription_names(topic_name)
            for subscription_name in subscription_names:
                subscription = topic_connector.get_subscription(subscription_name)
                push_config = subscription.get("pushConfig")
                bigquery_config = subscription.get("bigqueryConfig")
                subscription.update(
                    {
                        "id": self._make_subscription_id(subscription_name),
                        "deliveryType": self._make_delivery_type(
                            push_config, bigquery_config
                        ),
                    }
                )

            snapshots = []
            snapshot_names = topic_connector.list_snapshot_names(topic_name)
            for snapshot_name in snapshot_names:
                snapshot = topic_connector.get_snapshot(snapshot_name)
                snapshot.update({"id": self._make_snapshot_id(snapshot_name)})

            display = {
                "subscriptionCount": len(subscription_names),
                "encryptionKey": self._get_encryption_key(topic.get("kmsKeyName")),
            }
            if message_retention_duration:
                display.update(
                    {
                        "retention": self._change_duration_to_dhm(
                            message_retention_duration
                        )
                    }
                )

            topic.update(
                {
                    "topic_id": topic_id,
                    "project": project_id,
                    "messageRetentionDuration": message_retention_duration,
                    "subscriptions": subscriptions,
                    "snapshots": snapshots,
                    "display": display,
                }
            )

            topic.update(
                {
                    "google_cloud_logging": self.set_google_cloud_logging(
                        "Pub/Sub", "Topic", project_id, topic_name
                    )
                }
            )

            yield make_cloud_service(
                name=topic_name,
                cloud_service_type=self.cloud_service_type,
                cloud_service_group=self.cloud_service_group,
                provider=self.provider,
                account=project_id,
                tags=labels,
                data=topic,
                region_code="Global",
                instance_type="",
                instance_size=0,
                reference={
                    "resource_id": topic_id,
                    "external_link": f"https://console.cloud.google.com/cloudpubsub/topic/detail/{topic_id}?project={project_id}",
                },
            )

    def _change_duration_to_dhm(self, duration):
        seconds, _ = duration.split("s")
        return self._display_time(int(seconds))

    @staticmethod
    def _make_topic_id(topic_name, project_id):
        path, topic_id = topic_name.split(f"projects/{project_id}/topics/")
        return topic_id

    @staticmethod
    def _get_encryption_key(kms_key_name):
        if kms_key_name:
            encryption_key = "Customer managed"
        else:
            encryption_key = "Google managed"
        return encryption_key

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
    def _make_snapshot_id(snapshot_name):
        *path, snapshot_id = snapshot_name.split("/")
        return snapshot_id

    @staticmethod
    def _make_subscription_id(subscription_name):
        *path, subscription_id = subscription_name.split("/")
        return subscription_id
