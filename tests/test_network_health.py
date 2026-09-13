"""Tests for bounded network-layer health evidence."""

import asyncio
import struct

import pytest

from custom_components.asus_wifi_diagnostics.network_health import (
    _dns_query,
    _timed_probe,
    _validate_dns_response,
)


def test_dns_query_and_matching_success_response() -> None:
    """The probe accepts a matching response only when it contains an answer."""
    transaction_id = 0x1234
    query = _dns_query(transaction_id, "home-assistant.io")
    assert query[:2] == b"\x12\x34"

    response = struct.pack("!HHHHHH", transaction_id, 0x8180, 1, 1, 0, 0)
    _validate_dns_response(response, transaction_id)


def test_dns_response_rejects_no_answer() -> None:
    """An answering resolver is unhealthy when it cannot resolve the test name."""
    response = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 0, 0, 0)
    with pytest.raises(ValueError, match="no successful answer"):
        _validate_dns_response(response, 0x1234)


def test_timed_probe_records_bounded_failure_class() -> None:
    """Probe errors become stable attributes instead of coordinator failures."""

    async def fail() -> None:
        raise OSError("offline")

    probe = asyncio.run(_timed_probe("router_dns", "192.168.50.1", fail()))

    assert probe.healthy is False
    assert probe.failure == "OSError"
    assert probe.latency_ms >= 0
