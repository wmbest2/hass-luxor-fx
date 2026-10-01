#!/usr/bin/env python3
"""Check how a Luxor controller can be discovered on the network.

Usage:
    python -m pip install zeroconf
    python luxor_discovery.py 192.168.20.160

Reports the controller's reverse-DNS hostname (what DHCP discovery matches on)
and every mDNS/Bonjour service advertised from that IP. Read-only; listens for
about 10 seconds. Writes luxor_discovery.json next to this script.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.20.160"
LISTEN = 10


def main() -> None:
    out: dict = {"ip": IP}
    try:
        out["reverse_dns"] = socket.gethostbyaddr(IP)[0]
    except OSError as err:
        out["reverse_dns"] = f"lookup failed: {err}"
    print("Reverse DNS:", out["reverse_dns"])

    try:
        from zeroconf import ServiceBrowser, Zeroconf, ZeroconfServiceTypes
    except ImportError:
        print("zeroconf not installed; run: python -m pip install zeroconf")
        out["mdns"] = "zeroconf package not installed"
    else:
        print(f"Collecting mDNS service types for {LISTEN}s ...")
        types = sorted(ZeroconfServiceTypes.find(timeout=LISTEN))
        out["all_service_types_on_network"] = types
        zc = Zeroconf()
        found: list[dict] = []

        class Listener:
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name, timeout=3000)
                if info and IP in info.parsed_addresses():
                    found.append(
                        {
                            "type": type_,
                            "name": name,
                            "server": info.server,
                            "port": info.port,
                            "properties": {
                                k.decode(errors="replace"): (v or b"").decode(errors="replace")
                                for k, v in info.properties.items()
                            },
                        }
                    )

            update_service = add_service

            def remove_service(self, *a):
                pass

        browsers = [ServiceBrowser(zc, t, Listener()) for t in types]
        time.sleep(LISTEN)
        for b in browsers:
            b.cancel()
        zc.close()
        out["services_from_controller"] = found
        print("Services advertised by the controller:", found or "none")

    path = Path(__file__).with_name("luxor_discovery.json")
    path.write_text(json.dumps(out, indent=2))
    print("Wrote", path)


if __name__ == "__main__":
    main()
