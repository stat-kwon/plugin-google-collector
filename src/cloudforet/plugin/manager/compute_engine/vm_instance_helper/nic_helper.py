class NICHelper:
    def get_nic_info(self, instance, subnet_vo):
        """
        nic_data = {
            "device_index": 0,
            "device": "",
            "cidr": "",
            "ip_addresses": [],
            "mac_address": "",
            "public_ip_address": "",
            "tags": {
                "public_dns": "",
            }
        }
        """
        nics = []
        network_interfaces = instance.get("networkInterfaces", [])
        for idx, network in enumerate(network_interfaces):
            ip_addresses, public_ip = self._get_ip_addresses(network)
            nic_data = {
                "deviceIndex": idx,
                "ipAddresses": ip_addresses,
                "device": "",
                "nicType": "Virtual",
                "cidr": subnet_vo.get("cidr", ""),
                "publicIpAddress": public_ip,
                "tags": {},
            }

            nics.append(nic_data)

        return nics

    @staticmethod
    def _get_ip_addresses(network):
        ip_addresses = []
        public_ip_address = ""
        private_ip = network.get("networkIP", "")
        access_configs = network.get("accessConfigs", [])
        if private_ip != "":
            ip_addresses.append(private_ip)

        for idx, access_config in enumerate(access_configs):
            nat_ip = access_config.get("natIP", "")
            if nat_ip != "":
                # ip_addresses.append(nat_ip)
                if idx == 0:
                    public_ip_address = nat_ip

        return ip_addresses, public_ip_address
