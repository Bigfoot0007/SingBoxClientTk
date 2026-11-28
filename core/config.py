"""Configuration generator — produces sing-box config.json from nodes.

Targets sing-box 1.12+ / 1.14:
- geoip/geosite rule fields were REMOVED in 1.12.0 → use route.rule_set
- legacy DNS server format was REMOVED in 1.14.0 → use type/server fields
- route.default_domain_resolver is required (warns+FATAL otherwise on 1.14)
"""
import json
import os


class ConfigGenerator:
    """Generate sing-box compatible configuration."""

    # Routing modes
    ROUTING_GEO = "geo"         # geosite + geoip
    ROUTING_MANUAL = "manual"   # manual domain list
    ROUTING_ALL = "proxy_all"   # everything through proxy

    # Official rule-sets, downloaded & cached by sing-box at startup
    GEOIP_URL = ("https://raw.githubusercontent.com/"
                 "SagerNet/sing-geoip/rule-set/geoip-cn.srs")
    GEOSITE_URL = ("https://raw.githubusercontent.com/"
                   "SagerNet/sing-geosite/rule-set/geosite-cn.srs")

    def __init__(self):
        self.routing_mode = self.ROUTING_GEO
        self.manual_domains = []
        self.mixed_port = 7890
        # Directory of bundled .srs bootstrap copies (see bundled_bin).
        self.rule_set_dir = ""

    def generate(self, nodes: list, selected_id: str,
                 routing_mode: str = None,
                 stats_port: int = None, stats_secret: str = "",
                 rule_set_dir: str = None) -> dict:
        if routing_mode:
            self.routing_mode = routing_mode
        if rule_set_dir is not None:
            self.rule_set_dir = rule_set_dir
        config = {
            "log": {
                "disabled": False,
                "level": "info",
                "timestamp": True
            },
            "inbounds": [
                {
                    "type": "mixed",
                    "listen": "127.0.0.1",
                    "listen_port": self.mixed_port,
                    "tag": "mixed-in"
                }
            ],
            "outbounds": self._build_outbounds(nodes, selected_id),
            "dns": self._build_dns(),
            "route": self._build_route()
        }
        exp = {}
        if stats_port:
            # Clash API: app polls /traffic (1 line of {"up":..,"down":..}
            # JSON per second) for the live chart.
            exp["clash_api"] = {
                "external_controller": f"127.0.0.1:{stats_port}",
                "secret": stats_secret
            }
        if self.routing_mode == self.ROUTING_GEO:
            # Persist remote rule-sets in <data dir>/cache.db so a restart
            # doesn't refetch; pairs with initial_path bootstrap above.
            # (1.16 direction: cache replaces download_detour entirely.)
            exp["cache_file"] = {"enabled": True}
        if exp:
            config["experimental"] = exp
        return config

    def _build_outbounds(self, nodes: list, selected_id: str) -> list:
        outbounds = []
        if nodes and selected_id:
            for node in nodes:
                if node.get("id") == selected_id:
                    outbound = self._build_outbound(node)
                    outbound["tag"] = "proxy"
                    outbounds.append(outbound)
            outbounds.append({"type": "direct", "tag": "direct"})
        elif nodes:
            for node in nodes:
                node["tag"] = f"proxy_{node.get('id', 'unknown')}"
                outbounds.append(self._build_outbound(node))
            outbounds.append({"type": "direct", "tag": "direct"})
        return outbounds

    def _build_outbound(self, node: dict) -> dict:
        if node["type"] == "vless":
            outbound = {
                "type": "vless",
                "server": node.get("server", ""),
                "server_port": int(node.get("port", 443)),
                "uuid": node.get("uuid", ""),
                "packet_encoding": "xudp"
            }
            if node.get("flow"):
                outbound["flow"] = node["flow"]

            tls = {"enabled": True}
            if node.get("sni"):
                tls["server_name"] = node["sni"]
            if node.get("utls", True):
                tls["utls"] = {"enabled": True, "fingerprint": "chrome"}
            if node.get("reality"):
                tls["utls"] = {"enabled": True, "fingerprint": "chrome"}
                tls["reality"] = {
                    "enabled": True,
                    "public_key": node["reality"].get("public_key", ""),
                    "short_id": node["reality"].get("short_id", "")
                }
            outbound["tls"] = tls

            if node.get("transport") and node["transport"] != "tcp":
                transport = {"type": node["transport"]}
                if node.get("path"):
                    transport["path"] = node["path"]
                if node.get("host"):
                    transport["headers"] = {"Host": node["host"]}
                outbound["transport"] = transport

            return outbound

        elif node["type"] == "vmess":
            return {
                "type": "vmess",
                "server": node.get("server", ""),
                "server_port": int(node.get("port", 443)),
                "uuid": node.get("uuid", ""),
                "security": "auto",
                "tag": node.get("tag", "proxy"),
                "tls": {"enabled": True} if node.get("tls") else {}
            }

        elif node["type"] == "shadowsocks":
            return {
                "type": "shadowsocks",
                "server": node.get("server", ""),
                "server_port": int(node.get("port", 443)),
                "method": node.get("method", "aes-256-gcm"),
                "password": node.get("password", ""),
                "udp_over_tcp": node.get("udp_over_tcp", False),
                "tag": node.get("tag", "proxy")
            }

        elif node["type"] == "trojan":
            return {
                "type": "trojan",
                "server": node.get("server", ""),
                "server_port": int(node.get("port", 443)),
                "password": node.get("password", ""),
                "tls": {"enabled": True},
                "tag": node.get("tag", "proxy")
            }

        return {"type": "direct", "tag": "unknown"}

    # Internal hostname suffixes resolved by the system (local) resolver, so
    # LAN/internal names reach ip_is_private below instead of failing at 8.8.8.8.
    LAN_DOMAINS = ["local", "lan", "home", "internal", "corp", "arpa"]

    def _build_route(self) -> dict:
        rules = [
            {"protocol": "dns", "action": "hijack-dns"},
            # Pre-resolve LAN/internal names ONLY, so ip_is_private below can
            # still catch reserved addresses hidden behind hostnames (*.local,
            # *.lan, ...). The former GLOBAL {"action": "resolve"} is gone: the
            # resolve action uses route.default_domain_resolver (local system
            # DNS) — NOT the dns.rules split — and the browser never resolves
            # target hostnames itself when proxied (CONNECT carries the name).
            # So every new connection serially re-hit the router DNS: 3–17 s
            # stalls (observed), NXDOMAIN on valid foreign domains, and failed
            # lookups closed the connection outright. GEO needs no pre-resolve:
            # geosite-cn matches domain targets, and geoip-cn / ip_is_private
            # still match IP-literal targets untouched.
            {"domain_suffix": self.LAN_DOMAINS,
             "action": "resolve", "strategy": "prefer_ipv4"},
            # Reserved addresses never touch the proxy, in any routing mode:
            # ip_is_private is built into sing-box (no rule-set download) and
            # covers RFC1918, loopback, link-local, CGNAT, multicast, ::1 etc.
            {"ip_is_private": True, "outbound": "direct"},
        ]
        route = {
            "rules": rules,
            # Required since 1.12: resolve proxy-server hostnames explicitly
            "default_domain_resolver": "local"
        }

        if self.routing_mode == self.ROUTING_GEO:
            rule_sets = [
                {"tag": "geoip-cn", "type": "remote", "format": "binary",
                 "url": self.GEOIP_URL, "download_detour": "proxy"},
                {"tag": "geosite-cn", "type": "remote", "format": "binary",
                 "url": self.GEOSITE_URL, "download_detour": "proxy"},
            ]
            if self.rule_set_dir:
                # Cold-start bootstrap: load the shipped .srs when no
                # cached copy exists; remote updates still run normally.
                for rs in rule_sets:
                    rs["initial_path"] = os.path.join(
                        self.rule_set_dir, rs["tag"] + ".srs")
            route["rule_set"] = rule_sets
            rules.append({"rule_set": "geoip-cn", "outbound": "direct"})
            rules.append({"rule_set": "geosite-cn", "outbound": "direct"})
        elif self.routing_mode == self.ROUTING_MANUAL:
            if self.manual_domains:
                rules.append({"domain": self.manual_domains,
                              "outbound": "direct"})

        rules.append({"outbound": "proxy"})
        return route

    def _build_dns(self) -> dict:
        dns = {
            "servers": [
                # No detour: 1.14 rejects detouring to an empty direct outbound
                {"tag": "local", "type": "local"},
                {"tag": "remote", "type": "tls", "server": "8.8.8.8",
                 "detour": "proxy"}
            ],
            "rules": [
                {"domain": ["localhost"],
                 "domain_suffix": self.LAN_DOMAINS,
                 "server": "local"},
            ],
            "final": "remote"
        }
        if self.routing_mode == self.ROUTING_GEO:
            dns["rules"].append(
                {"rule_set": ["geoip-cn", "geosite-cn"], "server": "local"})
        return dns

    def save(self, config: dict, path: str):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
