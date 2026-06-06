# ECU Health Monitor 🩺

A Python-based real-time health monitoring system for automotive ECUs, simulating the kind of **End-of-Line (EOL) and plant-floor diagnostic monitoring** used at Mercedes-Benz production facilities.

Continuously polls multiple ECUs, evaluates signal health against configurable thresholds, and raises tiered alerts (WARNING / CRITICAL) with fault logging and trend tracking.

## Features

- Multi-ECU polling with configurable interval (runs synchronously or as a background thread)
- Per-signal threshold bands: warning and critical levels
- Signal trend tracking (↑ ↓ ─) using rolling history
- Tiered alert system with pluggable callback hooks
- Live snapshot table showing all ECU signals and their status
- Fault summary report with deduplication
- Three pre-built ECU models: EPS (steering), BCM (body control), Gateway
- Fault injection simulation for testing and demo

## Project Structure

```
ecu-health-monitor/
├── ecu_health_monitor.py    # Core monitor, ECU nodes, signal definitions
├── tests/
│   └── test_monitor.py      # Unit tests
└── README.md
```

## Quick Start

```bash
python ecu_health_monitor.py
```

## Sample Output

```
ECU                Signal               Value  Unit   Trend  Status
──────────────────────────────────────────────────────────────────────
EPS_ECU            MotorTemp            102.40  °C     ↑     [ CRIT ]
EPS_ECU            SupplyVoltage         10.75  V      ↓     [ CRIT ]
EPS_ECU            MotorCurrent          88.10  A      ↑     [ CRIT ]
BCM_ECU            WarningSoundReq        2.00         ─     [ CRIT ]
BCM_ECU            CANBusErrors           3.00  cnt    ─     [  OK  ]
GW_ECU             CPULoad               46.20  %      ─     [  OK  ]

Fault Summary: 42 events  (28 critical / 14 warnings)

🔴 [10:42:15] EPS_ECU / MotorTemp = 102.40 — Value outside critical range (−20–100 °C)
⚠️  [10:42:08] BCM_ECU / TrunkSensorState = 1.00 — Value outside warning range
```

## Extending with New ECUs

Subclass `ECUNode` and implement `_define_signals()` and `_read_signals()`:

```python
class DisplayECUNode(ECUNode):
    def _define_signals(self):
        self.signals = {
            "Brightness":  HealthSignal("Brightness",  "nit", 50, 800, 0, 1000),
            "FrameErrors": HealthSignal("FrameErrors", "cnt",  0,   5, 0,   50),
        }
    def _read_signals(self):
        return {
            "Brightness":  random.gauss(500, 30),
            "FrameErrors": random.randint(0, 2),
        }
```

## Background

Modelled on ECU health monitoring work at **Mercedes-Benz R&D India**, where I conducted End-of-Line testing, managed on-site plant validations at Mercedes-Benz Germany, and resolved safety-critical issues (steering pull, trunk warning) through diagnostic monitoring and root cause analysis.
