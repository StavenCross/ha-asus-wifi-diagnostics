"""Bounded LAN and DNS probes for separating router failures from WAN failures.

The Wi-Fi collector already proves that authenticated router diagnostics work, but that signal
cannot distinguish a healthy LAN from a broken local resolver or an upstream DNS outage. These
small, dependency-free probes run from the Home Assistant host so their viewpoint matches the
integrations that experienced the overnight failures.
"""

from __future__ import annotations

import asyncio
import secrets
import socket
import struct
from collections.abc import Awaitable
from time import monotonic

from .models import NetworkHealthProbe

DNS_TEST_NAME = "home-assistant.io"
DIRECT_DNS_SERVER = "1.1.1.1"
_PROBE_TIMEOUT_SECONDS = 3


async def collect_network_health(router_host: str) -> dict[str, NetworkHealthProbe]:
    """Collect independent LAN, router-DNS, and direct-DNS observations concurrently."""
    probes = await asyncio.gather(
        _timed_probe("lan_reachability", router_host, _probe_tcp(router_host, 22)),
        _timed_probe("router_dns", router_host, _probe_dns(router_host)),
        _timed_probe("direct_dns", DIRECT_DNS_SERVER, _probe_dns(DIRECT_DNS_SERVER)),
    )
    return {probe.key: probe for probe in probes}


async def _timed_probe(
    key: str,
    target: str,
    operation: Awaitable[None],
) -> NetworkHealthProbe:
    """Turn one bounded probe into stable recorder-friendly evidence."""
    started = monotonic()
    try:
        await asyncio.wait_for(operation, timeout=_PROBE_TIMEOUT_SECONDS)
    except (TimeoutError, OSError, ValueError) as err:
        return NetworkHealthProbe(
            key=key,
            target=target,
            healthy=False,
            latency_ms=round((monotonic() - started) * 1000),
            failure=err.__class__.__name__,
        )
    return NetworkHealthProbe(
        key=key,
        target=target,
        healthy=True,
        latency_ms=round((monotonic() - started) * 1000),
    )


async def _probe_tcp(host: str, port: int) -> None:
    """Prove that the router is reachable without opening an authenticated SSH session."""
    _, writer = await asyncio.open_connection(host, port)
    writer.close()
    await writer.wait_closed()


async def _probe_dns(server: str) -> None:
    """Resolve one stable public name through an explicitly selected DNS server."""
    transaction_id = secrets.randbits(16)
    query = _dns_query(transaction_id, DNS_TEST_NAME)
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    try:
        await loop.sock_sendto(sock, query, (server, 53))
        response, _ = await loop.sock_recvfrom(sock, 512)
    finally:
        sock.close()
    _validate_dns_response(response, transaction_id)


def _dns_query(transaction_id: int, name: str) -> bytes:
    """Build the minimal A-record query used by the health probe."""
    labels = name.rstrip(".").split(".")
    encoded_name = b"".join(bytes((len(label),)) + label.encode("ascii") for label in labels)
    header = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    return header + encoded_name + b"\x00" + struct.pack("!HH", 1, 1)


def _validate_dns_response(response: bytes, transaction_id: int) -> None:
    """Accept only a matching successful DNS answer with at least one record."""
    if len(response) < 12:
        raise ValueError("short DNS response")
    response_id, flags, _, answers, _, _ = struct.unpack("!HHHHHH", response[:12])
    if response_id != transaction_id or not flags & 0x8000:
        raise ValueError("mismatched DNS response")
    if flags & 0x000F or answers == 0:
        raise ValueError("DNS query returned no successful answer")
