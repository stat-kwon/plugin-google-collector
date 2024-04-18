import logging
import ipaddress
from urllib.parse import urlparse

from spaceone.inventory.plugin.collector.lib import *

from cloudforet.plugin.config.global_conf import ASSET_URL
from cloudforet.plugin.connector.networking.load_balancing import LoadBalancingConnector
from cloudforet.plugin.manager import ResourceManager

_LOGGER = logging.getLogger("spaceone")


class LoadBalancingManager(ResourceManager):
    service = "Networking"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.cloud_service_group = "Networking"
        self.cloud_service_type = "LoadBalancing"
        self.metadata_path = "plugin/metadata/networking/load_balancing.yaml"

    def create_cloud_service_type(self):
        return make_cloud_service_type(
            name=self.cloud_service_type,
            group=self.cloud_service_group,
            provider=self.provider,
            metadata_path=self.metadata_path,
            is_primary=True,
            is_major=True,
            service_code="Networking",
            tags={
                "spaceone:icon": f"{ASSET_URL}/Load_Balancing.svg",
                "spaceone:display_name": "LoadBalancing",
            },
            labels=["Networking"],
        )

    def create_cloud_service(self, options, secret_data, schema):
        project_id = secret_data["project_id"]
        lb_id = ""
        loadbalancing_conn = LoadBalancingConnector(
            options=options, secret_data=secret_data, schema=schema
        )

        # Getting all components for loadbalancing
        forwarding_rules = loadbalancing_conn.list_forwarding_rules()

        # Extend all types of proxies
        load_balancers = []
        all_proxies = []
        grpc_proxies = loadbalancing_conn.list_grpc_proxies()
        load_balancers.extend(grpc_proxies)
        all_proxies.extend(grpc_proxies)

        http_proxies = loadbalancing_conn.list_target_http_proxies()
        load_balancers.extend(http_proxies)
        all_proxies.extend(http_proxies)

        https_proxies = loadbalancing_conn.list_target_https_proxies()
        load_balancers.extend(https_proxies)
        all_proxies.extend(https_proxies)

        ssl_proxies = loadbalancing_conn.list_ssl_proxies()
        load_balancers.extend(ssl_proxies)
        all_proxies.extend(ssl_proxies)

        tcp_proxies = loadbalancing_conn.list_tcp_proxies()
        load_balancers.extend(tcp_proxies)
        all_proxies.extend(tcp_proxies)

        # SSL Cert for proxy
        ssl_certificates = loadbalancing_conn.list_ssl_certificates()

        url_maps = loadbalancing_conn.list_url_maps()
        backend_services = loadbalancing_conn.list_backend_services()
        backend_buckets = loadbalancing_conn.list_backend_buckets()

        # Health Checks
        legacy_health_checks = []
        health_checks = loadbalancing_conn.list_health_checks()

        http_health_checks = loadbalancing_conn.list_http_health_checks()
        legacy_health_checks.extend(http_health_checks)

        https_health_checks = loadbalancing_conn.list_https_health_checks()
        legacy_health_checks.extend(https_health_checks)

        target_pools = loadbalancing_conn.list_target_pools()

        # Extract loadbalancer information from related resources(Target Proxy, Forwarding Rule)
        # Google Cloud Service Does not provider single object of loadbalancer
        target_pool_based_load_balancers = self._get_loadbalancer_from_forwarding_rule(
            forwarding_rules
        )
        load_balancers.extend(target_pool_based_load_balancers)

        cloud_services = []
        error_responses = []
        for load_balancer in load_balancers:
            try:
                lb_forwarding_rules = self._get_forwarding_rules(
                    load_balancer, forwarding_rules
                )
                lb_target_proxy = self._get_target_proxy(load_balancer)
                lb_certificates = self._get_certificates(
                    lb_target_proxy, ssl_certificates
                )
                lb_urlmap = self._get_urlmap(load_balancer, url_maps)
                lb_backend_services = self._get_backend_services(
                    lb_urlmap, backend_services
                )
                lb_health_checks = self._get_health_checks(
                    lb_backend_services, health_checks
                )
                lb_legacy_health_checks = self._get_legacy_health_checks(
                    lb_backend_services, legacy_health_checks
                )
                lb_bucket_services = self._get_bucket_services(
                    lb_urlmap, backend_buckets
                )
                lb_target_pools = self._get_target_pools(
                    lb_forwarding_rules, target_pools
                )

                loadbalancer_data = {
                    "id": load_balancer.get("id", ""),
                    "name": self._get_name(load_balancer),
                    "description": load_balancer.get("description", ""),
                    "project": self._get_project_name(load_balancer),
                    "region": self.get_region(load_balancer),
                    "internalOrExternal": self._get_external_internal(
                        lb_forwarding_rules
                    ),
                    "type": self._get_loadbalancer_type(load_balancer),
                    "protocol": self._get_loadbalancer_protocol(load_balancer),
                    "selfLink": load_balancer.get("selfLink", ""),
                    "forwardingRules": lb_forwarding_rules,
                    "targetProxy": lb_target_proxy,
                    "urlmap": lb_urlmap,
                    "certificates": lb_certificates,
                    "backendServices": lb_backend_services,
                    "backendBuckets": lb_bucket_services,
                    "heathChecks": lb_health_checks,
                    "legacyHealthChecks": lb_legacy_health_checks,
                    "targetPools": lb_target_pools,
                    "tags": [],
                    "creationTimestamp": load_balancer.get("creationTimestamp"),
                }

                self.set_region_code(loadbalancer_data.get("region", ""))
                print(load_balancer)
                cloud_services.append(
                    make_cloud_service(
                        name=loadbalancer_data.get("name", ""),
                        cloud_service_type=self.cloud_service_type,
                        cloud_service_group=self.cloud_service_group,
                        provider=self.provider,
                        account=project_id,
                        data=loadbalancer_data,
                        region_code=loadbalancer_data.get("region", ""),
                        reference={
                            "resource_id": load_balancer.get("selfLink", ""),
                            "external_link": load_balancer.get("selfLink", ""),
                        },
                    )
                )

            except Exception as e:
                _LOGGER.error(f"Error on LoadBalancer {lb_id}: {e}")

                error_responses.append(
                    make_error_response(
                        error=e,
                        provider=self.provider,
                        cloud_service_group=self.cloud_service_group,
                        cloud_service_type=self.cloud_service_type,
                    )
                )
        return cloud_services, error_responses

    def _get_loadbalancer_from_forwarding_rule(self, forwarding_rules) -> list:
        loadbalancers = []
        for fr in forwarding_rules:
            if self._check_forwarding_rule_is_loadbalancer(fr):
                loadbalancers.append(fr)

        return loadbalancers

    def _check_forwarding_rule_is_loadbalancer(self, forwarding_rule) -> bool:
        target = forwarding_rule.get("target", "")
        if self.get_param_in_url(target, "targetPools") != "":
            return True
        else:
            return False

    # Get loadbalancer name from related services
    def _get_name(self, loadbalancer) -> str:
        # Loadbalancer name can be extracted by resource type
        # Google cloud does not support one single loadbalancer
        if loadbalancer.get("kind") == "compute#targetHttpProxy":
            return self.get_param_in_url(loadbalancer.get("urlMap", ""), "urlMaps")
        elif loadbalancer.get("kind") == "compute#targetHttpsProxy":
            return self.get_param_in_url(loadbalancer.get("urlMap", ""), "urlMaps")
        elif loadbalancer.get("kind") == "compute#targetSslProxy":
            return self.get_param_in_url(
                loadbalancer.get("service", ""), "backendServices"
            )
        elif loadbalancer.get("kind") == "compute#targetTcpProxy":
            return self.get_param_in_url(
                loadbalancer.get("service", ""), "backendServices"
            )
        elif loadbalancer.get("kind") == "compute#forwardingRule":
            return self.get_param_in_url(loadbalancer.get("target", ""), "targetPools")
        else:
            return ""

    def _get_project_name(self, loadbalancer) -> str:
        url_self_link = loadbalancer.get("selfLink", "")
        project_name = self.get_param_in_url(url_self_link, "projects")
        return project_name

    def _get_target_proxy(self, load_balancer) -> dict:
        """
        Loadbalancer type is two case
        1. proxy type(grpc, http, https, tcp, udp)
        2. forwarding rule(target pool based)
        Remove forwarding rule case
        """
        if load_balancer.get("kind", "") == "compute#forwardingRule":
            target_proxy = {}
        else:
            target_proxy = {
                "name": load_balancer.get("name", ""),
                "description": load_balancer.get("description", ""),
            }
            target_proxy.update(
                self._get_target_proxy_type(
                    load_balancer.get("kind", ""), load_balancer
                )
            )

        return target_proxy

    @staticmethod
    def _get_target_proxy_type(kind, target_proxy) -> dict:
        # Proxy service is managed by type(protocol)
        if kind == "compute#targetGRPCProxy":
            proxy_type = {"type": "GRPC", "grpcProxy": target_proxy}
        elif kind == "compute#targetHttpProxy":
            proxy_type = {"type": "HTTP", "httpProxy": target_proxy}
        elif kind == "compute#targetHttpsProxy":
            proxy_type = {"type": "HTTPS", "httpsProxy": target_proxy}
        elif kind == "compute#targetSslProxy":
            proxy_type = {"type": "SSL", "sslProxy": target_proxy}
        elif kind == "compute#targetTcpProxy":
            proxy_type = {"type": "TCP", "tcpProxy": target_proxy}
        else:
            proxy_type = {}
        return proxy_type

    @staticmethod
    def _get_certificates(lb_target_proxy, ssl_certificates) -> list:
        """
        Get related certificated to target proxy(LoadBalancer)
        """
        matched_certificates = []
        for cert in ssl_certificates:
            if cert.get("selfLink", "") in lb_target_proxy.get("sslCertificates", []):
                matched_certificates.append(cert)
        return matched_certificates

    @staticmethod
    def _get_urlmap(load_balancer, url_maps):
        """
        Get relatred urlmaps to loadbalancer
        """
        matched_urlmap = {}
        for map in url_maps:
            if map.get("selfLink") == load_balancer.get("urlMap", ""):
                matched_urlmap = map

        return matched_urlmap

    @staticmethod
    def _get_backend_services(lb_urlmap, backend_services):
        """
        Get related backend services from urlmap
        """
        matched_backend_services = []
        for svc in backend_services:
            if lb_urlmap.get("defaultService", "") == svc.get("selfLink"):
                matched_backend_services.append(svc)

        return matched_backend_services

    @staticmethod
    def _get_health_checks(lb_backend_services, health_checks):
        """
        Get related health checks from backend_services
        """
        matched_health_checks = []
        for svc in lb_backend_services:
            for check in health_checks:
                if check.get("selfLink") in svc.get("healthChecks", []):
                    matched_health_checks.append(check)

        return matched_health_checks

    @staticmethod
    def _get_legacy_health_checks(lb_backend_services, legacy_health_checks):
        """
        Get related legacy health checks from backend_services
        """
        matched_legacy_health_checks = []
        for svc in lb_backend_services:
            for check in legacy_health_checks:
                if check.get("selfLink") in svc.get("healthChecks", []):
                    matched_legacy_health_checks.append(check)

        return matched_legacy_health_checks

    @staticmethod
    def _get_bucket_services(lb_urlmap, backend_buckets):
        """
        Get related bucket backend from urlmaps
        """
        matched_bucket_service = []
        for backend in backend_buckets:
            if backend.get("selfLink") in lb_urlmap.get("defaultService", ""):
                matched_bucket_service.append(backend)

        return matched_bucket_service

    @staticmethod
    def _get_target_pools(lb_forwarding_rules, target_pools):
        """
        Get related target pool from forwarding rules
        """
        matched_target_pools = []
        for rule in lb_forwarding_rules:
            for pool in target_pools:
                if rule.get("target", "") == pool.get("selfLink"):
                    matched_target_pools.append(pool)

        return matched_target_pools

    @staticmethod
    def _get_forwarding_rules(loadbalancer, forwarding_rules):
        matched_forwarding_rules = []
        """
        1. LoadBalancer is target of forwarding rule
        2. LoadBalancer is same as forwarding rules(Target Pool Based)
        """
        for rule in forwarding_rules:
            if loadbalancer.get("selfLink") == rule.get("target", ""):
                matched_forwarding_rules.append(rule)
            if loadbalancer.get("selfLink") == rule.get("selfLink", ""):
                matched_forwarding_rules.append(rule)

        return matched_forwarding_rules

    @staticmethod
    def _get_external_internal(forwarding_rules) -> str:
        external_or_internal = "UnKnown"
        if len(forwarding_rules) > 0:
            external_or_internal = forwarding_rules[0].get("loadBalancingScheme")

        return external_or_internal

    @staticmethod
    def _get_loadbalancer_type(load_balancer):
        """
        - load_balancer kind is six type
            compute#forwardingRule
            compute#targetHttpProxy
            compute#targetHttpsProxy
            compute#targetSslProxy
            compute#targetTcpProxy
            compute#targetGrpcProxy
        """
        lb_type = "UnKnown"
        if load_balancer.get("kind") == "compute#forwardingRule":
            # kind: compute#forwardingRule loadbalancer pass traffic to backend service directly.
            lb_type = "TCP/UDP Network LoadBalancer"
        elif load_balancer.get("kind") in [
            "compute#targetHttpsProxy",
            "compute#targetHttpProxy",
            "compute#targetGrpcProxy",
        ]:
            lb_type = "HTTP(S) LoadBalancer"
        elif load_balancer.get("kind") in ["compute#targetTcpProxy"]:
            lb_type = "TCP Proxy LoadBalancer"
        elif load_balancer.get("kind") in ["compute#targetSslProxy"]:
            lb_type = "SSL Proxy LoadBalancer"

        return lb_type

    @staticmethod
    def _get_loadbalancer_protocol(load_balancer):
        lb_protocol = "UnKnown"

        if load_balancer.get("kind") == "compute#forwardingRule":
            # IPProtocol can be TCP, UDP, ESP, AH, SCTP, ICMP and L3_DEFAULT
            lb_protocol = load_balancer.get("IPProtocol", "")
        elif load_balancer.get("kind") in [
            "compute#targetHttpProxy",
            "compute#targetGrpcProxy",
        ]:
            lb_protocol = "HTTP"
        elif load_balancer.get("kind") in ["compute#targetHttpsProxy"]:
            lb_protocol = "HTTPS"
        elif load_balancer.get("kind") in ["compute#targetTcpProxy"]:
            lb_protocol = "TCP"
        elif load_balancer.get("kind") in ["compute#targetSslProxy"]:
            lb_protocol = "SSL"

        return lb_protocol

    @staticmethod
    def get_param_in_url(url, key):
        param = ""
        raw_path = urlparse(url).path
        list_path = raw_path.split("/")
        # Google cloud resource representation rules is /{key}/{value}/{key}/{value}
        if key in list_path:
            index_key = list_path.index(key)
            index_value = index_key + 1
            param = list_path[index_value]
        return param

    def get_region(self, resource_info):
        if "region" in resource_info:
            return self.get_param_in_url(resource_info.get("region", ""), "regions")
        else:
            return "global"
