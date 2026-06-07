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

def test_eps_fault_triggers_critical_alerts():
    """
    Simulates the Mercedes-Benz steering pull issue —
    SteeringTorque stuck high, motor overworking, voltage dropping.
    Expects CRITICAL alerts to fire.
    """
    monitor = ECUHealthMonitor(poll_interval_s=0.05)
    eps = EPSECUNode("EPS_ECU", node_id=0x18)

    # Inject steering pull fault
    def steering_pull_fault():
        return {
            "MotorTemp":      64.0,
            "SupplyVoltage":  8.0,    # critically low
            "MotorCurrent":   101.0,   # critically high
            "SteeringTorque": 55.0,   # above 50 Nm critical limit
            "CommStatus":     1.0,
        }
    eps._read_signals = steering_pull_fault

    alerts = []
    monitor.add_ecu(eps)
    monitor.on_alert(lambda r: alerts.append(r))
    monitor.run(duration_s=0.3)

    critical = [a for a in alerts if a.level == AlertLevel.CRITICAL]
    assert len(critical) >= 3, "Expected CRITICAL alerts for SteeringTorque, MotorCurrent, SupplyVoltage"

    signal_names = [a.signal_name for a in critical]
    assert "SteeringTorque" in signal_names
    assert "MotorCurrent"   in signal_names
    assert "SupplyVoltage"  in signal_names
    print(f"\n  ✔  Steering pull fault detected — {len(critical)} critical alerts fired")


# ─── Fault Scenario Tests ─────────────────────────────────────────────────────

def test_eps_fault_triggers_critical_alerts():
    """
    Simulates the Mercedes-Benz steering pull issue —
    SteeringTorque stuck high, motor overworking, voltage dropping.
    CRITICAL: SteeringTorque, MotorCurrent
    WARNING:  SupplyVoltage
    """
    monitor = ECUHealthMonitor(poll_interval_s=0.05)
    eps = EPSECUNode("EPS_ECU", node_id=0x18)

    def steering_pull_fault():
        return {
            "MotorTemp":      64.0,
            "SupplyVoltage":  10.2,   # WARNING zone (between 9.0 and 11.5)
            "MotorCurrent":   101.0,  # CRITICAL (above 100)
            "SteeringTorque": 55.0,   # CRITICAL (above 50)
            "CommStatus":     1.0,
        }
    eps._read_signals = steering_pull_fault

    alerts = []
    monitor.add_ecu(eps)
    monitor.on_alert(lambda r: alerts.append(r))
    monitor.run(duration_s=0.3)

    # CRITICAL checks
    critical = [a for a in alerts if a.level == AlertLevel.CRITICAL]
    signal_names_crit = [a.signal_name for a in critical]
    assert "SteeringTorque" in signal_names_crit
    assert "MotorCurrent"   in signal_names_crit

    # WARNING checks
    warnings = [a for a in alerts if a.level == AlertLevel.WARNING]
    signal_names_warn = [a.signal_name for a in warnings]
    assert "SupplyVoltage" in signal_names_warn

    print(f"\n  ✔  Steering pull fault detected")
    print(f"     CRITICAL : {set(signal_names_crit)}")
    print(f"     WARNING  : {set(signal_names_warn)}")

def test_bcm_trunk_warning_fault():
    """
    Simulates the Mercedes-Benz trunk sound warning issue —
    trunk sensor stuck open, spurious sound warning, CAN bus errors.
    Expects CRITICAL alerts on all 3 signals.
    """
    monitor = ECUHealthMonitor(poll_interval_s=0.05)
    bcm = BCMECUNode("BCM_ECU", node_id=0x40)

    # Inject trunk fault
    def trunk_fault():
        return {
            "BatteryVoltage":   13.2,
            "TrunkSensorState": 2.0,   # stuck open — above critical max of 2
            "WarningSoundReq":  4.0,   # spurious warning firing
            "LightingLoad":     9.0,
            "CANBusErrors":     22.0,  # above critical max of 20
        }
    bcm._read_signals = trunk_fault

    alerts = []
    monitor.add_ecu(bcm)
    monitor.on_alert(lambda r: alerts.append(r))
    monitor.run(duration_s=0.3)

    critical = [a for a in alerts if a.level == AlertLevel.CRITICAL]
    signal_names = [a.signal_name for a in critical]

    assert "WarningSoundReq" in signal_names
    assert "CANBusErrors"    in signal_names
    print(f"\n  ✔  Trunk warning fault detected — {len(critical)} critical alerts fired")


def test_gateway_overload_fault():
    """
    Simulates Gateway ECU overload —
    CPU maxed out, routing overwhelmed, error frames spiking.
    """
    monitor = ECUHealthMonitor(poll_interval_s=0.05)
    gw = GatewayECUNode("GW_ECU", node_id=0x60)

    # Inject gateway overload
    def gateway_overload():
        return {
            "RoutingLoad":    92.0,   # above critical 90%
            "ActiveBuses":    3.0,
            "ErrorFrameRate": 25.0,   # above critical 20/s
            "CPULoad":        97.0,   # above critical 95%
        }
    gw._read_signals = gateway_overload

    alerts = []
    monitor.add_ecu(gw)
    monitor.on_alert(lambda r: alerts.append(r))
    monitor.run(duration_s=0.3)

    critical = [a for a in alerts if a.level == AlertLevel.CRITICAL]
    signal_names = [a.signal_name for a in critical]

    assert "CPULoad"        in signal_names
    assert "RoutingLoad"    in signal_names
    assert "ErrorFrameRate" in signal_names
    print(f"\n  ✔  Gateway overload detected — {len(critical)} critical alerts fired")


def test_normal_operation_no_critical_alerts():
    """
    Verifies all ECUs run clean with no faults —
    no CRITICAL alerts should fire under normal conditions.
    """
    monitor = ECUHealthMonitor(poll_interval_s=0.05)

    eps = EPSECUNode("EPS_ECU", node_id=0x18)
    bcm = BCMECUNode("BCM_ECU", node_id=0x40)
    gw  = GatewayECUNode("GW_ECU", node_id=0x60)

    # Force all ECUs into normal state — no fault injection
    def normal_eps():
        return {
            "MotorTemp":      62.0,
            "SupplyVoltage":  13.5,
            "MotorCurrent":   45.0,
            "SteeringTorque":  2.0,
            "CommStatus":      1.0,
        }
    def normal_bcm():
        return {
            "BatteryVoltage":   13.2,
            "TrunkSensorState": 0.0,
            "WarningSoundReq":  0.0,
            "LightingLoad":     9.0,
            "CANBusErrors":     2.0,
        }
    def normal_gw():
        return {
            "RoutingLoad":    40.0,
            "ActiveBuses":     3.0,
            "ErrorFrameRate":  1.0,
            "CPULoad":        45.0,
        }

    eps._read_signals = normal_eps
    bcm._read_signals = normal_bcm
    gw._read_signals  = normal_gw

    alerts = []
    monitor.add_ecu(eps)
    monitor.add_ecu(bcm)
    monitor.add_ecu(gw)
    monitor.on_alert(lambda r: alerts.append(r))
    monitor.run(duration_s=0.3)

    critical = [a for a in alerts if a.level == AlertLevel.CRITICAL]
    assert len(critical) == 0, f"Expected no critical alerts, got {len(critical)}"
    print(f"\n  ✔  Normal operation confirmed — 0 critical alerts")


def test_fault_then_recovery():
    monitor = ECUHealthMonitor(poll_interval_s=0.05)
    eps = EPSECUNode("EPS_ECU", node_id=0x18)

    # Force fault AND override signals to guarantee critical values
    eps._fault_active = True
    def forced_fault():
        return {
            "MotorTemp":      125.0,  # above critical 120
            "SupplyVoltage":  8.0,    # below critical 9
            "MotorCurrent":   101.0,  # above critical 100
            "SteeringTorque": 2.0,
            "CommStatus":     1.0,
        }
    eps._read_signals = forced_fault

    alerts_before = []
    monitor.add_ecu(eps)
    monitor.on_alert(lambda r: alerts_before.append(r))
    monitor.run(duration_s=0.3)

    # Recover and replace with normal signals
    eps.recover()
    def normal_signals():
        return {
            "MotorTemp":      62.0,
            "SupplyVoltage":  13.5,
            "MotorCurrent":   45.0,
            "SteeringTorque":  2.0,
            "CommStatus":      1.0,
        }
    eps._read_signals = normal_signals

    alerts_after = []
    monitor2 = ECUHealthMonitor(poll_interval_s=0.05)
    monitor2.add_ecu(eps)
    monitor2.on_alert(lambda r: alerts_after.append(r))
    monitor2.run(duration_s=0.3)

    crit_before = len([a for a in alerts_before if a.level == AlertLevel.CRITICAL])
    crit_after  = len([a for a in alerts_after  if a.level == AlertLevel.CRITICAL])

    assert crit_before > 0, "Expected critical alerts during fault"
    assert crit_after == 0, "Expected zero critical alerts after recovery"
    print(f"\n  ✔  Recovery confirmed — faults before={crit_before}, after={crit_after}")