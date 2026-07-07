import math
import time

from PyQt5.QtCore import QObject, QTimer, Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QPainter, QPen, QFont, QColor, QBrush,
                          QRadialGradient, QFontMetrics, QPolygonF)
from PyQt5.QtWidgets import QWidget


class SpeedSimulator(QObject):
    """
    Animates the speed and RPM gauges through a sequence of scenario segments.

    Each segment defines a target state and how long to take getting there:
        (target_speed_kmh, target_rpm, duration_ms)

    The simulator linearly interpolates from the previous segment's end values
    to the target values over the given duration, ticking every `tick_ms` ms.

    Gauge ranges expected by this simulator:
        speed : 0 – 220  km/h   (set in app.py progress())
        power : 0 – 150  kW     (set in app.py progress())
    """

    # ------------------------------------------------------------------
    # Default scenario  –  a typical city → highway → stop journey
    # (target_speed km/h,  target_power kW,  duration_ms)
    #
    # Power behaviour for an EV:
    #   - High power during acceleration bursts
    #   - Low power (~30–50 kW) while cruising at steady speed
    #   - Near-zero power when coasting / decelerating
    # ------------------------------------------------------------------
    DEFAULT_SCENARIO = [
        # Phase 1 – motor idle / standstill
        (0,    0,   1500),

        # Phase 2 – pulling away from standstill
        (20,   35,  2000),

        # Phase 3 – city acceleration
        (40,   55,  2000),

        # Phase 4 – leaving city, picking up speed
        (70,   90,  3000),

        # Phase 5 – highway on-ramp, full power burst
        (100,  145, 4000),

        # Phase 6 – cruising at 100 km/h  →  ACC engaged at 100 km/h
        (100,  40,  3000, 100),

        # Phase 7 – slight slowdown, coasting  →  driver overrides, ACC off
        (80,   8,   2000),

        # Phase 8 – back to cruise  →  ACC re-engaged at 100 km/h
        (100,  45,  2000, 100),

        # Phase 9 – approaching exit, coasting
        (70,   10,  2000),

        # Phase 10 – urban slowdown
        (40,   20,  2000),

        # Phase 11 – approaching junction, braking
        (20,   5,   1500),

        # Phase 12 – full stop
        (0,    0,   1500),

        # Phase 13 – wait at junction
        (0,    0,   1000),
    ]

    def __init__(self, speed_gauge, rpm_gauge, scenario=None, tick_ms=50, loop=False,
                 acc_widget=None):
        """
        Args:
            speed_gauge : FuturisticGauge for speed display
            rpm_gauge   : FuturisticGauge for power display
            scenario    : list of (target_speed, target_power, duration_ms[, acc_setpoint])
                          tuples.  Pass None to use DEFAULT_SCENARIO.
                          When acc_setpoint is present and not None, the ACC widget is
                          activated with that value; when absent or None it is deactivated.
            tick_ms     : timer interval in milliseconds (default 50 → ~20 fps)
            loop        : if True the scenario restarts automatically when finished
            acc_widget  : optional ACCWidget instance to update automatically
        """
        super().__init__()

        self.speed_gauge  = speed_gauge
        self.rpm_gauge    = rpm_gauge
        self.scenario     = scenario if scenario is not None else self.DEFAULT_SCENARIO
        self.tick_ms      = tick_ms
        self.loop         = loop
        self._acc_widget  = acc_widget

        self._segment_index = 0
        self._elapsed_ms    = 0
        self._last_seg_idx  = -1   # tracks when segment changes for ACC updates

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Start (or restart) the simulation from the first segment."""
        self._segment_index = 0
        self._elapsed_ms    = 0
        self._apply(0.0, 0.5)          # reset gauges to idle position
        self._timer.start(self.tick_ms)

    def stop(self):
        """Pause the simulation; gauges keep their current value."""
        self._timer.stop()

    def reset(self):
        """Stop the simulation and return both gauges to zero."""
        self.stop()
        self._apply(0.0, 0.0)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _start_values(self):
        """Return the (speed, rpm) that the current segment starts from."""
        if self._segment_index == 0:
            return 0.0, 0.5
        prev = self.scenario[self._segment_index - 1]
        return float(prev[0]), float(prev[1])

    def _tick(self):
        """Advance the simulation by one tick."""
        # Check whether we have run out of segments
        if self._segment_index >= len(self.scenario):
            if self.loop:
                self._segment_index = 0
                self._elapsed_ms    = 0
            else:
                self._timer.stop()
                return

        seg          = self.scenario[self._segment_index]
        target_speed = seg[0]
        target_rpm   = seg[1]
        duration_ms  = seg[2]

        start_speed, start_rpm = self._start_values()

        # Normalised progress within this segment: 0.0 → 1.0
        t = min(self._elapsed_ms / duration_ms, 1.0)

        # Linear interpolation
        speed = start_speed + (target_speed - start_speed) * t
        rpm   = start_rpm   + (target_rpm   - start_rpm)   * t

        self._apply(speed, rpm)

        # Update ACC widget only when the segment changes (avoids redundant repaints)
        if self._acc_widget is not None and self._segment_index != self._last_seg_idx:
            self._last_seg_idx = self._segment_index
            acc_sp = seg[3] if len(seg) > 3 else None
            self._acc_widget.set_active(acc_sp is not None)
            if acc_sp is not None:
                self._acc_widget.set_setpoint(float(acc_sp))

        self._elapsed_ms += self.tick_ms

        # Move to the next segment once the duration has elapsed
        if self._elapsed_ms >= duration_ms:
            self._segment_index += 1
            self._elapsed_ms    = 0

    def _apply(self, speed, rpm):
        """Push interpolated values to both gauges."""
        self.speed_gauge.update_value(speed)
        self.rpm_gauge.update_value(rpm)


class BatteryIndicator(QWidget):
    """
    Circular battery State-of-Charge indicator.

    Draws a ring arc that fills clockwise from the top according to the
    battery percentage.  Color changes automatically:
        > 50 %  →  green
        20–50 % →  orange
        < 20 %  →  red

    Usage:
        self.battery = BatteryIndicator(parent)
        self.battery.setGeometry(x, y, w, h)
        self.battery.set_percentage(80)   # 0 – 100
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._percentage = 80.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_percentage(self, value):
        """Set the battery level (0–100) and repaint."""
        self._percentage = max(0.0, min(100.0, float(value)))
        self.update()

    def get_percentage(self):
        return self._percentage

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h   = self.width(), self.height()
        side   = min(w, h)
        pen_w  = max(side // 10, 6)          # ring thickness scales with widget
        pad    = pen_w + 4                    # keep arc inside the widget bounds

        arc_rect = QRectF(pad, pad, side - 2 * pad, side - 2 * pad)

        # --- background track (dark ring) ---
        painter.setPen(QPen(QColor(45, 45, 70), pen_w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(arc_rect, 0, 360 * 16)

        # --- foreground arc (charge level) ---
        if self._percentage > 50:
            color = QColor(0, 210, 110)       # green
        elif self._percentage > 20:
            color = QColor(255, 165, 0)       # orange
        else:
            color = QColor(220, 50, 50)       # red

        pen = QPen(color, pen_w, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        # Qt arc: start angle in 1/16°, counter-clockwise → use negative span
        span = int(-(self._percentage / 100.0) * 360 * 16)
        painter.drawArc(arc_rect, 90 * 16, span)

        # --- percentage text (center) ---
        painter.setPen(QPen(Qt.white))
        font = QFont("Roboto Thin", max(side // 5, 8))
        painter.setFont(font)
        painter.drawText(0, -side // 10, w, h, Qt.AlignCenter,
                         f"{int(self._percentage)}%")

        # --- "Battery" label (below center) ---
        painter.setPen(QPen(QColor(180, 180, 180)))
        font2 = QFont("Nirmala UI", max(side // 11, 6))
        painter.setFont(font2)
        painter.drawText(0, side // 5, w, h, Qt.AlignCenter, "Battery")


# ---------------------------------------------------------------------------
# Cyberpunk HUD gauge — neon glow needle, colored arc zones, digital readout
# ---------------------------------------------------------------------------

class FuturisticGauge(QWidget):
    """
    Cyberpunk HUD-style analog gauge.

    Visual features:
    - Dark radial-gradient background
    - 270° arc track split into cyan / yellow / red zones
    - Active zone fills up to the current value with a glow overlay
    - Sharp major & minor tick marks with scale labels
    - Needle drawn in multiple glow layers (wide soft glow → bright core → white tip)
    - Glowing pivot dot at center
    - Large digital value readout + unit label

    API:
        gauge.set_value(v)          – move the needle (clamped to min..max)
        gauge.set_min(v)
        gauge.set_max(v)
        gauge.set_unit("km/h")
        gauge.set_divisions(main, sub)
        gauge.update_value(v)       – alias for set_value (backward compat)
        gauge.valueChanged          – pyqtSignal(float)
    """

    valueChanged = pyqtSignal(float)

    # Gauge arc geometry (Qt angle convention: 0=East, CCW positive)
    _ARC_START  = 225   # 7:30 o'clock
    _ARC_SPAN   = 270   # degrees clockwise

    # Zone boundaries as ratios of the full range
    _ZONES = [
        (0.00, 0.60, QColor(0,   210, 210)),   # cyan
        (0.60, 0.85, QColor(255, 180,   0)),   # yellow
        (0.85, 1.00, QColor(255,  50,  80)),   # red
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value     = 0.0
        self._min_value = 0.0
        self._max_value = 100.0
        self._unit      = ""
        self._main_div  = 10
        self._sub_div   = 5

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_value(self, value):
        self._value = max(self._min_value, min(float(value), self._max_value))
        self.valueChanged.emit(self._value)
        self.update()

    update_value = set_value          # backward-compatible alias

    def set_min(self, v):
        self._min_value = float(v)
        self.update()

    def set_max(self, v):
        self._max_value = float(v)
        self.update()

    def set_unit(self, u):
        self._unit = u
        self.update()

    def set_divisions(self, main, sub=5):
        self._main_div = main
        self._sub_div  = sub
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        side = min(w, h)
        r    = side / 2 - 4

        painter.translate(w / 2, h / 2)

        self._draw_background(painter, r)
        self._draw_arc_zones(painter, r)
        self._draw_ticks(painter, r)
        self._draw_needle(painter, r)
        self._draw_pivot(painter, r)
        self._draw_text(painter, r)

    def _ratio(self):
        rng = self._max_value - self._min_value
        if rng == 0:
            return 0.0
        return (self._value - self._min_value) / rng

    # --- background ---

    def _draw_background(self, painter, r):
        grad = QRadialGradient(QPointF(0, 0), r)
        grad.setColorAt(0.0,  QColor(20, 25, 55))
        grad.setColorAt(0.65, QColor(12, 16, 38))
        grad.setColorAt(1.0,  QColor(6,  8,  18))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(-r, -r, 2*r, 2*r))

        # subtle outer ring
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 160, 255, 55), 1.2))
        painter.drawEllipse(QRectF(-r, -r, 2*r, 2*r))

    # --- arc zones ---

    def _draw_arc_zones(self, painter, r):
        arc_r = r * 0.86
        arc_w = r * 0.065
        rect  = QRectF(-arc_r, -arc_r, 2*arc_r, 2*arc_r)
        ratio = self._ratio()

        for z_start, z_end, color in self._ZONES:
            # Qt arc angles: start in CCW convention, negative span = clockwise
            qt_start = int((self._ARC_START - z_start * self._ARC_SPAN) * 16)
            qt_span  = int(-((z_end - z_start) * self._ARC_SPAN) * 16)

            # Dark background track for this zone
            bg = QPen(QColor(color.red(), color.green(), color.blue(), 35), arc_w)
            bg.setCapStyle(Qt.FlatCap)
            painter.setPen(bg)
            painter.drawArc(rect, qt_start, qt_span)

            # Active portion
            active = max(0.0, min(ratio, z_end) - z_start) / (z_end - z_start)
            if active <= 0:
                continue

            a_span = int(-(active * (z_end - z_start) * self._ARC_SPAN) * 16)

            # Glow halo
            glow = QPen(QColor(color.red(), color.green(), color.blue(), 55),
                        arc_w * 2.4)
            glow.setCapStyle(Qt.FlatCap)
            painter.setPen(glow)
            painter.drawArc(rect, qt_start, a_span)

            # Bright core
            core = QPen(color, arc_w)
            core.setCapStyle(Qt.FlatCap)
            painter.setPen(core)
            painter.drawArc(rect, qt_start, a_span)

    # --- ticks ---

    def _draw_ticks(self, painter, r):
        outer_r    = r * 0.80
        major_len  = r * 0.10
        minor_len  = r * 0.05
        total      = self._main_div * self._sub_div
        label_r    = outer_r - major_len - r * 0.09
        font       = QFont("Nirmala UI", max(int(r * 0.075), 6))
        fm         = QFontMetrics(font)

        for i in range(total + 1):
            t      = i / total
            angle  = math.radians(self._ARC_START - t * self._ARC_SPAN)
            is_maj = (i % self._sub_div == 0)
            tlen   = major_len if is_maj else minor_len

            x1 =  outer_r       * math.cos(angle)
            y1 = -outer_r       * math.sin(angle)
            x2 =  (outer_r - tlen) * math.cos(angle)
            y2 = -(outer_r - tlen) * math.sin(angle)

            if is_maj:
                painter.setPen(QPen(QColor(200, 230, 255, 210), 1.5))
            else:
                painter.setPen(QPen(QColor(90, 130, 170, 140), 0.8))
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            if is_maj:
                val  = self._min_value + t * (self._max_value - self._min_value)
                text = str(int(round(val)))
                lx   =  label_r * math.cos(angle)
                ly   = -label_r * math.sin(angle)
                tw   = fm.horizontalAdvance(text)
                th   = fm.height()
                painter.setFont(font)
                painter.setPen(QPen(QColor(150, 195, 235, 200)))
                painter.drawText(
                    QRectF(lx - tw / 2 - 2, ly - th / 2, tw + 4, th),
                    Qt.AlignCenter, text)

    # --- needle ---

    def _draw_needle(self, painter, r):
        needle_len = r * 0.70          # tip distance from centre
        tail_len   = r * 0.18          # how far the tail extends past centre
        bw         = r * 0.028         # half-width at needle base

        # Correct rotation: start angle + ratio × span, all CW in Qt painter space.
        # At ratio=0  → 225° CW from 12 o'clock  = 7:30 (lower-left, arc start)
        # At ratio=1  → 495° CW                  = 4:30 (lower-right, arc end)
        rotation = self._ARC_START + self._ratio() * self._ARC_SPAN

        painter.save()
        painter.rotate(rotation)       # Qt rotate() is clockwise-positive

        # --- tapered needle polygon (pointing UP before rotation) ---
        # tip: sharp point at top
        # base: two flanking points just above centre
        # tail: two narrow points below centre
        tip    = QPointF(0,          -needle_len)
        base_l = QPointF(-bw,        -r * 0.07)
        base_r = QPointF( bw,        -r * 0.07)
        tail_l = QPointF(-bw * 0.45,  tail_len)
        tail_r = QPointF( bw * 0.45,  tail_len)

        poly = QPolygonF([tip, base_r, tail_r, tail_l, base_l])

        # Outer glow (soft cyan halo around the whole needle)
        for halo_w, alpha in [(bw * 10, 18), (bw * 6, 40), (bw * 3, 80)]:
            painter.setPen(QPen(QColor(0, 210, 255, alpha),
                                halo_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawConvexPolygon(poly)

        # Filled needle body (cyan with slight transparency)
        painter.setPen(QPen(QColor(140, 230, 255, 220), 0.7,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(QBrush(QColor(0, 195, 255, 200)))
        painter.drawConvexPolygon(poly)

        # Bright white spine from base to tip
        painter.setPen(QPen(QColor(255, 255, 255, 200), 0.9,
                            Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(QPointF(0, -r * 0.07), tip)

        painter.restore()

    # --- pivot ---

    def _draw_pivot(self, painter, r):
        painter.setPen(Qt.NoPen)
        for cr, alpha in [(int(r*0.045), 35), (int(r*0.032), 80),
                          (int(r*0.022), 160), (int(r*0.013), 240)]:
            painter.setBrush(QBrush(QColor(0, 180, 255, alpha)))
            painter.drawEllipse(QPointF(0, 0), cr, cr)
        painter.setBrush(QBrush(QColor(220, 245, 255, 255)))
        painter.drawEllipse(QPointF(0, 0), max(int(r*0.007), 2),
                                           max(int(r*0.007), 2))

    # --- text ---

    def _draw_text(self, painter, r):
        # Large value
        val_str  = str(int(self._value))
        val_font = QFont("Roboto Thin", max(int(r * 0.23), 10))
        painter.setFont(val_font)
        painter.setPen(QPen(QColor(220, 240, 255, 255)))
        fm  = QFontMetrics(val_font)
        tw  = fm.horizontalAdvance(val_str)
        th  = fm.height()
        painter.drawText(QRectF(-tw / 2, r * 0.08, tw + 2, th),
                         Qt.AlignCenter, val_str)

        # Unit label
        if self._unit:
            u_font = QFont("Nirmala UI", max(int(r * 0.09), 6))
            painter.setFont(u_font)
            painter.setPen(QPen(QColor(80, 160, 210, 190)))
            ufm = QFontMetrics(u_font)
            uw  = ufm.horizontalAdvance(self._unit)
            painter.drawText(
                QRectF(-uw / 2, r * 0.34, uw + 4, ufm.height()),
                Qt.AlignCenter, self._unit)


# ---------------------------------------------------------------------------
# ACC (Adaptive Cruise Control) HUD indicator
# ---------------------------------------------------------------------------

class ACCWidget(QWidget):
    """
    Compact cyberpunk HUD pill showing ACC status and speed setpoint.

    Left half  : glowing green LED voyant + bold 'ACC' label
    Right half : 'SET' micro-label  +  setpoint value  +  unit

    States:
        inactive – dim grey LED, '---' placeholder value
        active   – pulsing green glow, shows numeric setpoint

    API:
        widget.set_active(True / False)   – activate / deactivate display
        widget.set_setpoint(value)        – target speed to display (numeric)
        widget.set_unit("km/h")           – unit string (default "km/h")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active   = False
        self._setpoint = 0.0
        self._unit     = "km/h"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active(self, active):
        self._active = bool(active)
        self.update()

    def set_setpoint(self, value):
        self._setpoint = float(value)
        self.update()

    def set_unit(self, unit):
        self._unit = str(unit)
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # ── panel background ──────────────────────────────────────────
        bg   = QColor(0,  40,  20, 135) if self._active else QColor(14, 18, 36, 135)
        bord = QColor(0, 255, 120,  90) if self._active else QColor(45, 65, 110,  65)
        p.setPen(QPen(bord, 1.2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0.6, 0.6, w - 1.2, h - 1.2), 9, 9)

        # ── LED voyant ────────────────────────────────────────────────
        led_cx = w * 0.13
        led_cy = h * 0.50
        led_r  = min(h * 0.21, w * 0.09)

        if self._active:
            for glow_r, alpha in [(led_r * 2.9, 18), (led_r * 1.9, 46), (led_r * 1.3, 88)]:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(0, 255, 120, alpha)))
                p.drawEllipse(QPointF(led_cx, led_cy), glow_r, glow_r)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 255, 120)))
            p.drawEllipse(QPointF(led_cx, led_cy), led_r, led_r)
            # specular highlight
            p.setBrush(QBrush(QColor(255, 255, 255, 185)))
            p.drawEllipse(QPointF(led_cx - led_r * 0.26, led_cy - led_r * 0.30),
                          led_r * 0.36, led_r * 0.36)
            lbl_color = QColor(0, 255, 120, 230)
        else:
            p.setPen(QPen(QColor(22, 50, 38, 110), 1))
            p.setBrush(QBrush(QColor(6, 14, 10, 155)))
            p.drawEllipse(QPointF(led_cx, led_cy), led_r, led_r)
            lbl_color = QColor(52, 80, 115, 130)

        # ── "ACC" label ───────────────────────────────────────────────
        acc_f = QFont("Nirmala UI", max(int(h * 0.27), 7))
        acc_f.setBold(True)
        p.setFont(acc_f)
        p.setPen(QPen(lbl_color))
        p.drawText(QRectF(w * 0.27, 0, w * 0.24, h),
                   Qt.AlignVCenter | Qt.AlignLeft, "ACC")

        # ── vertical divider ──────────────────────────────────────────
        div_x = w * 0.54
        p.setPen(QPen(bord, 0.9))
        p.drawLine(QPointF(div_x, h * 0.16), QPointF(div_x, h * 0.84))

        # ── right half: setpoint ──────────────────────────────────────
        rx = div_x + w * 0.05

        # "SET" micro-label
        set_f = QFont("Nirmala UI", max(int(h * 0.19), 5))
        p.setFont(set_f)
        p.setPen(QPen(QColor(0, 190, 255, 150) if self._active
                      else QColor(42, 62, 100, 90)))
        p.drawText(QRectF(rx, 1, w - rx - 3, h * 0.44),
                   Qt.AlignVCenter | Qt.AlignLeft, "SET")

        # setpoint value
        val_str = str(int(self._setpoint)) if self._active else "\u2013\u2013\u2013"
        val_f   = QFont("Roboto Thin", max(int(h * 0.33), 9))
        p.setFont(val_f)
        p.setPen(QPen(QColor(0, 255, 120, 255) if self._active
                      else QColor(42, 62, 100, 110)))
        p.drawText(QRectF(rx, h * 0.38, w - rx - 3, h * 0.60),
                   Qt.AlignVCenter | Qt.AlignLeft, val_str)

        # unit label (only when active, tucked after the value)
        if self._active and self._unit:
            fm = QFontMetrics(val_f)
            vw = fm.horizontalAdvance(val_str)
            u_f = QFont("Nirmala UI", max(int(h * 0.16), 5))
            p.setFont(u_f)
            p.setPen(QPen(QColor(0, 175, 140, 155)))
            p.drawText(QRectF(rx + vw + 2, h * 0.49, w, h * 0.50),
                       Qt.AlignVCenter | Qt.AlignLeft, self._unit)


# ---------------------------------------------------------------------------
# Speed Regulator HUD indicator
# ---------------------------------------------------------------------------

class SpeedRegWidget(QWidget):
    """
    Compact cyberpunk HUD pill for Speed Regulator status.

    Active   – pulsing green glow + bold 'SPEED REG' label
    Inactive – dim grey LED + greyed label

    API:
        widget.set_active(True / False)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = False

    def set_active(self, active):
        self._active = bool(active)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()

        # ── panel background ──────────────────────────────────────────
        bg   = QColor(0,  40,  20, 135) if self._active else QColor(14, 18, 36, 135)
        bord = QColor(0, 255, 120,  90) if self._active else QColor(45, 65, 110,  65)
        p.setPen(QPen(bord, 1.2))
        p.setBrush(QBrush(bg))
        p.drawRoundedRect(QRectF(0.6, 0.6, w - 1.2, h - 1.2), 9, 9)

        # ── LED voyant ────────────────────────────────────────────────
        led_cx = w * 0.10
        led_cy = h * 0.50
        led_r  = min(h * 0.21, w * 0.07)

        if self._active:
            for glow_r, alpha in [(led_r * 2.9, 18), (led_r * 1.9, 46), (led_r * 1.3, 88)]:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(0, 255, 120, alpha)))
                p.drawEllipse(QPointF(led_cx, led_cy), glow_r, glow_r)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(0, 255, 120)))
            p.drawEllipse(QPointF(led_cx, led_cy), led_r, led_r)
            p.setBrush(QBrush(QColor(255, 255, 255, 185)))
            p.drawEllipse(QPointF(led_cx - led_r * 0.26, led_cy - led_r * 0.30),
                          led_r * 0.36, led_r * 0.36)
            lbl_color = QColor(0, 255, 120, 230)
        else:
            p.setPen(QPen(QColor(22, 50, 38, 110), 1))
            p.setBrush(QBrush(QColor(6, 14, 10, 155)))
            p.drawEllipse(QPointF(led_cx, led_cy), led_r, led_r)
            lbl_color = QColor(52, 80, 115, 130)

        # ── "SPEED REG" label ─────────────────────────────────────────
        f = QFont("Nirmala UI", max(int(h * 0.24), 6))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(lbl_color))
        p.drawText(QRectF(w * 0.20, 0, w * 0.78, h),
                   Qt.AlignVCenter | Qt.AlignLeft, "SPEED REG")


# ---------------------------------------------------------------------------
# UDP receiver — receives speed data from Raspberry Pi over UDP port 5005
# ---------------------------------------------------------------------------

import socket
import json

from PyQt5.QtCore import QThread


class UDPReceiver(QThread):
    """
    Listens on UDP port 5005 for JSON packets of the form {"speed": 72.5}.
    Emits speed_received(float) on every valid packet.
    Emits timeout_occurred() when no packet arrives within TIMEOUT_S seconds.
    """

    speed_received        = pyqtSignal(float)   # km/h
    setpointspeed_recived = pyqtSignal(float)   # km/h
    lead_present_received = pyqtSignal(bool)    # True = vehicle ahead detected → ACC active
    speed_reg_received    = pyqtSignal(bool)    # True = speed regulator active

    timeout_occurred      = pyqtSignal()        # no data for TIMEOUT_S seconds

    HOST      = "0.0.0.0"
    PORT      = 5005
    TIMEOUT_S = 3     # seconds without data before emitting timeout signal
    SOCK_WAIT = 1.0   # socket timeout so the loop can check _should_stop

    def __init__(self):
        super().__init__()
        self._should_stop = False

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.HOST, self.PORT))
        sock.settimeout(self.SOCK_WAIT)

        last_data_time = time.time()

        while not self._should_stop:
            try:
                data, _ = sock.recvfrom(1024)
                payload = json.loads(data.decode())
                speed = float(payload["speed"])
                self.speed_received.emit(speed)
                if "lead_present" in payload:
                    self.lead_present_received.emit(bool(payload["lead_present"]))
                if "speed_reg" in payload:
                    self.speed_reg_received.emit(bool(payload["speed_reg"]))
                if "setpoint_speed" in payload:
                    self.setpointspeed_recived.emit(float(payload["setpoint_speed"]))
                last_data_time = time.time()
            except socket.timeout:
                if time.time() - last_data_time > self.TIMEOUT_S:
                    self.timeout_occurred.emit()
                    last_data_time = time.time()   # re-arm to avoid spamming
            except (json.JSONDecodeError, KeyError, ValueError):
                pass   # malformed packet, ignore

        sock.close()

    def stop(self):
        self._should_stop = True
