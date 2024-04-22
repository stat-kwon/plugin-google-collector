from cloudforet.plugin.connector.compute_engine.vm_instance import VMInstanceConnector


class DiskHelper:
    def get_disk_info(self, instance, disk_list):
        """
        disk_data = {
            "device_index": 0,
            "device": "",
            "disk_type": "EBS",
            "size": 100,
            "tags": {
                disk_id = StringType(serialize_when_none=False)
                disk_name = StringType(serialize_when_none=False)
                description = StringType(serialize_when_none=False)
                zone = StringType(serialize_when_none=False)
                disk_type = StringType(choices=('local-ssd', 'pd-balanced', 'pd-ssd', 'pd-standard'), serialize_when_none=False)
                encrypted = BooleanType(default=True)
                read_iops = FloatType(serialize_when_none=False)
                write_iops = FloatType(serialize_when_none=False)
                read_throughput = FloatType(serialize_when_none=False)
                write_throughput = FloatType(serialize_when_none=False)
                labels = DictType(StringType, default={}, serialize_when_none=False)
            }
        }
        """
        disks = []
        int_disks = instance.get("disks", [])
        for int_disk in int_disks:
            single_disk_tag = {}
            disk_sz = float(int_disk.get("diskSizeGb"))
            matching_single_disk_tag = self._get_matched_disk_tag_info(
                int_disk, disk_list
            )
            if matching_single_disk_tag is not None:
                single_disk_type = self._get_disk_type(matching_single_disk_tag)
                single_disk_tag.update(
                    {
                        "diskId": matching_single_disk_tag.get("id", ""),
                        "diskName": matching_single_disk_tag.get("name", ""),
                        "description": matching_single_disk_tag.get("description", ""),
                        "diskType": single_disk_type,
                        "encrypted": True,
                        "readIops": self.get_iops_rate(
                            single_disk_type, disk_sz, "read"
                        ),
                        "writeIops": self.get_iops_rate(
                            single_disk_type, disk_sz, "write"
                        ),
                        "readThroughput": self.get_throughput_rate(
                            single_disk_type, disk_sz
                        ),
                        "writeThroughput": self.get_throughput_rate(
                            single_disk_type, disk_sz
                        ),
                        "labels": self._get_labels(matching_single_disk_tag),
                    }
                )
            size = self._get_bytes(int(matching_single_disk_tag.get("sizeGb")))
            single_disk = {
                "deviceIndex": int_disk.get("index"),
                "device": "",
                "diskType": "disk",
                "size": float(size),
                "tags": single_disk_tag,
            }

            disks.append(single_disk)

        return disks

    def get_iops_rate(self, disk_type, disk_size, flag):
        const = self._get_iops_constant(disk_type, flag)
        return round(disk_size * const, 1)

    def get_throughput_rate(self, disk_type, disk_size):
        const = self._get_throughput_constant(disk_type)
        return round(disk_size * const, 1)

    @staticmethod
    def _get_iops_constant(disk_type, flag):
        constant = 0.0
        if flag == "read":
            if disk_type == "pd-standard":
                constant = 0.75
            elif disk_type == "pd-balanced":
                constant = 6.0
            elif disk_type == "pd-ssd":
                constant = 30.0
        else:
            if disk_type == "pd-standard":
                constant = 1.5
            elif disk_type == "pd-balanced":
                constant = 6.0
            elif disk_type == "pd-ssd":
                constant = 30.0
        return constant

    @staticmethod
    def _get_throughput_constant(disk_type):
        constant = 0.0
        if disk_type == "pd-standard":
            constant = 0.12
        elif disk_type == "pd-balanced":
            constant = 0.28
        elif disk_type == "pd-ssd":
            constant = 0.48

        return constant

    @staticmethod
    def _get_matched_disk_tag_info(int_disk, disk_list):
        source_disk = None
        source = int_disk.get("source", "")
        disk = [
            disk_single
            for disk_single in disk_list
            if disk_single["selfLink"] == source
        ]
        if len(disk) > 0:
            source_disk = disk[0]
        return source_disk

    @staticmethod
    def _get_disk_type(matching_single_disk_tag):
        type_str = matching_single_disk_tag.get("type", "")
        type_split = type_str.split("/")
        return type_split[-1]

    @staticmethod
    def _get_bytes(number):
        return 1024 * 1024 * 1024 * number

    @staticmethod
    def _get_labels(instance):
        labels = []
        for k, v in instance.get("labels", {}).items():
            labels.append({"key": k, "value": v})
        return labels
