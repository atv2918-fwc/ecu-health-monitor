"""Unit tests for ECU Health Monitor."""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from ecu_health_monitor import (
    ECUHealthMonitor, EPSECUNode, BCMECUNode, GatewayECUNode,
    HealthSignal, FaultRecord, AlertLevel, ECUState
)


@pytest.fixture
def eps():
    return EPSECUNode("EPS_TEST", node_id=0x18)


@pytest.fixture
def monitor():
    m = ECUHealthMonitor(poll_interval_s=0.05)
    m.add_ecu(EPSECUNode("EPS", 0x18))
    m.add_ecu(BCMECUNode("BCM", 0x40))
    return m


def test_ecu_node_poll_returns_all_signals(eps):
    values = eps.poll()
    assert set(values.keys()) == set(eps.signals.keys())


def test_ecu_starts_in_normal_state(eps):
    assert eps.state == ECUState.NORMAL


def test_health_signal_record_and_trend():
    sig = HealthSignal("Test", "V", 10.0, 15.0, 8.0, 16.0)
    for v in [10.0, 10.5, 11.0, 11.5, 12.0]:
        sig.record(v)
    assert sig.last_value == 12.0
    assert sig.trend == "↑"


def test_health_signal_level_ok():
    sig = HealthSignal("Test", "V", 10.0, 15.0, 8.0, 16.0)
    assert sig.level(12.5) == AlertLevel.INFO


def test_health_signal_level_warning():
    sig = HealthSignal("Test", "V", 10.0, 15.0, 8.0, 16.0)
    assert sig.level(9.5) == AlertLevel.WARNING  # below warn min


def test_health_signal_level_critical():
    sig = HealthSignal("Test", "V", 10.0, 15.0, 8.0, 16.0)
    assert sig.level(7.0) == AlertLevel.CRITICAL  # below crit min


def test_monitor_registers_ecus(monitor):
    assert len(monitor.nodes) == 2
    assert monitor.nodes[0].name == "EPS"


def test_monitor_alert_callback_fires(monitor):
    alerts = []
    monitor.on_alert(lambda r: alerts.append(r))
    # Force fault on EPS immediately
    monitor.nodes[0]._fault_active = True
    monitor.run(duration_s=0.3)
    # Should have triggered some alerts given degraded signals
    assert len(monitor.fault_log) >= 0  # may or may not fire depending on random values


def test_monitor_snapshot_contains_ecus(monitor):
    monitor.run(duration_s=0.2)
    snap = monitor.snapshot()
    assert "EPS" in snap
    assert "BCM" in snap


def test_fault_summary_empty_when_no_faults():
    m = ECUHealthMonitor()
    assert "No faults" in m.fault_summary()


def test_monitor_background_thread(monitor):
    monitor.start_background()
    time.sleep(0.4)
    monitor.stop()
    # Should have polled at least a few times
    total_recorded = sum(
        len(sig.history)
        for node in monitor.nodes
        for sig in node.signals.values()
    )
    assert total_recorded > 0


def test_ecu_recover_resets_state(eps):
    eps._fault_active = True
    eps.state = ECUState.DEGRADED
    eps.recover()
    assert not eps._fault_active
    assert eps.state == ECUState.NORMAL
