from __future__ import annotations

import time
from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QPoint, QRectF, QPointF
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PySide6.QtGui import (
    QFont,
    QCursor,
    QMouseEvent,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QLinearGradient,
)
from qfluentwidgets import FluentIcon as FI, Theme

from gui.styles.theme import ACCENT_BLUE, BORDER_SUBTLE


class TimelineScrubber(QWidget):
    """
    High-performance custom painted timeline scrubber.
    Eliminates QSlider jitter, negative margin glitches, and High-DPI rounding errors.
    Provides butter-smooth playhead dragging and subpixel precision.
    """
    frame_seek_requested = Signal(int)
    scrub_started = Signal()
    scrub_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.current_frame = 0
        self.total_frames = 1
        self.fps = 24.0

        self._is_dragging = False
        self._hover_x: Optional[int] = None
        self._pad = 8.0  # Horizontal padding for handle radius

    def set_range(self, total_frames: int, fps: float = 24.0):
        self.total_frames = max(1, total_frames)
        self.fps = fps or 24.0
        self.current_frame = max(0, min(self.current_frame, self.total_frames - 1))
        self.update()

    def set_frame(self, frame_idx: int):
        if self._is_dragging:
            return  # Preserve smooth manual dragging
        frame_idx = max(0, min(frame_idx, self.total_frames - 1))
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self.update()

    def _frame_at_pos(self, x: float) -> int:
        usable_w = max(1.0, float(self.width()) - 2.0 * self._pad)
        pct = max(0.0, min(1.0, (x - self._pad) / usable_w))
        return int(round(pct * (self.total_frames - 1)))

    def _x_for_frame(self, frame: int) -> float:
        if self.total_frames <= 1:
            return float(self._pad)
        usable_w = float(self.width()) - 2.0 * self._pad
        pct = frame / float(self.total_frames - 1)
        return self._pad + pct * usable_w

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self.scrub_started.emit()
            target_f = self._frame_at_pos(event.position().x())
            self.current_frame = target_f
            self.update()
            self.frame_seek_requested.emit(target_f)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        self._hover_x = int(event.position().x())
        if self._is_dragging:
            target_f = self._frame_at_pos(event.position().x())
            if target_f != self.current_frame:
                self.current_frame = target_f
                self.update()
                self.frame_seek_requested.emit(target_f)
        else:
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self.scrub_finished.emit()
            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        cy = h / 2.0
        usable_w = max(1.0, w - 2.0 * self._pad)

        is_hovered = (self._hover_x is not None) or self._is_dragging
        track_h = 6.0 if is_hovered else 4.0
        track_r = track_h / 2.0
        track_rect = QRectF(self._pad, cy - track_r, usable_w, track_h)

        # 1. Background Track
        groove_color = QColor("#282834") if is_hovered else QColor("#202026")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(groove_color))
        painter.drawRoundedRect(track_rect, track_r, track_r)

        # 2. Played Progress Fill
        head_x = self._x_for_frame(self.current_frame)
        fill_w = max(0.0, head_x - self._pad)
        if fill_w > 0:
            fill_rect = QRectF(self._pad, cy - track_r, fill_w, track_h)
            grad = QLinearGradient(self._pad, 0, head_x, 0)
            grad.setColorAt(0.0, QColor("#3B82F6"))  # Studio Blue
            grad.setColorAt(1.0, QColor("#00D2FF"))  # Neon Cyan
            painter.setBrush(QBrush(grad))
            painter.drawRoundedRect(fill_rect, track_r, track_r)

        # 3. Hover Hairline
        if is_hovered and self._hover_x is not None and not self._is_dragging:
            hx = max(self._pad, min(w - self._pad, float(self._hover_x)))
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
            painter.drawLine(QPointF(hx, 3.0), QPointF(hx, h - 3.0))

        # 4. Playhead Handle
        handle_r = 7.0 if is_hovered else 5.5
        handle_center = QPointF(head_x, cy)

        if is_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 210, 255, 70)))
            painter.drawEllipse(handle_center, handle_r + 3.0, handle_r + 3.0)

        painter.setPen(QPen(QColor("#00D2FF" if is_hovered else "#3B82F6"), 1.5))
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(handle_center, handle_r, handle_r)


class TimelineWidget(QWidget):
    """
    Monolithic video transport and scrubbing control dock.
    Features wall-clock synchronized playback, zero layout twitching,
    fixed metrics panels, and unified studio styling.
    """

    frame_changed = Signal(int)
    play_state_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setStyleSheet(f"""
            QWidget#timelineDock {{
                background-color: #141418;
                border-top: 1px solid {BORDER_SUBTLE};
            }}
            QPushButton.transport-btn {{
                background-color: #202026;
                border: 1px solid #303038;
                border-radius: 4px;
                color: #FFFFFF;
                font-weight: 700;
                min-width: 32px;
                max-width: 38px;
                min-height: 26px;
                max-height: 26px;
                padding: 0px 4px;
            }}
            QPushButton.transport-btn:hover {{
                background-color: #2A2A34;
                border-color: {ACCENT_BLUE};
            }}
            QPushButton.transport-btn:pressed {{
                background-color: #16161C;
            }}
            QPushButton#btnPlay {{
                background-color: #22222A;
                border: 1px solid #3B82F6;
                border-radius: 4px;
                min-width: 44px;
                max-width: 44px;
                min-height: 26px;
                max-height: 26px;
            }}
            QPushButton#btnPlay:hover {{
                background-color: #3B82F6;
            }}
            QPushButton.loop-btn {{
                background-color: #1A1A20;
                border: 1px solid #2C2C36;
                border-radius: 4px;
                color: #94A3B8;
                font-size: 10px;
                font-weight: 700;
                min-height: 24px;
                max-height: 24px;
                padding: 2px 8px;
            }}
            QPushButton.loop-btn:hover {{
                background-color: #24242E;
                color: #FFFFFF;
            }}
            QPushButton.loop-btn[checked="true"] {{
                background-color: #1E293B;
                border-color: #38BDF8;
                color: #38BDF8;
            }}
        """)
        self.setObjectName("timelineDock")

        self.current_frame = 0
        self.total_frames = 1
        self.fps = 24.0
        self.is_playing = False
        self.is_looping = True

        self._play_start_time: float = 0.0
        self._play_start_frame: int = 0
        self._was_playing_before_scrub = False

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._on_timer_tick)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 4, 12, 6)
        main_layout.setSpacing(4)

        # 1. Custom Smooth Scrubber
        self.scrubber = TimelineScrubber()
        self.scrubber.setToolTip("<b>Timeline Scrubber</b><br>Click or drag to navigate frames.")
        self.scrubber.frame_seek_requested.connect(self._on_scrubber_seek)
        self.scrubber.scrub_started.connect(self._on_scrub_started)
        self.scrubber.scrub_finished.connect(self._on_scrub_finished)
        main_layout.addWidget(self.scrubber)

        # 2. Solid Transport Dock (3 Fixed-Balance Zones)
        dock_layout = QHBoxLayout()
        dock_layout.setContentsMargins(0, 0, 0, 0)
        dock_layout.setSpacing(8)

        # --- ZONE 1: Left Fixed Metrics (Timecode & Frame, 170px fixed) ---
        left_zone = QWidget()
        left_zone.setFixedWidth(170)
        left_layout = QHBoxLayout(left_zone)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.timecode_label = QLabel("00:00:00:00")
        self.timecode_label.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self.timecode_label.setStyleSheet("color: #FFFFFF;")
        self.timecode_label.setToolTip("<b>Timecode</b><br>Hours : Minutes : Seconds : Frames.")
        left_layout.addWidget(self.timecode_label)

        self.frame_badge = QLabel("0001 / 0001")
        self.frame_badge.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.frame_badge.setStyleSheet("color: #94A3B8; background: #1C1C22; border: 1px solid #282830; border-radius: 3px; padding: 1px 4px;")
        self.frame_badge.setToolTip("<b>Frame Counter</b><br>Current frame / Total frames.")
        left_layout.addWidget(self.frame_badge)
        left_layout.addStretch()

        dock_layout.addWidget(left_zone)
        dock_layout.addStretch(1)

        # --- ZONE 2: Center Transport Buttons Cluster ---
        center_zone = QWidget()
        center_layout = QHBoxLayout(center_zone)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        self.btn_first = QPushButton()
        self.btn_first.setProperty("class", "transport-btn")
        self.btn_first.setIcon(FI.SKIP_BACK.icon(Theme.DARK))
        self.btn_first.setIconSize(QSize(13, 13))
        self.btn_first.setToolTip("<b>First Frame (Home)</b><br>Jump to the very first frame.")
        self.btn_first.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_first.clicked.connect(self.go_to_first)
        center_layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton()
        self.btn_prev.setProperty("class", "transport-btn")
        self.btn_prev.setIcon(FI.LEFT_ARROW.icon(Theme.DARK))
        self.btn_prev.setIconSize(QSize(13, 13))
        self.btn_prev.setToolTip("<b>Previous Frame (Left Arrow)</b><br>Step 1 frame backward.")
        self.btn_prev.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_prev.clicked.connect(self.prev_frame)
        center_layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton()
        self.btn_play.setObjectName("btnPlay")
        self.btn_play.setIcon(FI.PLAY.icon(Theme.DARK))
        self.btn_play.setIconSize(QSize(14, 14))
        self.btn_play.setToolTip("<b>Play / Pause (Space)</b><br>Start or pause playback.")
        self.btn_play.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_play.clicked.connect(self.toggle_play)
        center_layout.addWidget(self.btn_play)

        self.btn_next = QPushButton()
        self.btn_next.setProperty("class", "transport-btn")
        self.btn_next.setIcon(FI.RIGHT_ARROW.icon(Theme.DARK))
        self.btn_next.setIconSize(QSize(13, 13))
        self.btn_next.setToolTip("<b>Next Frame (Right Arrow)</b><br>Step 1 frame forward.")
        self.btn_next.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_next.clicked.connect(self.next_frame)
        center_layout.addWidget(self.btn_next)

        self.btn_last = QPushButton()
        self.btn_last.setProperty("class", "transport-btn")
        self.btn_last.setIcon(FI.SKIP_FORWARD.icon(Theme.DARK))
        self.btn_last.setIconSize(QSize(13, 13))
        self.btn_last.setToolTip("<b>Last Frame (End)</b><br>Jump to the last frame.")
        self.btn_last.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_last.clicked.connect(self.go_to_last)
        center_layout.addWidget(self.btn_last)

        dock_layout.addWidget(center_zone)
        dock_layout.addStretch(1)

        # --- ZONE 3: Right Fixed Controls (Loop & FPS, 170px fixed) ---
        right_zone = QWidget()
        right_zone.setFixedWidth(170)
        right_layout = QHBoxLayout(right_zone)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addStretch()

        self.btn_loop = QPushButton("Loop: ON")
        self.btn_loop.setProperty("class", "loop-btn")
        self.btn_loop.setProperty("checked", "true")
        self.btn_loop.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_loop.setToolTip("<b>Loop Playback</b><br>Toggle seamless looping of the clip.")
        self.btn_loop.clicked.connect(self._toggle_loop)
        right_layout.addWidget(self.btn_loop)

        self.fps_badge = QLabel("24.00 fps")
        self.fps_badge.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.fps_badge.setStyleSheet("color: #94A3B8; background: #1C1C22; border: 1px solid #282830; border-radius: 3px; padding: 2px 6px;")
        self.fps_badge.setToolTip("<b>FPS</b><br>Playback frame rate.")
        right_layout.addWidget(self.fps_badge)

        dock_layout.addWidget(right_zone)
        main_layout.addLayout(dock_layout)

    def set_clip(self, total_frames: int, fps: float):
        self.total_frames = max(1, total_frames)
        self.fps = fps or 24.0
        self.current_frame = 0

        self.scrubber.set_range(self.total_frames, self.fps)
        self.fps_badge.setText(f"{self.fps:.2f} fps")

        interval_ms = max(5, int(1000.0 / self.fps))
        self.timer.setInterval(interval_ms)
        self._update_metrics()

    def set_frame(self, frame_idx: int):
        frame_idx = max(0, min(frame_idx, self.total_frames - 1))
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self.scrubber.set_frame(frame_idx)
            self._update_metrics()
            self.frame_changed.emit(self.current_frame)

    def _on_scrubber_seek(self, frame_idx: int):
        self.current_frame = frame_idx
        self._update_metrics()
        self.frame_changed.emit(self.current_frame)

    def _on_scrub_started(self):
        self._was_playing_before_scrub = self.is_playing
        if self.is_playing:
            self.pause()

    def _on_scrub_finished(self):
        if self._was_playing_before_scrub:
            self.play()

    def _update_metrics(self):
        # Precise timecode calculation: HH:MM:SS:FF
        total_sec = self.current_frame / max(1.0, self.fps)
        h = int(total_sec // 3600)
        m = int((total_sec % 3600) // 60)
        s = int(total_sec % 60)
        f = int(round((total_sec - int(total_sec)) * self.fps))
        self.timecode_label.setText(f"{h:02d}:{m:02d}:{s:02d}:{f:02d}")

        pad_len = max(4, len(str(self.total_frames)))
        cur_str = str(self.current_frame + 1).zfill(pad_len)
        tot_str = str(self.total_frames).zfill(pad_len)
        self.frame_badge.setText(f"{cur_str} / {tot_str}")

    def _toggle_loop(self):
        self.is_looping = not self.is_looping
        self.btn_loop.setText("Loop: ON" if self.is_looping else "Loop: OFF")
        self.btn_loop.setProperty("checked", "true" if self.is_looping else "false")
        self.btn_loop.style().unpolish(self.btn_loop)
        self.btn_loop.style().polish(self.btn_loop)

    def toggle_play(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.is_playing:
            self.is_playing = True
            self.btn_play.setIcon(FI.PAUSE.icon(Theme.DARK))
            self._play_start_time = time.perf_counter()
            self._play_start_frame = self.current_frame
            self.timer.start()
            self.play_state_changed.emit(True)

    def pause(self):
        if self.is_playing:
            self.is_playing = False
            self.btn_play.setIcon(FI.PLAY.icon(Theme.DARK))
            self.timer.stop()
            self.play_state_changed.emit(False)

    def _on_timer_tick(self):
        if not self.is_playing or self.total_frames <= 1:
            return

        elapsed = time.perf_counter() - self._play_start_time
        target = self._play_start_frame + int(round(elapsed * self.fps))

        if target >= self.total_frames:
            if self.is_looping:
                target = target % self.total_frames
                self._play_start_time = time.perf_counter() - (target / max(1.0, self.fps))
                self._play_start_frame = 0
            else:
                target = self.total_frames - 1
                self.pause()

        self.set_frame(target)

    def prev_frame(self):
        self.pause()
        self.set_frame(max(0, self.current_frame - 1))

    def next_frame(self):
        self.pause()
        self.set_frame(min(self.total_frames - 1, self.current_frame + 1))

    def go_to_first(self):
        self.pause()
        self.set_frame(0)

    def go_to_last(self):
        self.pause()
        self.set_frame(self.total_frames - 1)
