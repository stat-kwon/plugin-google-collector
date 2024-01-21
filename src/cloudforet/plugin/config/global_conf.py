# ICON URL
ASSET_URL = "https://spaceone-custom-assets.s3.ap-northeast-2.amazonaws.com/console-assets/icons/cloud-services/google_cloud"

# Cloud Logging Settings
CLOUD_LOGGING_RESOURCE_TYPE_MAP = {
    "ComputeEngine": {
        "Instance": {
            "resource_type": "gce_instance",
            "labels_key": "resource.labels.instance_id",
        },
        "Disk": {"resource_type": "gce_disk", "labels_key": "resource.labels.disk_id"},
        "InstanceGroup": {
            "resource_type": "gce_instance_group",
            "labels_key": "resource.labels.instance_group_id",
        },
        "InstanceTemplate": {
            "resource_type": "gce_instance_template",
            "labels_key": "resource.labels.instance_template_id",
        },
        "MachineImage": {
            "resource_type": "gce_machine_image",
            "labels_key": "resource.labels.machine_image_id",
        },
    },
    "CloudSQL": {
        "Instance": {
            "resource_type": "cloudsql_database",
            "labels_key": "resource.labels.database_id",
        }
    },
    "BigQuery": {},
    "CloudStorage": {
        "Bucket": {
            "resource_type": "gcs_bucket",
            "labels_key": "resource.labels.bucket_name",
        }
    },
    "Networking": {},
    "Pub/Sub": {
        "Topic": {
            "resource_type": "pubsub_topic",
            "labels_key": "resource.labels.topic_id",
        },
        "Subscription": {
            "resource_type": "pubsub_subscription",
            "labels_key": "resource.labels.subscription_id",
        },
        "Snapshot": {
            "resource_type": "pubsub_snapshot",
            "labels_key": "resource.labels.snapshot_id",
        },
    },
    "CloudFunctions": {
        "Function": {
            "resource_type": "cloud_function",
            "labels_key": "resource.labels.function_name",
        }
    },
    "Recommender": {},
}
