from cloudforet.plugin.connector.compute_engine.vm_instance import VMInstanceConnector


class VPCHelper:
    def get_vpc_info(self, instance, vpcs, subnets):
        """
        vpc_data = {
            "vpc_id": "",
            "vpc_name": "",
            "description": "",
            "self_link": ""
        }

        subnet_data = {
            "subnet_id": "",
            "subnet_name": "",
            "self_link": "",
            "gateway_address": "",
            "vpc" : VPC
            "cidr": ""
        }
        """

        vpc_data = {}
        subnet_data = {}

        # To get vpc, subnet related to instance
        matched_subnet = self._get_matching_subnet(instance, subnets)
        matched_vpc = self._get_matching_vpc(matched_subnet, vpcs)

        vpc_data.update(
            {
                "vpcId": matched_vpc.get("id", ""),
                "vpcName": matched_vpc.get("name", ""),
                "description": matched_vpc.get("description", ""),
                "selfLink": matched_vpc.get("selfLink", ""),
            }
        )

        subnet_data.update(
            {
                "subnetId": matched_subnet.get("id", ""),
                "cidr": matched_subnet.get("ipCidrRange", ""),
                "subnetName": matched_subnet.get("name", ""),
                "gatewayAddress": matched_subnet.get("gatewayAddress", ""),
                "vpc": vpc_data,
                "selfLink": matched_subnet.get("selfLink", ""),
            }
        )

        return vpc_data, subnet_data

    @staticmethod
    def _get_matching_vpc(matched_subnet, vpcs) -> dict:
        matching_vpc = {}
        network = matched_subnet.get("selfLink", None)
        # Instance cannot be placed in multiple VPCs(Break after first matched result)
        if network is not None:
            for vpc in vpcs:
                if network in vpc.get("subnetworks", []):
                    matching_vpc = vpc
                    break

        return matching_vpc

    @staticmethod
    def _get_matching_subnet(instance, subnets) -> dict:
        subnet_data = {}
        subnetwork_links = []

        network_interfaces = instance.get("networkInterfaces", [])
        for network_interface in network_interfaces:
            """
            Subnet Type
            - auto subnet/custom subnet : reference selfLink is supported
            - legacy : reference selfLink is not supported
            """
            subnetwork = network_interface.get("subnetwork", "")
            if subnetwork != "":
                subnetwork_links.append(subnetwork)
        # Need to enhanced(multiple networkInterface in multiple subnets)
        for subnet in subnets:
            if subnet.get("selfLink", "") in subnetwork_links:
                subnet_data = subnet
                break

        return subnet_data
