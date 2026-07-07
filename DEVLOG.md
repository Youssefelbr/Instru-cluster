# Smart EV Dashboard — Development Log

**Project:** Smart Car Dashboard GUI in Python (PyQt5)
**Author:** Youssef EL BERRIRI
**Base code:** Sihab Sahariar
**Date:** 2026-07-01

---

## Overview

A PyQt5-based instrument cluster / HMI adapted for an Electric Vehicle.
Main file: `app.py` — run with `python app.py`.
Simulation file: `sim.py` — contains all custom widgets and the speed/power simulator.
Original gauge file: `gauge.py` — kept but no longer used (replaced by `FuturisticGauge`).

---

## Session Log

---

### 1. Initial Analysis

Analysed `app.py` (original Smart Car Dashboard GUI).

Key structure identified:
- `Ui_MainWindow` class with `setupUi()` builds the entire UI
- 4 tab frames: `frame_dashboard`, `frame_ac`, `frame_music`, `frame_map`
- `AnalogGaugeWidget` (from `gauge.py`) used for speed and RPM gauges
- `VideoThread(QThread)` handles webcam/video capture without blocking the UI
- `QWebEngineView` + `folium` for the live map tab
- IP geolocation (`ipapi.co` / `ip-api.com`) to center the map on startup

---

### 2. Created `sim.py` — Speed Simulator

Created `sim.py` with `SpeedSimulator(QObject)`:
- Drives speed + power gauges through a list of scenario segments
- Each segment: `(target_speed_kmh, target_power_kW, duration_ms)`
- Uses `QTimer` ticking every 50 ms (~20 fps)
- Linear interpolation between segment start/end values
- `loop=True` restarts automatically when the scenario finishes

**Default scenario** — a full city → highway → stop journey:

| Phase | Speed (km/h) | Power (kW) | Duration |
|-------|-------------|------------|----------|
| Idle | 0 | 0 | 1.5 s |
| Pull away | 20 | 35 | 2 s |
| City | 40 | 55 | 2 s |
| Open road | 70 | 90 | 3 s |
| Highway burst | 100 | 145 | 4 s |
| Cruise | 100 | 40 | 3 s |
| Coasting | 80 | 8 | 2 s |
| Back to cruise | 100 | 45 | 2 s |
| Exit | 70 | 10 | 2 s |
| Urban | 40 | 20 | 2 s |
| Braking | 20 | 5 | 1.5 s |
| Stop | 0 | 0 | 1.5 s |
| Wait | 0 | 0 | 1 s |

**Public API:**
```python
simulator.start()   # run from segment 0
simulator.stop()    # pause (gauges hold current value)
simulator.reset()   # stop + return gauges to zero
```

---

### 3. Max Speed Changed: 100 → 220 km/h

`app.py` — `progress()` method:
```python
# before
self.speed.set_MaxValue(100)

# after
self.speed.set_MaxValue(220)
```

---

### 4. EV Adaptation

#### 4a. Right gauge: RPM → Electric Motor Power (0–150 kW)

Replaced RPM gauge with a Power gauge.
Updated `progress()`:
```python
self.rpm.set_min(0)
self.rpm.set_max(150)
self.rpm.set_unit("kW")
self.rpm.set_divisions(6, 5)   # tick labels: 0, 25, 50, 75, 100, 125, 150
```

Simulator power values reflect real EV behaviour:
- High power (~145 kW) during hard acceleration
- Low power (~40 kW) while cruising at steady speed
- Near-zero power (~8 kW) when coasting/regenerating

#### 4b. Fuel bar → `BatteryIndicator` widget

Removed: `frame_4`, `progressBar_2`, `label_14` (fuel progress bar + label).

Added `BatteryIndicator(QWidget)` class in `sim.py`:
- Circular arc ring showing battery State-of-Charge (0–100 %)
- Drawn with `QPainter` / `drawArc`
- Color-coded automatically:
  - `> 50 %` → green `#00D26E`
  - `20–50 %` → orange
  - `< 20 %` → red
- Centered percentage value + "Battery" sub-label
- Placed at `(720, 300, 110, 110)` inside `frame_dashboard`

---

### 5. Removed Static Icon Widgets

Removed `frame_2` and the 4 icon labels it contained:
- `label_10` (steering wheel icon)
- `label_11` (seat icon)
- `label_12` (door icon)
- `label_13` (engine icon)

These were static decorations with no interactive purpose.

---

### 6. Dynamic Door Status + Futuristic HMI Style

#### Door status labels

Added `_DOOR_LABEL_MAP` dict mapping door names to label attributes:
```python
_DOOR_LABEL_MAP = {
    'hood':        'label_8',
    'front_left':  'label_4',
    'front_right': 'label_5',
    'rear_left':   'label_6',
    'rear_right':  'label_7',
    'trunk':       'label_9',
}
```

Added `set_door_status(door, is_open)` public method:
- Updates `_door_states` dict
- Calls `_animate_door_label()` → flashes label white twice then settles
  - Open → `#00FF99` green ("Opened")
  - Closed → `#FF3355` red ("Locked")
- Updates `frame_5` summary bar:
  - All closed → green border, "All Doors Locked"
  - Any open → red border, "N Door(s) Opened"

#### Tab fade animation

Added `_fade_in_frame(frame)`:
- Uses `QGraphicsOpacityEffect` + `QPropertyAnimation` on the `opacity` property
- 350 ms fade-in with `QEasingCurve.OutCubic`
- Called in `_switch_tab()` whenever a tab becomes visible

#### Futuristic dark stylesheet

Applied across all tab frames:
```
background: qlineargradient(… rgb(14,22,44) → rgb(10,14,30))
border-radius: 200px
border: 1px solid rgba(0, 180, 255, 35)
```

Nav buttons styled as HUD tabs:
- Default: dark navy, faint cyan border
- Hover: brighter cyan glow
- Active/Disabled: bottom border highlight (indicates current tab)

---

### 7. Replaced `AnalogGaugeWidget` with `FuturisticGauge`

Removed dependency on `gauge.py` (`AnalogGaugeWidget` no longer imported).

Added `FuturisticGauge(QWidget)` class in `sim.py` — full cyberpunk HUD gauge drawn in `paintEvent` with `QPainter`:

| Layer | Description |
|-------|-------------|
| Background | Radial gradient `rgb(20,25,55)` → `rgb(6,8,18)` + faint outer ring |
| Arc track | 270° sweep from 7:30 → 4:30 o'clock, split into 3 color zones |
| Arc zones | Cyan (0–60 %), Yellow (60–85 %), Red (85–100 %) — each with glow halo |
| Tick marks | Major + minor ticks with scale labels in `Nirmala UI` |
| Needle | Tapered polygon with 3 glow halos + solid cyan fill + white spine |
| Pivot | 4-layer glowing centre dot |
| Text | Large digital value (`Roboto Thin`) + unit label below |

**Arc geometry:**
- `_ARC_START = 225°` (7:30 o'clock, Qt CCW convention)
- `_ARC_SPAN  = 270°` clockwise sweep

**Public API:**
```python
gauge.set_value(v)            # move needle (clamped to min..max)
gauge.set_min(v)
gauge.set_max(v)
gauge.set_unit("km/h")
gauge.set_divisions(main, sub)
gauge.update_value(v)         # alias for set_value (backward compat)
gauge.valueChanged            # pyqtSignal(float)
```

Both speed and RPM gauge instances configured in `progress()`:
```python
self.speed.set_min(0);    self.speed.set_max(220)
self.speed.set_unit("km/h"); self.speed.set_divisions(11, 5)

self.rpm.set_min(0);      self.rpm.set_max(150)
self.rpm.set_unit("kW");  self.rpm.set_divisions(6, 5)
```

---

### 8. Needle Rotation Bug Fix

**Bug:** Needle pointed to 4:30 (arc end) at speed=0 and swept the wrong direction.

**Root cause:** Wrong rotation formula in `_draw_needle`:
```python
# broken — evaluates to rotate(ratio*270 - 225)
rotation = self._ARC_START - self._ratio() * self._ARC_SPAN
painter.rotate(-rotation)
```

At `ratio=0`: `painter.rotate(-225)` → CCW 225° → needle at 4:30 (arc end, not start).

**Fix:**
```python
# correct — CW 225° at min (7:30), CW 495° at max (4:30)
rotation = self._ARC_START + self._ratio() * self._ARC_SPAN
painter.rotate(rotation)
```

Verification:

| ratio | rotation | needle position |
|-------|----------|----------------|
| 0.0 | 225° CW | 7:30 (arc start) ✓ |
| 0.5 | 360° CW | 12 o'clock (midpoint) ✓ |
| 1.0 | 495°=135° CW | 4:30 (arc end) ✓ |

#### Needle redesign — tapered polygon

Replaced the single `drawLine` needle with a 5-point polygon:

```
       tip (0, -needle_len)
      / \
base_l   base_r        ← wider flanking points above pivot
     |   |
  tail_l  tail_r       ← narrow tail below pivot
```

Render layers:
1. 3 cyan glow halos (wide → narrow, alpha 18→46→88)
2. Solid filled polygon — cyan `rgba(0, 195, 255, 200)`
3. White spine line from base to tip

Added `QPolygonF` to `sim.py` imports.

---

### 9. ACC (Adaptive Cruise Control) Indicator

Added `ACCWidget(QWidget)` in `sim.py` — a compact cyberpunk HUD pill:

```
┌──────────────────────────────────┐
│  ● ACC  │  SET                   │
│         │  100 km/h              │
└──────────────────────────────────┘
```

**Left half:** LED voyant + "ACC" label
**Right half:** "SET" micro-label + setpoint speed + unit

**States:**

| State | LED | Label | Value |
|-------|-----|-------|-------|
| Active | Green glow (3 halos + core + specular highlight) | `#00FF7A` | Numeric (e.g. `100`) |
| Inactive | Dim dark circle | Grey | `———` |

**Public API:**
```python
acc.set_active(True / False)   # light up / dim
acc.set_setpoint(100)          # setpoint value to display
acc.set_unit("km/h")           # unit string
```

**Placement:** `(30, 314, 106, 41)` inside `frame_dashboard` — compact pill sitting to the left of the door-status frame, both aligned on the same horizontal row.

#### Simulator integration

Updated `DEFAULT_SCENARIO` — added optional 4th tuple element (ACC setpoint):
```python
(100, 40,  3000, 100),   # Phase 6: cruise → ACC engaged at 100 km/h
(100, 45,  2000, 100),   # Phase 8: back to cruise → ACC re-engaged
```

All other phases have no 4th element → ACC deactivated.

Updated `SpeedSimulator.__init__`:
```python
SpeedSimulator(speed_gauge, rpm_gauge, loop=True, acc_widget=self.acc_indicator)
```

`_tick()` updates the ACC widget only on segment transitions (not every tick) to avoid redundant repaints.

---

## File Change Summary

| File | Status | Key Changes |
|------|--------|-------------|
| `app.py` | Modified | Removed `AnalogGaugeWidget` import; replaced both gauge instances with `FuturisticGauge`; added `BatteryIndicator`, `ACCWidget`; removed fuel bar, 4 icons, door flap overlays; added door status API, tab fade animation, futuristic stylesheet |
| `sim.py` | Created | `SpeedSimulator`, `BatteryIndicator`, `FuturisticGauge`, `ACCWidget` |
| `gauge.py` | Unchanged | Original `AnalogGaugeWidget` — kept but no longer imported |
| `resources.py` | Unchanged | Compiled Qt resource file (all embedded images/icons) |

---

## Architecture Notes

### Thread safety rule
All gauge/widget updates must happen on the **main Qt thread**.
If driving gauges from an external algorithm in a separate process or thread, always cross the boundary with a `pyqtSignal`:

```python
class SpeedReceiver(QThread):
    speed_received = pyqtSignal(float)

    def run(self):
        while True:
            value = get_speed_from_algorithm()
            self.speed_received.emit(value)   # safe cross-thread call

# in main thread:
receiver.speed_received.connect(gauge.set_value)
```

### Connecting an external speed algorithm

Two supported patterns:

1. **Same process** — subclass `QThread`, emit `pyqtSignal(float)`, connect to `gauge.set_value`
2. **Separate process** — open a UDP socket in a `QThread`, receive datagrams, emit signal

---

## Known Issues / Notes

- `sizePolicy` variable is reused for `btn_start` / `btn_stop` in `setupUi` (pre-existing, harmless)
- Door flap overlays (visual door-open state on the car drawing) were prototyped but removed — the car image coordinate mapping was inaccurate at the widget's scaled size
- `Roboto Thin` font used for value readouts — install the font or Qt will fall back gracefully to a system default
