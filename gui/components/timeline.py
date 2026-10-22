from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyleOptionSlider,
)
from PySide6.QtGui import QFont, QCursor, QMouseEvent
from qfluentwidgets import FluentIcon as FI, Theme

from gui.styles.theme import ACCENT_BLUE, CORRIDOR_YELLOW, BORDER_SUBTLE


class ClickableSlider(QSlider):
    """QSlider that jumps directly to the clicked position."""

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            slider_length = opt.rect.width()
            slider_min = self.minimum()
            slider_max = self.maximum()
            
            if slider_max > slider_min and slider_length > 0:
                pos = event.pos().x()
                new_val = slider_min + ((slider_max - slider_min) * pos) // slider_length
                self.setValue(int(new_val))
                event.accept()
        super().mousePressEvent(event)


class TimelineWidget(QWidget):
    """Timeline transport and scrubbing controls in English with detailed Russian hover tooltips."""

    frame_changed = Signal(int)
    play_state_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #16161A;
                border-top: 1px solid {BORDER_SUBTLE};
            }}
            QPushButton {{
                background-color: #222228;
                border: 1px solid #32323A;
                border-radius: 5px;
                color: #FFFFFF;
                font-weight: 700;
                min-width: 32px;
                min-height: 26px;
                padding: 3px 6px;
            }}
            QPushButton:hover {{
                background-color: #2C2C34;
                border-color: {ACCENT_BLUE};
            }}
            QPushButton:pressed {{
                background-color: #18181E;
            }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: #25252B;
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_BLUE};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                border: none;
                width: 12px;
                height: 12px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 6px;
            }}
            QSlider::handle:horizontal:hover {{
                background: #D9F7FF;
            }}
        """)

        self.current_frame = 0
        self.total_frames = 1
        self.fps = 24.0
        self.is_playing = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 6, 14, 8)
        main_layout.setSpacing(6)

        # 1. Transport Bar
        transport_layout = QHBoxLayout()
        transport_layout.setSpacing(6)

        self.frame_label = QLabel("0 / 0")
        self.frame_label.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self.frame_label.setStyleSheet("color: #FFFFFF;")
        self.frame_label.setToolTip("<b>Счетчик кадров</b><br>Текущий кадр / всего кадров в клипе.")
        transport_layout.addWidget(self.frame_label)

        transport_layout.addStretch()

        self.btn_first = QPushButton("|<")
        self.btn_first.setToolTip("<b>First Frame (Home)</b><br>Перейти к самому первому кадру видео.")
        self.btn_first.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_first.clicked.connect(self.go_to_first)
        transport_layout.addWidget(self.btn_first)

        self.btn_prev = QPushButton()
        self.btn_prev.setIcon(FI.LEFT_ARROW.icon(Theme.DARK))
        self.btn_prev.setIconSize(QSize(14, 14))
        self.btn_prev.setToolTip("<b>Previous Frame (Left Arrow)</b><br>Шаг на один кадр назад.")
        self.btn_prev.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_prev.clicked.connect(self.prev_frame)
        transport_layout.addWidget(self.btn_prev)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(FI.PLAY.icon(Theme.DARK))
        self.btn_play.setIconSize(QSize(15, 15))
        self.btn_play.setToolTip("<b>Play / Pause (Space)</b><br>Запустить или приостановить воспроизведение клипа.")
        self.btn_play.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_play.clicked.connect(self.toggle_play)
        transport_layout.addWidget(self.btn_play)

        self.btn_next = QPushButton()
        self.btn_next.setIcon(FI.RIGHT_ARROW.icon(Theme.DARK))
        self.btn_next.setIconSize(QSize(14, 14))
        self.btn_next.setToolTip("<b>Next Frame (Right Arrow)</b><br>Шаг на один кадр вперед.")
        self.btn_next.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_next.clicked.connect(self.next_frame)
        transport_layout.addWidget(self.btn_next)

        self.btn_last = QPushButton(">|")
        self.btn_last.setToolTip("<b>Last Frame (End)</b><br>Перейти к последнему кадру видео.")
        self.btn_last.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_last.clicked.connect(self.go_to_last)
        transport_layout.addWidget(self.btn_last)

        transport_layout.addStretch()

        self.fps_label = QLabel("24.00 fps")
        self.fps_label.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.fps_label.setToolTip("<b>FPS</b><br>Частота кадров активного видеоклипа.")
        transport_layout.addWidget(self.fps_label)

        main_layout.addLayout(transport_layout)

        # 2. Scrubber
        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.slider.setToolTip("<b>Таймлайн (Scrubber)</b><br>Перетащите ползунок или кликните в любую точку шкалы для быстрого перехода к кадру.")
        self.slider.valueChanged.connect(self._on_slider_changed)
        main_layout.addWidget(self.slider)

    def set_clip(self, total_frames: int, fps: float):
        self.total_frames = max(1, total_frames)
        self.fps = fps or 24.0
        self.current_frame = 0

        self.slider.blockSignals(True)
        self.slider.setRange(0, self.total_frames - 1)
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        interval_ms = max(10, int(1000.0 / self.fps))
        self.timer.setInterval(interval_ms)

        self.fps_label.setText(f"{self.fps:.2f} fps")
        self._update_label()

    def set_frame(self, frame_idx: int):
        frame_idx = max(0, min(frame_idx, self.total_frames - 1))
        if frame_idx != self.current_frame:
            self.current_frame = frame_idx
            self.slider.blockSignals(True)
            self.slider.setValue(frame_idx)
            self.slider.blockSignals(False)
            self._update_label()
            self.frame_changed.emit(self.current_frame)

    def _on_slider_changed(self, value: int):
        self.current_frame = value
        self._update_label()
        self.frame_changed.emit(self.current_frame)

    def _update_label(self):
        self.frame_label.setText(f"{self.current_frame + 1} / {self.total_frames}")

    def toggle_play(self):
        if self.is_playing:
            self.pause()
        else:
            self.play()

    def play(self):
        if not self.is_playing:
            self.is_playing = True
            self.btn_play.setIcon(FI.PAUSE.icon(Theme.DARK))
            self.timer.start()
            self.play_state_changed.emit(True)

    def pause(self):
        if self.is_playing:
            self.is_playing = False
            self.btn_play.setIcon(FI.PLAY.icon(Theme.DARK))
            self.timer.stop()
            self.play_state_changed.emit(False)

    def _on_timer_tick(self):
        next_f = (self.current_frame + 1) % self.total_frames
        self.set_frame(next_f)

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
