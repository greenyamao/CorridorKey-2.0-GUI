from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QSize, QSettings
from PySide6.QtGui import QIcon, QFont, QColor, QCursor, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
    QLabel,
    QPushButton,
    QComboBox,
    QMessageBox,
    QDialog,
    QProgressBar,
    QTextEdit,
    QFrame,
    QStatusBar,
)
from qfluentwidgets import FluentIcon as FI, Theme, setTheme

from gui.styles.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    CORRIDOR_YELLOW,
    CORRIDOR_GREEN,
    BG_CANVAS,
    CARD_BG,
    BORDER_SUBTLE,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
    DARK_WORKBENCH_QSS,
)
from gui.backend.system_monitor import get_gpu_info, get_disk_free_gb
from gui.backend.video_loader import ClipInfo, VideoReader, probe_clip, scan_directory_for_clips
from gui.backend.render_worker import RenderTask, RenderRunner, WeightDownloader
from gui.managers import FFmpegManager, EngineManager, WeightsManager, AppUpdater
from gui.components.media_panel import MediaPanel
from gui.components.viewport import ViewportWidget
from gui.components.timeline import TimelineWidget
from gui.components.inspector import InspectorPanel


class WeightDownloadDialog(QDialog):
    """Dialog for downloading model weights with overall and per-model live progress bars, speed, and ETA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download CorridorKey 2.0 Weights (~5 GB)")
        self.resize(600, 430)
        self.setStyleSheet("background-color: #16161A; color: #FFFFFF;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        title_lbl = QLabel("CorridorKey 2.0 Model Setup")
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(title_lbl)

        sub_lbl = QLabel("Downloading weights from Hugging Face and foundation models (~4.9 GB total)...")
        sub_lbl.setStyleSheet("color: #D4D4DC; font-size: 11px;")
        layout.addWidget(sub_lbl)

        layout.addSpacing(6)

        # --- Overall Progress Section ---
        overall_hdr = QHBoxLayout()
        overall_title = QLabel("OVERALL PROGRESS")
        overall_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        overall_title.setStyleSheet("color: #9A9AA6; letter-spacing: 0.5px;")
        overall_hdr.addWidget(overall_title)
        overall_hdr.addStretch()

        self.lbl_overall_stage = QLabel("Initializing...")
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

        self.lbl_overall_stats = QLabel("Calculating total size...")
        self.lbl_overall_stats.setStyleSheet("color: #9A9AA6; font-size: 11px; font-family: Consolas, monospace;")
        layout.addWidget(self.lbl_overall_stats)

        layout.addSpacing(6)

        # --- Current Model Section ---
        current_hdr = QHBoxLayout()
        current_title = QLabel("CURRENT MODEL")
        current_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        current_title.setStyleSheet("color: #9A9AA6; letter-spacing: 0.5px;")
        current_hdr.addWidget(current_title)
        current_hdr.addStretch()

        self.lbl_stage = QLabel("Connecting to Hugging Face...")
        self.lbl_stage.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.lbl_stage.setStyleSheet("color: #38BDF8;")
        current_hdr.addWidget(self.lbl_stage)
        layout.addLayout(current_hdr)

        self.pbar = QProgressBar()
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setFixedHeight(16)
        self.pbar.setTextVisible(True)
        self.pbar.setFormat("%p%")
        self.pbar.setStyleSheet("""
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
        layout.addWidget(self.pbar)

        self.lbl_stats = QLabel("Preparing download...")
        self.lbl_stats.setStyleSheet("color: #9A9AA6; font-size: 11px; font-family: Consolas, monospace;")
        layout.addWidget(self.lbl_stats)

        layout.addSpacing(4)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(110)
        self.log_view.setStyleSheet("background-color: #121216; border: 1px solid #282832; border-radius: 5px; font-family: Consolas; font-size: 11px; color: #D4D4DC;")
        layout.addWidget(self.log_view)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_close = QPushButton("Cancel")
        self.btn_close.setProperty("class", "pill-btn")
        self.btn_close.clicked.connect(self._on_close_clicked)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        self.worker = WeightDownloader(parent=self)
        self.worker.progress_received.connect(self._on_progress)
        self.worker.progress_updated.connect(self._on_progress_update)
        self.worker.overall_progress_updated.connect(self._on_overall_progress_update)
        self.worker.download_finished.connect(self._on_finished)
        self.worker.start()

    def _cancel_and_close(self):
        if hasattr(self, 'worker') and self.worker is not None:
            self.worker.stop()
            if self.worker.isRunning():
                if not self.worker.wait(2000):
                    self.worker.terminate()
                    self.worker.wait(1000)

    def _on_close_clicked(self):
        self._cancel_and_close()
        if self.btn_close.text() == "Close":
            self.accept()
        else:
            super().reject()

    def reject(self):
        self._cancel_and_close()
        super().reject()

    def closeEvent(self, event):
        self._cancel_and_close()
        event.accept()

    def _on_progress(self, line: str):
        self.log_view.append(line)

    def _on_progress_update(self, pct: float, stage: str, stats: str):
        self.pbar.setValue(int(pct))
        if stage:
            self.lbl_stage.setText(stage)
        if stats:
            self.lbl_stats.setText(stats)

    def _on_overall_progress_update(self, pct: float, stage_title: str, stats: str):
        self.pbar_overall.setValue(int(pct))
        if stage_title:
            self.lbl_overall_stage.setText(stage_title)
        if stats:
            self.lbl_overall_stats.setText(stats)

    def _on_finished(self, success: bool, msg: str):
        self.pbar.setValue(100 if success else 0)
        self.log_view.append(f"\nStatus: {msg}")
        self.btn_close.setText("Close")
        if success:
            self.pbar_overall.setValue(100)
            self.lbl_overall_stage.setText("All Models Ready (4 of 4)")
            self.lbl_overall_stats.setText("4.88 GB / 4.88 GB (100%)")
            self.lbl_stage.setText("Download Complete!")
            self.lbl_stage.setStyleSheet("color: #10B981;")
            self.btn_close.setStyleSheet("background-color: #10B981; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 16px;")
        else:
            self.lbl_stage.setText("Download Canceled" if "canceled" in msg.lower() else "Download Error")
            self.lbl_stage.setStyleSheet("color: #EF4444;")
            self.btn_close.setStyleSheet("background-color: #EF4444; color: #FFFFFF; font-weight: bold; border-radius: 5px; padding: 6px 16px;")


class MainWindow(QMainWindow):
    """Clean Windows 11 Workbench for CorridorKey 2.0 in English with detailed Russian tooltips."""

    def __init__(self):
        super().__init__()
        setTheme(Theme.DARK)
        self.setWindowTitle("CorridorKey 2.0 Workbench")
        self.resize(1400, 860)
        self.setMinimumSize(1000, 650)
        self.setAcceptDrops(True)

        self.active_reader: Optional[VideoReader] = None
        self.current_clip: Optional[ClipInfo] = None
        self._active_hint_mask: Optional[Any] = None
        self.render_queue: List[RenderTask] = []
        self.queue_items_map: Dict[str, Any] = {}
        self.active_runner: Optional[RenderRunner] = None
        self.rendered_alpha_reader: Optional[VideoReader] = None
        self.rendered_fg_reader: Optional[VideoReader] = None
        self._last_rendered_out_dir: str = ""
        self._current_rendering_path: str = ""
        self._current_task_output_dir: str = ""
        self.session_rendered_clips: set[str] = set()
        self.session_clip_output_dirs: Dict[str, str] = {}

        self._init_ui()
        self._setup_shortcuts()
        self._load_settings()

        # Telemetry timer (update GPU/VRAM and disk stats every 1 second)
        self.sys_timer = QTimer(self)
        self.sys_timer.timeout.connect(self._update_system_stats)
        self.sys_timer.start(1000)
        self._update_system_stats()

        # Check isolated layers asynchronously
        FFmpegManager.setup_path()
        if not FFmpegManager.is_available():
            QTimer.singleShot(1500, self._check_ffmpeg_available)

        if not EngineManager.is_engine_installed():
            QTimer.singleShot(600, self._prompt_engine_install)
        else:
            QTimer.singleShot(2500, self._check_engine_updates_async)

        # Check for GUI application updates
        QTimer.singleShot(3500, self._check_gui_updates_async)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 4)
        main_layout.setSpacing(6)

        # Main 3-Column Splitter (Left: Media, Center: Viewport, Right: Inspector)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {BG_CANVAS}; }}")

        # 1. Left Column: Unified Media & Batch Panel
        self.media_panel = MediaPanel()
        self.media_panel.clip_selected.connect(self._on_clip_selected)
        self.media_panel.render_all_requested.connect(self._on_render_all_clips)
        self.media_panel.stop_batch_requested.connect(self._on_stop_batch)
        self.splitter.addWidget(self.media_panel)

        # 2. Center Column: Viewport & Timeline
        center_card = QFrame()
        center_card.setProperty("class", "flat-card")
        center_card.setStyleSheet("""
            QFrame.flat-card {
                background-color: #16161A;
                border: 1px solid #28282E;
                border-radius: 8px;
            }
        """)
        c_layout = QVBoxLayout(center_card)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)

        # Viewport Header Toolbar
        vp_header = QWidget()
        vp_header.setFixedHeight(38)
        vp_header.setStyleSheet("background-color: #1B1B20; border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 1px solid #28282E;")
        vph_layout = QHBoxLayout(vp_header)
        vph_layout.setContentsMargins(12, 0, 12, 0)
        vph_layout.setSpacing(10)

        lbl_vp_title = QLabel("Viewport")
        lbl_vp_title.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700;")
        lbl_vp_title.setToolTip("<b>Viewport Monitor</b><br>Interactive video monitor with pan, zoom, and interactive wipe split.")
        vph_layout.addWidget(lbl_vp_title)

        vph_layout.addSpacing(10)

        # Display Mode Segmented Buttons
        lbl_mode = QLabel("Mode:")
        lbl_mode.setToolTip("<b>Display Mode</b><br>Switch between Single view, interactive Wipe divider, and Side by Side view.")
        vph_layout.addWidget(lbl_mode)

        self.btn_single = QPushButton("Single")
        self.btn_single.setCheckable(True)
        self.btn_single.setChecked(False)
        self.btn_single.setToolTip("<b>Single Mode</b><br>Full view of the selected channel.")

        self.btn_wipe = QPushButton("Wipe")
        self.btn_wipe.setCheckable(True)
        self.btn_wipe.setChecked(True)
        self.btn_wipe.setToolTip("<b>Wipe Mode</b><br>Interactive split screen: original video on the left, processed key on the right. Drag the vertical divider line.")

        self.btn_sbs = QPushButton("Side by Side")
        self.btn_sbs.setCheckable(True)
        self.btn_sbs.setToolTip("<b>Side by Side Mode</b><br>Displays original footage and keyed subject side by side.")

        seg_style = f"""
            QPushButton {{
                background-color: #222228;
                border: 1px solid #32323A;
                border-radius: 4px;
                color: #CCCCCC;
                padding: 3px 8px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #2A2A32;
                border-color: #40404C;
            }}
            QPushButton:checked {{
                background-color: {ACCENT_BLUE};
                color: #FFFFFF;
                font-weight: 700;
                border-color: {ACCENT_BLUE};
            }}
        """
        for b in (self.btn_single, self.btn_wipe, self.btn_sbs):
            b.setStyleSheet(seg_style)
            vph_layout.addWidget(b)

        self.btn_single.clicked.connect(lambda: self._set_disp_mode("Single"))
        self.btn_wipe.clicked.connect(lambda: self._set_disp_mode("Wipe"))
        self.btn_sbs.clicked.connect(lambda: self._set_disp_mode("Side by side"))

        vph_layout.addSpacing(10)

        # Channel Selector
        lbl_channel = QLabel("Channel:")
        tip_channel = (
            "<b>Channel Mode</b><br>"
            "&bull; <b>Composite</b>: keyed subject over transparency checkerboard.<br>"
            "&bull; <b>Alpha</b>: black & white matte (white is opaque, black is transparent).<br>"
            "&bull; <b>Foreground</b>: despilled RGB foreground.<br>"
            "&bull; <b>Original</b>: raw source video frame."
        )
        lbl_channel.setToolTip(tip_channel)
        vph_layout.addWidget(lbl_channel)

        self.cmb_channel = QComboBox()
        self.cmb_channel.addItems(["Composite (Checker)", "Alpha (Matte)", "Foreground (Cutout)", "Original (Source)"])
        self.cmb_channel.setToolTip(tip_channel)
        self.cmb_channel.currentIndexChanged.connect(self._on_channel_changed)
        vph_layout.addWidget(self.cmb_channel)

        vph_layout.addStretch()

        btn_fit = QPushButton("Fit 100%")
        btn_fit.setProperty("class", "pill-btn")
        btn_fit.setToolTip("<b>Fit 100%</b><br>Reset zoom and fit the video frame to the viewport window (also double click Left Button in viewport).")
        btn_fit.clicked.connect(lambda: self.viewport.reset_view())
        vph_layout.addWidget(btn_fit)

        c_layout.addWidget(vp_header)

        # Viewport Canvas
        self.viewport = ViewportWidget()
        c_layout.addWidget(self.viewport, stretch=1)

        # Timeline Scrubber Bar
        self.timeline = TimelineWidget()
        self.timeline.frame_changed.connect(self._on_timeline_frame_changed)
        c_layout.addWidget(self.timeline)

        self.splitter.addWidget(center_card)

        # 3. Right Column: Inspector Panel
        self.inspector = InspectorPanel()
        self.inspector.render_requested.connect(self._on_render_active_clip)
        self.inspector.download_weights_requested.connect(self._open_weight_downloader)
        self.inspector.hint_changed.connect(self._on_hint_changed)
        self.inspector.paint_mask_requested.connect(self._open_mask_painter)
        self.inspector.despill_changed.connect(self._on_despill_changed)
        self.inspector.despill_color_changed.connect(self._on_despill_color_changed)
        self.splitter.addWidget(self.inspector)

        self.splitter.setSizes([260, 760, 380])
        main_layout.addWidget(self.splitter, stretch=1)

        # Native Minimal Status Bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setFixedHeight(24)
        self.status_bar.setStyleSheet("""
            QStatusBar {
                background-color: #121214;
                color: #8E8E93;
                border-top: 1px solid #202024;
                font-size: 11px;
                padding-left: 6px;
                padding-right: 6px;
            }
            QStatusBar::item {
                border: none;
            }
        """)
        self.setStatusBar(self.status_bar)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet(f"color: {CORRIDOR_GREEN}; font-size: 11px; font-weight: 600;")
        self.lbl_status.setToolTip("<b>System Status</b><br>Current status of the CorridorKey inference engine.")
        self.status_bar.addWidget(self.lbl_status, stretch=1)

        self.lbl_vram_status = QLabel("VRAM: 0.0 / 8.0 GB")
        self.lbl_vram_status.setStyleSheet("color: #CCCCCC; font-size: 11px; font-family: Consolas, monospace; padding-right: 12px;")
        self.lbl_vram_status.setToolTip("<b>GPU VRAM Usage</b><br>Currently allocated and total video memory on your GPU.")
        self.status_bar.addPermanentWidget(self.lbl_vram_status)

        self.lbl_disk_status = QLabel("Disk: 0.0 GB Free")
        self.lbl_disk_status.setStyleSheet("color: #CCCCCC; font-size: 11px; font-family: Consolas, monospace;")
        self.lbl_disk_status.setToolTip("<b>Disk Space</b><br>Free disk space available on the target render drive.")
        self.status_bar.addPermanentWidget(self.lbl_disk_status)

        self.btn_engine_update = QPushButton("Update Engine")
        self.btn_engine_update.setIcon(FI.SYNC.icon(color=QColor("#FFFFFF")))
        self.btn_engine_update.setIconSize(QSize(11, 11))
        self.btn_engine_update.setVisible(False)
        self.btn_engine_update.setFixedHeight(18)
        self.btn_engine_update.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_engine_update.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid #3B82F6;
                border-radius: 3px;
                padding: 1px 6px;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        self.btn_engine_update.clicked.connect(self._on_update_engine)
        self.status_bar.addPermanentWidget(self.btn_engine_update)

        self.btn_gui_update = QPushButton("Update GUI")
        self.btn_gui_update.setIcon(FI.SYNC.icon(color=QColor("#FFFFFF")))
        self.btn_gui_update.setIconSize(QSize(11, 11))
        self.btn_gui_update.setVisible(False)
        self.btn_gui_update.setFixedHeight(18)
        self.btn_gui_update.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_gui_update.setStyleSheet("""
            QPushButton {
                background-color: #059669;
                color: #FFFFFF;
                font-size: 10px;
                font-weight: 700;
                border: 1px solid #10B981;
                border-radius: 3px;
                padding: 1px 6px;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        self.btn_gui_update.clicked.connect(self._on_update_gui)
        self.status_bar.addPermanentWidget(self.btn_gui_update)

    def _check_ffmpeg_available(self):
        if not FFmpegManager.is_available():
            reply = QMessageBox.question(
                self,
                "FFmpeg Missing",
                "FFmpeg was not found in your system PATH.\n\n"
                "Would you like to automatically download portable FFmpeg binaries into ./bin/?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.lbl_status.setText("Downloading portable FFmpeg...")
                success = FFmpegManager.download_portable_ffmpeg()
                if success:
                    QMessageBox.information(self, "FFmpeg Installed", "Portable FFmpeg installed into ./bin/ successfully!")
                    self.lbl_status.setText("Ready")
                else:
                    QMessageBox.warning(self, "FFmpeg Error", "Failed to download FFmpeg automatically. Please install FFmpeg manually.")

    def _prompt_engine_install(self):
        if not EngineManager.is_engine_installed():
            msg = QMessageBox(self)
            msg.setWindowTitle("CorridorKey 2.0 Engine Setup")
            msg.setText("The core CorridorKey 2.0 engine was not found in ./engine/.")
            msg.setInformativeText("Would you like to download it from GitHub, or locate an existing CorridorKey folder on your disk?")
            btn_download = msg.addButton("Download from GitHub", QMessageBox.ButtonRole.AcceptRole)
            btn_locate = msg.addButton("Locate Existing Folder...", QMessageBox.ButtonRole.ActionRole)
            btn_cancel = msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() == btn_download:
                self.lbl_status.setText("Installing CorridorKey engine...")
                success = EngineManager.install_or_update_engine()
                if success:
                    QMessageBox.information(self, "Engine Installed", "CorridorKey 2.0 engine installed successfully!")
                    self.lbl_status.setText("Ready")
                else:
                    QMessageBox.warning(self, "Installation Failed", "Could not install engine. Check your network connection.")
            elif msg.clickedButton() == btn_locate:
                folder = QFileDialog.getExistingDirectory(self, "Select Existing CorridorKey 2.0 Folder")
                if folder:
                    if EngineManager.link_existing_engine(folder):
                        QMessageBox.information(self, "Engine Linked", f"Successfully linked CorridorKey engine from:\n{folder}")
                        self.lbl_status.setText("Ready")
                    else:
                        QMessageBox.warning(self, "Invalid Folder", "The selected folder does not contain 'infer.py'. Please select the root CorridorKey 2.0 repository folder.")

    def _check_engine_updates_async(self):
        def _bg():
            try:
                info = EngineManager.check_for_updates()
                if info:
                    QTimer.singleShot(0, lambda: self._on_engine_update_found(info[0], info[1]))
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def _on_engine_update_found(self, commit_hash: str, msg: str):
        self.btn_engine_update.setText(f"Update Engine ({commit_hash})")
        self.btn_engine_update.setToolTip(f"New CorridorKey commit: {commit_hash}\n{msg}\nClick to pull update.")
        self.btn_engine_update.setVisible(True)

    def _on_update_engine(self):
        reply = QMessageBox.question(
            self,
            "Update CorridorKey Engine",
            "A newer commit of CorridorKey 2.0 is available on GitHub.\nWould you like to pull the latest changes into ./engine/?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.lbl_status.setText("Updating engine...")
            success = EngineManager.install_or_update_engine()
            if success:
                QMessageBox.information(self, "Engine Updated", "CorridorKey 2.0 engine has been updated successfully!")
                self.btn_engine_update.setVisible(False)
                self.lbl_status.setText("Ready")
            else:
                QMessageBox.warning(self, "Update Failed", "Could not update engine automatically. Check your git configuration or network.")

    def _check_gui_updates_async(self):
        def _bg():
            try:
                info = AppUpdater.check_for_update()
                if info:
                    QTimer.singleShot(0, lambda: self._on_gui_update_found(info[0], info[1]))
            except Exception:
                pass
        import threading
        threading.Thread(target=_bg, daemon=True).start()

    def _on_gui_update_found(self, short_sha: str, msg: str):
        self.btn_gui_update.setText(f"Update GUI ({short_sha})")
        self.btn_gui_update.setToolTip(f"New GUI version available on GitHub ({short_sha}):\n{msg}\nClick to update and restart.")
        self.btn_gui_update.setVisible(True)

    def _on_update_gui(self):
        reply = QMessageBox.question(
            self,
            "Update CorridorKey Workbench GUI",
            "A newer version of the GUI is available on GitHub.\nWould you like to pull the update and restart?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.lbl_status.setText("Updating GUI...")
            success = AppUpdater.update_gui()
            if success:
                QMessageBox.information(self, "Update Complete", "GUI updated successfully! The application will now restart.")
                AppUpdater.restart_application()
            else:
                QMessageBox.warning(self, "Update Failed", "Could not complete GUI update automatically. Check network or git.")
                self.lbl_status.setText("Ready")

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.timeline.toggle_play)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self.timeline.prev_frame)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self.timeline.next_frame)
        QShortcut(QKeySequence(Qt.Key.Key_Home), self, self.timeline.go_to_first)
        QShortcut(QKeySequence(Qt.Key.Key_End), self, self.timeline.go_to_last)
        QShortcut(QKeySequence.StandardKey.Open, self, self.media_panel._on_import_file)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self.media_panel._on_import_folder)
        QShortcut(QKeySequence("Ctrl+R"), self, self._on_shortcut_render)

    def _on_shortcut_render(self):
        task = self.inspector.get_render_task()
        if task:
            self._start_render(task)
        else:
            QMessageBox.warning(self, "No Clip Selected", "Please import or select a clip to render.")

    def _set_disp_mode(self, mode: str):
        self.btn_single.setChecked(mode == "Single")
        self.btn_wipe.setChecked(mode == "Wipe")
        self.btn_sbs.setChecked(mode == "Side by side")
        self.viewport.set_display_mode(mode)

    def _on_channel_changed(self, idx: int):
        channels = ["Composite", "Alpha", "Foreground", "Original"]
        self.viewport.set_channel_mode(channels[idx])

    def _check_and_load_rendered_outputs(self, clip: Optional[ClipInfo], specific_dir: Optional[str] = None) -> bool:
        """Checks if rendered alpha/foreground videos exist for this clip, and loads them for live preview."""
        if clip is None:
            return False

        stem = Path(clip.path).stem
        base_out = Path(self.inspector.output_dir)

        possible_dirs: List[Path] = []
        if specific_dir and os.path.isdir(specific_dir):
            possible_dirs.append(Path(specific_dir))

        # Check structured set_XX subdirectories (sorted latest first)
        clip_base = base_out / stem
        if clip_base.is_dir():
            set_dirs = sorted([d for d in clip_base.iterdir() if d.is_dir() and d.name.startswith("set_")], reverse=True)
            possible_dirs.extend(set_dirs)
            possible_dirs.append(clip_base)

        # Legacy directories fallback
        possible_dirs.extend([
            base_out / f"out_{stem}",
            base_out,
            Path.home() / "Videos" / "CorridorKey_Renders" / f"out_{stem}",
            Path.home() / "Videos" / "CorridorKey_Renders",
        ])

        found_alpha: Optional[Path] = None
        found_fg: Optional[Path] = None
        target_dir: Optional[Path] = None

        for d in possible_dirs:
            if not d.is_dir():
                continue
            cutout_candidates = list(d.glob(f"{stem}_cutout.*")) or list(d.glob("*_cutout.*"))
            alpha_candidates = list(d.glob(f"{stem}_alpha.*")) or list(d.glob("*_alpha.*"))
            checker_candidates = list(d.glob(f"{stem}_checker*.*")) or list(d.glob("*_checker*.*"))
            fg_candidates = list(d.glob(f"{stem}_fg.*")) or list(d.glob("*_fg.*"))

            if cutout_candidates or alpha_candidates or checker_candidates or fg_candidates:
                target_dir = d
                if alpha_candidates:
                    found_alpha = alpha_candidates[0]
                if cutout_candidates:
                    found_fg = cutout_candidates[0]
                elif checker_candidates:
                    found_fg = checker_candidates[0]
                elif fg_candidates:
                    found_fg = fg_candidates[0]
                break

        loaded_any = False
        if found_alpha and found_alpha.is_file():
            if self.rendered_alpha_reader is not None:
                self.rendered_alpha_reader.close()
            self.rendered_alpha_reader = VideoReader(probe_clip(str(found_alpha)))
            self.rendered_alpha_reader.open()
            loaded_any = True

        if found_fg and found_fg.is_file():
            if self.rendered_fg_reader is not None:
                self.rendered_fg_reader.close()
            self.rendered_fg_reader = VideoReader(probe_clip(str(found_fg)))
            self.rendered_fg_reader.open()
            loaded_any = True

        if loaded_any:
            self._last_rendered_out_dir = str(target_dir) if target_dir else ""
            self.media_panel.set_clip_status(clip.path, "Done")
            return True

        return False

    def _display_current_frame(self):
        if self.active_reader is None:
            return
        frame_idx = self.timeline.current_frame
        orig_rgb = self.active_reader.get_frame(frame_idx)
        if orig_rgb is None:
            return

        alpha_matte = None
        fg_rgb = orig_rgb

        # If we have a rendered foreground reader (such as cutout.mov):
        if self.rendered_fg_reader is not None:
            if self.rendered_fg_reader.clip.path.lower().endswith(".mov"):
                rgba = self.rendered_fg_reader.get_rgba_frame(frame_idx)
                if rgba is not None:
                    fg_rgb = rgba[:, :, :3]
                    alpha_matte = rgba[:, :, 3]
            else:
                f_frame = self.rendered_fg_reader.get_frame(frame_idx)
                if f_frame is not None:
                    fg_rgb = f_frame

        if alpha_matte is None and self.rendered_alpha_reader is not None:
            a_frame = self.rendered_alpha_reader.get_frame(frame_idx)
            if a_frame is not None:
                alpha_matte = a_frame[:, :, 0] if a_frame.ndim == 3 else a_frame
        elif alpha_matte is None and self._active_hint_mask is not None:
            alpha_matte = self._active_hint_mask

        self.viewport.set_frames(rgb_frame=fg_rgb, alpha_matte=alpha_matte, original_rgb=orig_rgb)

    def _release_rendered_readers(self):
        if self.rendered_alpha_reader is not None:
            self.rendered_alpha_reader.close()
            self.rendered_alpha_reader = None
        if self.rendered_fg_reader is not None:
            self.rendered_fg_reader.close()
            self.rendered_fg_reader = None

    def _on_clip_selected(self, clip: ClipInfo):
        self.current_clip = clip

        if self.active_reader is not None:
            self.active_reader.close()
        self._release_rendered_readers()

        self.active_reader = VideoReader(clip)
        self.active_reader.open()

        self.timeline.set_clip(clip.total_frames, clip.fps)
        self.inspector.set_clip(clip)

        # Load companion hint mask once and cache in memory for zero-lag playback
        self._active_hint_mask = None
        if clip.discovered_hint_path and os.path.exists(clip.discovered_hint_path):
            ext = Path(clip.discovered_hint_path).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".exr"}:
                import cv2
                self._active_hint_mask = cv2.imread(clip.discovered_hint_path, cv2.IMREAD_GRAYSCALE)

        # Only load rendered outputs if this clip was actually rendered during this session!
        if clip.path in self.session_rendered_clips:
            specific_dir = self.session_clip_output_dirs.get(clip.path)
            self._check_and_load_rendered_outputs(clip, specific_dir=specific_dir)
        else:
            self.media_panel.set_clip_status(clip.path, "Ready")

        self._display_current_frame()
        self.viewport.reset_view()

    def _on_timeline_frame_changed(self, frame_idx: int):
        self._display_current_frame()

    def _open_mask_painter(self):
        if not self.active_clip or not self.active_reader:
            QMessageBox.information(
                self,
                "No Clip Loaded",
                "Please import or select a video clip to paint a mask.",
            )
            return

        frame_0 = self.active_reader.get_frame(0)
        if frame_0 is None:
            QMessageBox.warning(
                self,
                "Frame Error",
                "Could not decode the first frame of the active clip.",
            )
            return

        from gui.components.mask_painter import MaskPainterDialog

        dlg = MaskPainterDialog(
            frame_rgb=frame_0,
            clip_path=self.active_clip.path,
            initial_mask_path=self.inspector.hint_file_path or None,
            parent=self,
        )
        if dlg.exec():
            saved_path = dlg.saved_mask_path
            if saved_path:
                self.inspector.set_painted_mask(saved_path)
                self.active_clip.discovered_hint_path = saved_path
                self.active_clip.discovered_hint_mode = "first_frame"
                self.media_panel.update_clip_hint(self.active_clip.path, saved_path)
                self._on_hint_changed(saved_path)

    def _on_hint_changed(self, hint_path: str):
        self._active_hint_mask = None
        if hint_path and os.path.exists(hint_path):
            ext = Path(hint_path).suffix.lower()
            if ext in {".png", ".jpg", ".jpeg", ".exr"}:
                import cv2
                self._active_hint_mask = cv2.imread(hint_path, cv2.IMREAD_GRAYSCALE)
        self._display_current_frame()

    def _on_despill_changed(self, strength: float):
        self.viewport.set_despill_strength(strength)
        self._display_current_frame()

    def _on_despill_color_changed(self, color: str):
        self.viewport.set_despill_color(color)
        self._display_current_frame()

    def _update_system_stats(self):
        gpu = get_gpu_info()
        disk_gb = get_disk_free_gb()
        if gpu.get("available"):
            used = gpu.get("used_gb", 0.0)
            total = gpu.get("total_gb", 8.0)
            util = gpu.get("gpu_util", 0)
            pct = int((used / max(0.1, total)) * 100)
            self.lbl_vram_status.setText(f"GPU: {util}% | VRAM: {used:.1f} / {total:.1f} GB ({pct}%)")
        else:
            self.lbl_vram_status.setText("CPU Only")

        self.lbl_disk_status.setText(f"Disk: {disk_gb:.1f} GB Free")

    def _open_weight_downloader(self):
        dlg = WeightDownloadDialog(self)
        dlg.exec()
        self.inspector._check_weights_exist()

    def _on_render_active_clip(self, task: RenderTask):
        if self.active_runner is not None:
            QMessageBox.warning(self, "Render Busy", "Another render process is already active.")
            return
        self.render_queue = [task]
        self._process_next_in_queue()

    def _on_render_all_clips(self):
        if not self.media_panel.clips:
            return
        if self.active_runner is not None:
            QMessageBox.warning(self, "Render Busy", "Another render process is already active.")
            return

        self.render_queue.clear()
        for clip in self.media_panel.clips:
            task = self.inspector.get_render_task(clip)
            if task:
                self.render_queue.append(task)
                self.media_panel.set_clip_status(clip.path, "Queued")

        if self.render_queue:
            self.media_panel.set_batch_running(True)
            self._process_next_in_queue()

    def _on_stop_batch(self):
        self.render_queue.clear()
        if self.active_runner is not None:
            self.active_runner.cancel()
            if self.active_runner.isRunning():
                self.active_runner.wait(500)
        self.media_panel.set_batch_running(False)
        self.lbl_status.setText("Batch Stopped")

    def _process_next_in_queue(self):
        if self.active_runner is not None:
            return
        if not self.render_queue:
            self.media_panel.set_batch_running(False)
            self.lbl_status.setText("All tasks completed")
            return

        next_task = self.render_queue.pop(0)
        self._start_render(next_task)

    def _start_render(self, task: RenderTask):
        self._current_rendering_path = task.clip_path
        self._current_task_output_dir = task.output_dir

        # Release existing reader handles before rendering to allow clean file replacement
        if self.current_clip and self.current_clip.path == task.clip_path:
            self._release_rendered_readers()

        self.media_panel.set_clip_status(task.clip_path, "Rendering", 0.0)
        self.lbl_status.setText(f"Rendering: {task.clip_name}")
        self.lbl_status.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: 600;")

        self.inspector.btn_render.setEnabled(False)

        self.active_runner = RenderRunner(task, parent=self)
        self.active_runner.progress_changed.connect(self._on_render_progress)
        self.active_runner.finished_signal.connect(self._on_render_finished)
        self.active_runner.start()

    def _on_render_progress(self, task_id: str, cur: int, tot: int, pct: float, status: str):
        if self._current_rendering_path:
            self.media_panel.set_clip_status(self._current_rendering_path, "Rendering", pct)
        self.lbl_status.setText(status)

    def _on_render_finished(self, task_id: str, success: bool, msg: str):
        self.inspector.btn_render.setEnabled(True)
        clip_path = self._current_rendering_path
        if clip_path:
            self.media_panel.set_clip_status(clip_path, "Done" if success else "Error")

        task_out = getattr(self, '_current_task_output_dir', "") or getattr(self, '_last_rendered_out_dir', "")
        if not task_out and clip_path:
            task_out = str(Path(self.inspector.output_dir) / Path(clip_path).stem)

        if success:
            clip_name = Path(clip_path).name if clip_path else "Task"
            if clip_path:
                self.session_rendered_clips.add(clip_path)
                self.session_clip_output_dirs[clip_path] = task_out

            self.lbl_status.setText(f"Done: {clip_name}")
            self.lbl_status.setStyleSheet(f"color: {CORRIDOR_GREEN}; font-size: 11px; font-weight: 600;")

            # Play gentle audio notification chime if enabled
            if hasattr(self.inspector, 'chk_sound_on_finish') and self.inspector.chk_sound_on_finish.isChecked():
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except Exception:
                    pass

            # Automatically bind rendered output and update the Viewport with transparent background!
            if self.current_clip and self.current_clip.path == clip_path:
                self._check_and_load_rendered_outputs(self.current_clip, specific_dir=task_out)
                self._display_current_frame()

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Rendering Complete")
            msg_box.setText(f"Rendering finished successfully for:\n{clip_name}")
            msg_box.setInformativeText(f"Saved to folder:\n{task_out}\n\nProcessed transparency preview is now active in the Viewport.")
            btn_open = msg_box.addButton("Open Output Folder", QMessageBox.ButtonRole.ActionRole)
            btn_ok = msg_box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            msg_box.exec()
            if msg_box.clickedButton() == btn_open and task_out and os.path.exists(task_out):
                try:
                    os.startfile(task_out)
                except Exception as e:
                    print(f"[MainWindow] Could not open folder: {e}")
        else:
            self.lbl_status.setText(f"Error: {msg}")
            self.lbl_status.setStyleSheet("color: #FF5252; font-size: 11px; font-weight: 600;")

        if self.active_runner is not None and self.active_runner.isRunning():
            self.active_runner.wait(500)
        self.active_runner = None

        if self.render_queue:
            self._process_next_in_queue()
        else:
            self.media_panel.set_batch_running(False)

    def _save_settings(self):
        settings = QSettings("CorridorKey", "Workbench")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("window_state", self.saveState())
        if hasattr(self, "splitter"):
            settings.setValue("splitter_state", self.splitter.saveState())
        if hasattr(self, "btn_wipe"):
            disp_mode = "Wipe"
            if self.btn_single.isChecked():
                disp_mode = "Single"
            elif self.btn_sbs.isChecked():
                disp_mode = "Side by side"
            settings.setValue("viewport_mode", disp_mode)
        if hasattr(self, "cmb_channel"):
            settings.setValue("viewport_channel", self.cmb_channel.currentIndex())
        if hasattr(self, "inspector"):
            self.inspector.save_settings(settings)

    def _load_settings(self):
        settings = QSettings("CorridorKey", "Workbench")
        geom = settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = settings.value("window_state")
        if state:
            self.restoreState(state)
        splitter_state = settings.value("splitter_state")
        if splitter_state and hasattr(self, "splitter"):
            self.splitter.restoreState(splitter_state)
        if hasattr(self, "btn_wipe"):
            disp_mode = str(settings.value("viewport_mode", "Wipe"))
            self._set_disp_mode(disp_mode)
        if hasattr(self, "cmb_channel") and settings.contains("viewport_channel"):
            self.cmb_channel.setCurrentIndex(int(settings.value("viewport_channel", 0)))
        if hasattr(self, "inspector"):
            self.inspector.load_settings(settings)
        if hasattr(self, "viewport") and hasattr(self, "inspector"):
            self.viewport.set_despill_color(self.inspector.cmb_despill_color.currentText())
            self.viewport.set_despill_strength(self.inspector.slider_despill.value() / 100.0)

    def closeEvent(self, event):
        self._save_settings()
        if self.active_runner is not None and self.active_runner.isRunning():
            self.active_runner.cancel()
            self.active_runner.wait(1000)
        if self.active_reader is not None:
            self.active_reader.close()
        self._release_rendered_readers()
        event.accept()

    # Drag and Drop support
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            fpath = url.toLocalFile()
            if fpath:
                if os.path.isdir(fpath):
                    single = probe_clip(fpath)
                    if single and single.is_frame_dir:
                        self.media_panel.add_clip(fpath)
                    else:
                        found = scan_directory_for_clips(fpath)
                        if found:
                            self.media_panel.add_clips_batch(found)
                        elif single:
                            self.media_panel.add_clip(fpath)
                else:
                    self.media_panel.add_clip(fpath)
        event.acceptProposedAction()


def main():
    try:
        from gui.backend.logger import setup_logging
        setup_logging()
    except Exception as e:
        print(f"[Warning] Could not initialize logger: {e}")

    setTheme(Theme.DARK)
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_WORKBENCH_QSS)

    window = MainWindow()
    window.show()

    return app.exec()
