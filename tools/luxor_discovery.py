#!/usr/bin/env python3
"""Check how a Luxor controller can be discovered on the network.

Usage:
    python -m pip install zeroconf
    python luxor_discovery.py 192.168.20.160 [controller-name]

Checks:
  1. Reverse DNS for the IP.
  2. mDNS hostname: does "<name>.local" answer a multicast A query? (A box can
     run an mDNS hostname responder without advertising any service.)
     The name defaults to what ControllerName.json reports.
  3. Every mDNS/DNS-SD service instance on the network, with addresses,
     flagging any that point at the controller or look Luxor/FX related.

Read-only. Takes ~20 seconds. Writes luxor_discovery.json next to this script.
"""

from __future__ import annotations

import json
import socket
import sys
import time
import urllib.request
from pathlib import Path

from zeroconf import DNSOutgoing, DNSQuestion, IPVersion, ServiceBrowser, Zeroconf, ZeroconfServiceTypes

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.20.160"
NAME = sys.argv[2] if len(sys.argv) > 2 else None
LISTEN = 10
KEYWORDS = ("lux", "fx", "lxtwo", "lxzdc")


def controller_name() -> str | None:
    req = urllib.request.Request(f"http://{IP}/ControllerName.json", data=b"{}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read()).get("Controller")
    except Exception as err:  # noqa: BLE001
        print("ControllerName failed:", err)
        return None


def resolve_mdns_host(zc: Zeroconf, host: str, timeout: float = 3.0) -> list:
    """Send a multicast A query for host and collect answers (works on old and new zeroconf)."""
    type_a, class_in, flags_query = 1, 1, 0x0000
    out = DNSOutgoing(flags_query, True)
    out.add_question(DNSQuestion(host, type_a, class_in))
    deadline = time.monotonic() + timeout
    next_send = 0.0
    while time.monotonic() < deadline:
        if time.monotonic() >= next_send:
            zc.send(out)
            next_send = time.monotonic() + 1.0
        time.sleep(0.2)
        addrs = sorted(
            {
                socket.inet_ntoa(r.address)
                for r in zc.cache.entries_with_name(host)
                if getattr(r, "type", None) == type_a and len(getattr(r, "address", b"")) == 4
            }
        )
        if addrs:
            return addrs
    return []


def main() -> None:
    out: dict = {"ip": IP}
    try:
        out["reverse_dns"] = socket.gethostbyaddr(IP)[0]
    except OSError as err:
        out["reverse_dns"] = f"lookup failed: {err}"
    print("Reverse DNS:", out["reverse_dns"])

    name = NAME or controller_name()
    out["controller_name"] = name
    zc = Zeroconf(ip_version=IPVersion.V4Only)

    if name:
        out["mdns_hostname"] = {}
        for host in (f"{name}.local.", f"{name.lower()}.local.", f"{name.upper()}.local."):
            if host in out["mdns_hostname"]:
                continue
            out["mdns_hostname"][host] = resolve_mdns_host(zc, host) or "no answer"
            print(f"mDNS hostname {host}", out["mdns_hostname"][host])

    print(f"Collecting mDNS service types for {LISTEN}s ...")
    types = sorted(ZeroconfServiceTypes.find(zc=zc, timeout=LISTEN))
    instances: list[dict] = []

    class Listener:
        def add_service(self, zc_, type_, name_):
            info = zc_.get_service_info(type_, name_, timeout=3000)
            instances.append(
                {
                    "type": type_,
                    "name": name_,
                    "server": info.server if info else None,
                    "addresses": info.parsed_addresses() if info else [],
                    "port": info.port if info else None,
                    "properties": {
                        k.decode(errors="replace"): (v or b"").decode(errors="replace")
                        for k, v in (info.properties.items() if info else [])
                    },
                }
            )

        update_service = add_service

        def remove_service(self, *args):
            pass

    browsers = [ServiceBrowser(zc, t, Listener()) for t in types]
    time.sleep(LISTEN)
    for b in browsers:
        b.cancel()
    zc.close()

    def interesting(i: dict) -> bool:
        blob = f"{i['name']} {i['server']}".lower()
        return IP in i["addresses"] or any(k in blob for k in KEYWORDS)

    out["matches"] = [i for i in instances if interesting(i)]
    out["unresolved"] = sorted({i["name"] for i in instances if not i["addresses"]})
    out["all_instances"] = instances
    print("Possible controller services:", out["matches"] or "none")
    print("Instances that never resolved:", out["unresolved"] or "none")

    path = Path(__file__).with_name("luxor_discovery.json")
    path.write_text(json.dumps(out, indent=2))
    print("Wrote", path)


if __name__ == "__main__":
    main()
