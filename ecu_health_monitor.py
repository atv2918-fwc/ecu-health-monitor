"""
ECU Health Monitor
==================
Continuously polls a set of ECUs over simulated UDS/CAN, tracks live
signal health, detects anomalies, logs faults, and raises alerts.

Models the kind of End-of-Line (EOL) and plant-floor health monitoring
done at Mercedes-Benz production plants.

Author: Anurag Thaliyil Veedu
"""

import time
import random
import logging
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from collections import deque
from typing import Callable, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s  %(message)s",
    datefmt="%H:%M:%S"
)


# ─── Enums & Constants ────────────────────────────────────────────────────────

class ECUState(IntEnum):
    BOOT       = 0x00
    NORMAL     = 0x01
    DEGRADED   = 0x02
    FAULT      = 0x03
    SLEEP      = 0x04
    UNKNOWN    = 0xFF


class AlertLevel(IntEnum):
    INFO     = 0
    WARNING  = 1
    CRITICAL = 2


SEVERITY_EMOJI = {AlertLevel.INFO: "ℹ️ ", AlertLevel.WARNING: "⚠️ ", AlertLevel.CRITICAL: "🔴"}


# ─── Data Models ─────────────────────────────────────────────────────────────

@dataclass
class HealthSignal:
    name: str
    unit: str
    min_warn: float
    max_warn: float
    min_crit: float
    max_crit: float
    history: deque = field(default_factory=lambda: deque(maxlen=50))

    def record(self, value: float):
        self.history.append((time.monotonic(), value))

    def level(self, value: float) -> AlertLevel:
        if value < self.min_crit or value > self.max_crit:
            return AlertLevel.CRITICAL
        if value < self.min_warn or value > self.max_warn:
            return AlertLevel.WARNING
        return AlertLevel.INFO

    @property
    def last_value(self) -> Optional[float]:
        return self.history[-1][1] if self.history else None

    @property
    def trend(self) -> str:
        if len(self.history) < 3:
            return "─"
        vals = [v for _, v in list(self.history)[-5:]]
        delta = vals[-1] - vals[0]
        if delta > 0.5:  return "↑"
        if delta < -0.5: return "↓"
        return "─"


@dataclass
class FaultRecord:
    timestamp: float
    ecu_name: str
    signal_name: str
    value: float
    level: AlertLevel
    message: str

    def __str__(self):
        em = SEVERITY_EMOJI[self.level]
        return (f"{em} [{time.strftime('%H:%M:%S', time.localtime(self.timestamp))}] "
                f"{self.ecu_name} / {self.signal_name} = {self.value:.2f}  —  {self.message}")


# ─── Simulated ECU Node ───────────────────────────────────────────────────────

class ECUNode:
    """
    Represents a single ECU being monitored.
    Exposes health signals that can be polled via UDS ReadDataByID.
    """

    def __init__(self, name: str, node_id: int):
        self.name = name
        self.node_id = node_id
        self.log = logging.getLogger(name)
        self.state = ECUState.NORMAL
        self._fault_active = False
        self._fault_countdown = random.randint(20, 60)  # steps before injecting fault
        self._step = 0

        # Define monitored signals
        self.signals: dict[str, HealthSignal] = {}
        self._define_signals()

    def _define_signals(self):
        raise NotImplementedError

    def poll(self) -> dict[str, float]:
        """Simulate a UDS poll returning current signal values."""
        self._step += 1
        if self._step >= self._fault_countdown and not self._fault_active:
            self._fault_active = True
            self.state = ECUState.DEGRADED
            self.log.warning(f"Fault injected at step {self._step}")

        return self._read_signals()

    def _read_signals(self) -> dict[str, float]:
        raise NotImplementedError

    def recover(self):
        self._fault_active = False
        self.state = ECUState.NORMAL
        self._fault_countdown = self._step + random.randint(20, 60)


class EPSECUNode(ECUNode):
    """Electric Power Steering ECU"""

    def _define_signals(self):
        self.signals = {
            "MotorTemp":      HealthSignal("MotorTemp",      "°C",  -20, 100, -40, 120),
            "SupplyVoltage":  HealthSignal("SupplyVoltage",  "V",   11.5, 14.5, 9.0, 16.0),
            "MotorCurrent":   HealthSignal("MotorCurrent",   "A",   0, 80,  0, 100),
            "SteeringTorque": HealthSignal("SteeringTorque", "Nm",  -40, 40, -50, 50),
            "CommStatus":     HealthSignal("CommStatus",     "",    1, 1, 0, 1),  # 1=OK, 0=lost
        }

    def _read_signals(self) -> dict[str, float]:
        fault = self._fault_active
        return {
            "MotorTemp":      random.gauss(75 if fault else 60, 3),
            "SupplyVoltage":  random.gauss(10.8 if fault else 13.5, 0.2),
            "MotorCurrent":   random.gauss(85 if fault else 45, 5),
            "SteeringTorque": random.gauss(0, 5),
            "CommStatus":     0.0 if (fault and random.random() < 0.3) else 1.0,
        }


class BCMECUNode(ECUNode):
    """Body Control Module — Sound Warning & Lighting"""

    def _define_signals(self):
        self.signals = {
            "BatteryVoltage":   HealthSignal("BatteryVoltage",   "V",  11.5, 14.5, 9.0, 16.0),
            "TrunkSensorState": HealthSignal("TrunkSensorState", "",   0, 1, 0, 2),
            "WarningSoundReq":  HealthSignal("WarningSoundReq",  "",   0, 0, 0, 3),  # should be 0
            "LightingLoad":     HealthSignal("LightingLoad",     "A",  0, 15, 0, 20),
            "CANBusErrors":     HealthSignal("CANBusErrors",     "cnt",0, 5, 0, 20),
        }

    def _read_signals(self) -> dict[str, float]:
        fault = self._fault_active
        return {
            "BatteryVoltage":   random.gauss(13.2, 0.3),
            "TrunkSensorState": 1.0 if (fault and random.random() < 0.4) else 0.0,
            "WarningSoundReq":  random.randint(1, 3) if fault else 0,
            "LightingLoad":     random.gauss(9.0, 1.0),
            "CANBusErrors":     random.randint(8, 25) if fault else random.randint(0, 3),
        }


class GatewayECUNode(ECUNode):
    """Central Gateway / Network Management"""

    def _define_signals(self):
        self.signals = {
            "RoutingLoad":    HealthSignal("RoutingLoad",    "%",   0, 70, 0, 90),
            "ActiveBuses":    HealthSignal("ActiveBuses",    "cnt", 3, 3, 2, 4),
            "ErrorFrameRate": HealthSignal("ErrorFrameRate", "/s",  0, 5, 0, 20),
            "CPULoad":        HealthSignal("CPULoad",        "%",   0, 80, 0, 95),
        }

    def _read_signals(self) -> dict[str, float]:
        fault = self._fault_active
        return {
            "RoutingLoad":    random.gauss(75 if fault else 40, 5),
            "ActiveBuses":    2.0 if (fault and random.random() < 0.3) else 3.0,
            "ErrorFrameRate": random.gauss(15 if fault else 1, 2),
            "CPULoad":        random.gauss(88 if fault else 45, 5),
        }


# ─── Health Monitor ───────────────────────────────────────────────────────────

class ECUHealthMonitor:
    """
    Orchestrates polling of multiple ECU nodes, evaluates signal health,
    logs faults, and dispatches alert callbacks.
    """

    def __init__(self, poll_interval_s: float = 0.5):
        self.nodes: list[ECUNode] = []
        self.poll_interval = poll_interval_s
        self.fault_log: list[FaultRecord] = []
        self._alert_callbacks: list[Callable[[FaultRecord], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.log = logging.getLogger("HealthMonitor")

    def add_ecu(self, node: ECUNode):
        self.nodes.append(node)
        self.log.info(f"Registered ECU: {node.name} (ID=0x{node.node_id:02X})")

    def on_alert(self, callback: Callable[[FaultRecord], None]):
        self._alert_callbacks.append(callback)

    def _dispatch(self, record: FaultRecord):
        self.fault_log.append(record)
        for cb in self._alert_callbacks:
            cb(record)

    def _poll_once(self):
        for node in self.nodes:
            values = node.poll()
            for sig_name, value in values.items():
                sig = node.signals.get(sig_name)
                if not sig:
                    continue
                sig.record(value)
                level = sig.level(value)
                if level >= AlertLevel.WARNING:
                    record = FaultRecord(
                        timestamp=time.time(),
                        ecu_name=node.name,
                        signal_name=sig_name,
                        value=value,
                        level=level,
                        message=(
                            f"Value {value:.2f} {sig.unit} outside "
                            f"{'critical' if level==AlertLevel.CRITICAL else 'warning'} range "
                            f"({sig.min_warn}–{sig.max_warn} {sig.unit})"
                        )
                    )
                    self._dispatch(record)

    def run(self, duration_s: float = 10.0):
        """Run the monitor synchronously for a fixed duration."""
        self.log.info(f"Starting health monitor — {len(self.nodes)} ECUs — "
                      f"duration={duration_s}s  interval={self.poll_interval}s")
        end = time.monotonic() + duration_s
        while time.monotonic() < end:
            self._poll_once()
            time.sleep(self.poll_interval)
        self.log.info("Monitor run complete.")

    def start_background(self):
        """Start monitoring in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._background_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def _background_loop(self):
        while self._running:
            self._poll_once()
            time.sleep(self.poll_interval)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def snapshot(self) -> str:
        """Return a tabular snapshot of current signal states across all ECUs."""
        lines = ["", f"{'ECU':<18} {'Signal':<20} {'Value':>10}  {'Unit':<5}  {'Trend'}  Status"]
        lines.append("─" * 70)
        for node in self.nodes:
            for sig_name, sig in node.signals.items():
                val = sig.last_value
                if val is None:
                    continue
                level = sig.level(val)
                badge = {AlertLevel.INFO: "  OK  ", AlertLevel.WARNING: " WARN ", AlertLevel.CRITICAL: " CRIT "}[level]
                lines.append(
                    f"{node.name:<18} {sig_name:<20} {val:>10.2f}  {sig.unit:<5}  "
                    f"{sig.trend:<5}  [{badge}]"
                )
        lines.append("")
        return "\n".join(lines)

    def fault_summary(self) -> str:
        if not self.fault_log:
            return "No faults recorded."
        crit = [f for f in self.fault_log if f.level == AlertLevel.CRITICAL]
        warn = [f for f in self.fault_log if f.level == AlertLevel.WARNING]
        lines = [
            f"\nFault Summary: {len(self.fault_log)} events  "
            f"({len(crit)} critical / {len(warn)} warnings)\n"
        ]
        # Show last 10 unique faults
        seen = set()
        for record in reversed(self.fault_log):
            key = (record.ecu_name, record.signal_name, record.level)
            if key not in seen:
                lines.append(str(record))
                seen.add(key)
            if len(seen) >= 10:
                break
        return "\n".join(lines)


# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    monitor = ECUHealthMonitor(poll_interval_s=0.3)

    monitor.add_ecu(EPSECUNode("EPS_ECU",     node_id=0x18))
    monitor.add_ecu(BCMECUNode("BCM_ECU",     node_id=0x40))
    monitor.add_ecu(GatewayECUNode("GW_ECU",  node_id=0x60))

    # Register an alert callback
    def on_critical(record: FaultRecord):
        if record.level == AlertLevel.CRITICAL:
            print(f"\n{'!'*60}\n  CRITICAL ALERT: {record}\n{'!'*60}\n")

    monitor.on_alert(on_critical)

    print("Running ECU Health Monitor for 8 seconds...\n")
    monitor.run(duration_s=8.0)

    print(monitor.snapshot())
    print(monitor.fault_summary())
