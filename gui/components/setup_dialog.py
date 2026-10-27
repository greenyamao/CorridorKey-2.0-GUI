"""Unified Setup Dialog for CorridorKey 2.0 Workbench.

Automated, zero-prompt setup wizard that sequentially downloads and verifies:
1. CorridorKey 2.0 Core Engine
2. Portable FFmpeg / FFprobe binaries
3. AI Model Weights (~5.1 GB)

Features live dual-progress bars (Overall & Current Task), live byte-rate telemetry,
expandable console log, and safe QThread cancellation.
Strict English-only rule compliant.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QFrame,
    QFileDialog,
    QMessageBox,
)
from qfluentwidgets import FluentIcon as FI

from gui.styles.theme import (
    BG_CANVAS,
    CARD_BG,
    BORDER_SUBTLE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
    CORRIDOR_GREEN,
    ACCENT_BLUE,
    ACCENT_CYAN,
    CORRIDOR_YELLOW,
)
from gui.managers.engine_manager import EngineManager
from gui.managers.setup_worker import UnifiedSetupWorker


class SetupChecklistRow(QFrame):
    """Visual checklist row showing component status (Pending, In Progress, Ready)."""

    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame {
                background-color: #1A1A20;
                border: 1px solid #282832;
                border-radius: 5px;
                padding: 2px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)

        self.lbl_title = QLabel(title)
        self.lbl_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.lbl_title.setStyleSheet("color: #FFFFFF; border: none; background: transparent;")
        text_layout.addWidget(self.lbl_title)

        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setFont(QFont("Segoe UI", 8))
        self.lbl_sub.setStyleSheet("color: #9A9AA6; border: none; background: transparent;")
        text_layout.addWidget(self.lbl_sub)

        layout.addLayout(text_layout)
        layout.addStretch()

        self.lbl_badge = QLabel("Pending")
        self.lbl_badge.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.lbl_badge.setStyleSheet("""
            color: #9A9AA6;
            background-color: #24242C;
            border: 1px solid #363642;
            border-radius: 4px;
            padding: 2px 8px;
        """)
        layout.addWidget(self.lbl_badge)

    def set_status(self, status: str):
        """Updates badge style according to status ('pending', 'running', 'ready', 'error')."""
        st = status.lower()
        if st == "ready":
            self.lbl_badge.setText("Ready")
            self.lbl_badge.setStyleSheet("""
                color: #FFFFFF;
                background-color: #10B981;
                border: 1px solid #059669;
                border-radius: 4px;
                padding: 2px 8px;
            """)
        elif st == "running":
            self.lbl_badge.setText("Installing...")
            self.lbl_badge.setStyleSheet("""
                color: #FFFFFF;
                background-color: #2563EB;
                border: 1px solid #3B82F6;
                border-radius: 4px;
                padding: 2px 8px;
            """)
        elif st == "error":
            self.lbl_badge.setText("Failed")
            self.lbl_badge.setStyleSheet("""
                color: #FFFFFF;
                background-color: #EF4444;
                border: 1px solid #DC2626;
                border-radius: 4px;
                padding: 2px 8px;
            """)
        else:
            self.lbl_badge.setText("Pending")
            self.lbl_badge.setStyleSheet("""
                color: #9A9AA6;
                background-color: #24242C;
                border: 1px solid #363642;
                border-radius: 4px;
                padding: 2px 8px;
            """)


class SetupDialog(QDialog):
    """Unified setup wizard with live dual-progress bars and automatic execution."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CorridorKey 2.0 Workbench — Setup Wizard")
        self.resize(640, 520)
        self.setMinimumSize(580, 480)
        self.setStyleSheet("background-color: #141418; color: #FFFFFF;")

        self._is_completed = False
        self._init_ui()
        self._start_worker()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)

        # Header
        title_lbl = QLabel("CorridorKey 2.0 Setup")
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("Configuring engine, video transcoding tools, and neural network weights (~5.2 GB total)...")
        sub_lbl.setStyleSheet("color: #D4D4DC; font-size: 11px;")
        layout.addWidget(sub_lbl)

        layout.addSpacing(4)

        # Checklist rows
        self.row_engine = SetupChecklistRow(
            "1. CorridorKey 2.0 Engine",
            "Upstream neural matting framework and pipeline scripts"
        )
        layout.addWidget(self.row_engine)

        self.row_ffmpeg = SetupChecklistRow(
            "2. Portable FFmpeg & FFprobe",
            "Hardware-accelerated video decoding and ProRes / WebM container encoders"
        )
        layout.addWidget(self.row_ffmpeg)

        self.row_weights = SetupChecklistRow(
            "3. Deep Learning Checkpoints (~5.08 GB)",
            "CorridorKey v2, C-RADIOv4 Vision, MoGe-2 3D Geometry, RVM Matting"
        )
        layout.addWidget(self.row_weights)

        layout.addSpacing(6)

        # Overall Progress Section
        overall_hdr = QHBoxLayout()
        lbl_overall_title = QLabel("TOTAL SETUP PROGRESS")
        lbl_overall_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_overall_title.setStyleSheet("color: #9A9AA6; letter-spacing: 0.5px;")
        overall_hdr.addWidget(lbl_overall_title)
        overall_hdr.addStretch()

        self.lbl_overall_stage = QLabel("Initializing setup...")
        self.lbl_overall_stage.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_overall_stage.setStyleSheet("color: #10B981;")
        overall_hdr.addWidget(self.lbl_overall_stage)
        layout.addLayout(overall_hdr)

        self.pbar_overall = QProgressBar()
        self.pbar_overall.setRange(0, 100)
        self.pbar_overall.setValue(0)
        self.pbar_overall.setFixedHeight(16)
        self.pbar_overall.setTextVisible(True)
        self.pbar_overall.setFormat("%p%")
        self.pbar_overall.setStyleSheet("""
            QProgressBar {
                background-color: #202026;
                border: 1px solid #363642;
                border-radius: 4px;
                text-align: center;
                color: #FFFFFF;
                font-weight: 700;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.pbar_overall)

        self.lbl_overall_stats = QLabel("Preparing components...")
        self.lbl_overall_stats.setStyleSheet("color: #9A9AA6; font-size: 11px; font-family: Consolas, monospace;")
        layout.addWidget(self.lbl_overall_stats)

        layout.addSpacing(4)

        # Current Task Section
        current_hdr = QHBoxLayout()
        lbl_current_title = QLabel("CURRENT TASK")
        lbl_current_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_current_title.setStyleSheet("color: #9A9AA6; letter-spacing: 0.5px;")
        current_hdr.addWidget(lbl_current_title)
        current_hdr.addStretch()

        self.lbl_current_task = QLabel("Starting worker...")
        self.lbl_current_task.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_current_task.setStyleSheet("color: #38BDF8;")
        current_hdr.addWidget(self.lbl_current_task)
        layout.addLayout(current_hdr)

        self.pbar_current = QProgressBar()
        self.pbar_current.setRange(0, 100)
        self.pbar_current.setValue(0)
        self.pbar_current.setFixedHeight(16)
        self.pbar_current.setTextVisible(True)
        self.pbar_current.setFormat("%p%")
        self.pbar_current.setStyleSheet("""
            QProgressBar {
                background-color: #202026;
                border: 1px solid #363642;
                border-radius: 4px;
                text-align: center;
                color: #FFFFFF;
                font-weight: 700;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.pbar_current)

        self.lbl_current_stats = QLabel("Waiting...")
        self.lbl_current_stats.setStyleSheet("color: #9A9AA6; font-size: 11px; font-family: Consolas, monospace;")
        layout.addWidget(self.lbl_current_stats)

        layout.addSpacing(4)

        # Console Log
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(105)
        self.log_view.setStyleSheet("""
            background-color: #101014;
            border: 1px solid #262630;
            border-radius: 5px;
            font-family: Consolas, monospace;
            font-size: 10px;
            color: #C8C8D4;
        """)
        layout.addWidget(self.log_view)

        # Button Row
        btn_row = QHBoxLayout()
        self.btn_locate = QPushButton("Locate Existing Engine Folder...")
        self.btn_locate.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #363642;
                color: #9A9AA6;
                border-radius: 5px;
                padding: 6px 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                color: #FFFFFF;
                border-color: #4F4F5E;
                background-color: #1E1E26;
            }
        """)
        self.btn_locate.clicked.connect(self._on_locate_engine)
        btn_row.addWidget(self.btn_locate)

        btn_row.addStretch()

        self.btn_action = QPushButton("Cancel")
        self.btn_action.setStyleSheet("""
            QPushButton {
                background-color: #24242C;
                color: #FFFFFF;
                border: 1px solid #3A3A46;
                border-radius: 5px;
                padding: 6px 18px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #30303A;
            }
        """)
        self.btn_action.clicked.connect(self._on_action_clicked)
        btn_row.addWidget(self.btn_action)

        layout.addLayout(btn_row)

    def _start_worker(self):
        self.worker = UnifiedSetupWorker(parent=self)
        self.worker.stage_started.connect(self._on_stage_started)
        self.worker.stage_progress.connect(self._on_stage_progress)
        self.worker.overall_progress.connect(self._on_overall_progress)
        self.worker.log_received.connect(self._on_log)
        self.worker.setup_finished.connect(self._on_finished)
        self.worker.start()

    def _on_stage_started(self, stage: str):
        st = stage.lower()
        if st == "engine":
            self.row_engine.set_status("running")
        elif st == "ffmpeg":
            self.row_engine.set_status("ready")
            self.row_ffmpeg.set_status("running")
        elif st == "weights":
            self.row_engine.set_status("ready")
            self.row_ffmpeg.set_status("ready")
            self.row_weights.set_status("running")

    def _on_stage_progress(self, pct: float, task_name: str, speed_eta: str):
        self.pbar_current.setValue(int(pct))
        if task_name:
            self.lbl_current_task.setText(task_name)
        if speed_eta:
            self.lbl_current_stats.setText(speed_eta)

    def _on_overall_progress(self, pct: float, stage_title: str, size_stats: str):
        self.pbar_overall.setValue(int(pct))
        if stage_title:
            self.lbl_overall_stage.setText(stage_title)
        if size_stats:
            self.lbl_overall_stats.setText(size_stats)

    def _on_log(self, text: str):
        self.log_view.append(text)

    def _on_finished(self, success: bool, message: str):
        self._is_completed = success
        self.btn_locate.setVisible(False)
        self.pbar_current.setValue(100 if success else 0)

        if success:
            self.pbar_overall.setValue(100)
            self.row_engine.set_status("ready")
            self.row_ffmpeg.set_status("ready")
            self.row_weights.set_status("ready")
            self.lbl_overall_stage.setText("All Components Ready!")
            self.lbl_overall_stage.setStyleSheet("color: #10B981;")
            self.lbl_current_task.setText("Setup Complete!")
            self.lbl_current_task.setStyleSheet("color: #10B981;")
            self.lbl_overall_stats.setText("5.18 GB / 5.18 GB (100%)")
            self.lbl_current_stats.setText("Ready to launch Workbench.")

            self.btn_action.setText("Open Workbench")
            QTimer.singleShot(1200, self.accept)
            self.btn_action.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 5px;
                    padding: 7px 22px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
        else:
            self.lbl_overall_stage.setText("Setup Canceled or Incomplete")
            self.lbl_overall_stage.setStyleSheet("color: #EF4444;")
            self.btn_action.setText("Close")
            self.btn_action.setStyleSheet("""
                QPushButton {
                    background-color: #EF4444;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 5px;
                    padding: 7px 22px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #DC2626;
                }
            """)

    def _on_locate_engine(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Existing CorridorKey 2.0 Folder")
        if folder:
            if EngineManager.link_existing_engine(folder):
                self.row_engine.set_status("ready")
                self.log_view.append(f"[Engine] Linked existing CorridorKey engine from: {folder}")
                QMessageBox.information(self, "Engine Linked", f"Successfully linked CorridorKey engine from:\n{folder}")
            else:
                QMessageBox.warning(self, "Invalid Folder", "The selected folder does not contain 'infer.py'. Please select the root CorridorKey 2.0 folder.")

    def _cancel_and_close(self):
        if hasattr(self, 'worker') and self.worker is not None:
            self.worker.stop()
            if self.worker.isRunning():
                if not self.worker.wait(1500):
                    self.worker.terminate()
                    self.worker.wait(500)

    def _on_action_clicked(self):
        if self._is_completed:
            self.accept()
        else:
            self._cancel_and_close()
            self.reject()

    def reject(self):
        if not self._is_completed:
            self._cancel_and_close()
        super().reject()

    def closeEvent(self, event):
        if not self._is_completed:
            self._cancel_and_close()
        event.accept()
