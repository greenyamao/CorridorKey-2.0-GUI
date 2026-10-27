"""Unified Setup Worker for CorridorKey 2.0 Workbench.

Sequentially verifies and installs:
1. CorridorKey 2.0 Engine (upstream core)
2. Portable FFmpeg / FFprobe binaries
3. AI Model Weights (~5.1 GB across 4 models)

Operates in an isolated background QThread with dual-level live progress reporting.
Strict English-only rule compliant.
"""

from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
import zipfile
import urllib.request
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, QThread

from gui.managers.engine_manager import EngineManager
from gui.managers.ffmpeg_manager import FFmpegManager
from gui.managers.weights_manager import WeightsManager, WeightsDownloadWorker

APP_ROOT = Path(__file__).resolve().parent.parent.parent


class UnifiedSetupWorker(QThread):
    """Coordinates automated, zero-prompt setup of Engine, FFmpeg, and Weights."""

    stage_started = Signal(str)  # "engine", "ffmpeg", "weights"
    stage_progress = Signal(float, str, str)  # current_pct, task_name, speed_eta
    overall_progress = Signal(float, str, str)  # overall_pct, stage_title, size_stats
    log_received = Signal(str)  # text line
    setup_finished = Signal(bool, str)  # success, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_stopped = False
        self._active_weights_worker: Optional[WeightsDownloadWorker] = None

    def stop(self):
        """Cleanly terminates any active downloads or child subprocesses."""
        self._is_stopped = True
        if self._active_weights_worker is not None:
            self._active_weights_worker.stop()
        self.log_received.emit("[Setup] Stop signal received. Canceling operation...")

    def run(self):
        self._is_stopped = False
        self.log_received.emit("=== CorridorKey 2.0 Unified Setup Starting ===")

        # ---------------------------------------------------------------------
        # Stage 1: CorridorKey 2.0 Engine Layer (Weight budget: 0% -> 2%)
        # ---------------------------------------------------------------------
        if self._is_stopped:
            self.setup_finished.emit(False, "Setup cancelled by user.")
            return

        self.stage_started.emit("engine")
        if EngineManager.is_engine_installed():
            self.log_received.emit("[Engine] CorridorKey 2.0 engine is already installed.")
            EngineManager.ensure_junctions()
            self.stage_progress.emit(100.0, "CorridorKey 2.0 Engine Ready", "Verified on disk")
            self.overall_progress.emit(2.0, "Stage 1 of 3: Core Engine Ready", "Verified")
        else:
            self.log_received.emit("[Engine] Core engine not found. Downloading CorridorKey 2.0 repository...")
            self.overall_progress.emit(0.5, "Stage 1 of 3: Downloading Engine", "Connecting to GitHub...")
            self.stage_progress.emit(0.0, "Downloading Engine...", "Connecting...")

            def _engine_cb(pct: float, msg: str):
                if self._is_stopped:
                    return
                self.stage_progress.emit(pct, msg, "")
                overall_pct = (pct / 100.0) * 2.0
                self.overall_progress.emit(overall_pct, "Stage 1 of 3: Engine Setup", msg)
                self.log_received.emit(f"[Engine] {msg}")

            success = EngineManager.install_or_update_engine(progress_callback=_engine_cb)
            if self._is_stopped:
                self.setup_finished.emit(False, "Setup cancelled by user.")
                return

            if not success or not EngineManager.is_engine_installed():
                self.log_received.emit("[Error] Failed to install CorridorKey 2.0 engine.")
                self.setup_finished.emit(False, "Failed to download or install CorridorKey 2.0 engine.")
                return

            EngineManager.ensure_junctions()
            self.log_received.emit("[Engine] Core engine installed and linked successfully.")
            self.stage_progress.emit(100.0, "Engine Ready", "Complete")
            self.overall_progress.emit(2.0, "Stage 1 of 3: Engine Complete", "2 MB / ~5.18 GB")

        # ---------------------------------------------------------------------
        # Stage 2: Portable FFmpeg / FFprobe Layer (Weight budget: 2% -> 5%)
        # ---------------------------------------------------------------------
        if self._is_stopped:
            self.setup_finished.emit(False, "Setup cancelled by user.")
            return

        self.stage_started.emit("ffmpeg")
        FFmpegManager.setup_path()
        if FFmpegManager.is_available():
            self.log_received.emit("[FFmpeg] FFmpeg and FFprobe are available and verified.")
            self.stage_progress.emit(100.0, "FFmpeg Ready", "Verified in PATH")
            self.overall_progress.emit(5.0, "Stage 2 of 3: FFmpeg Ready", "Verified")
        else:
            self.log_received.emit("[FFmpeg] Downloading portable FFmpeg binaries (~90 MB)...")
            self.overall_progress.emit(2.5, "Stage 2 of 3: Downloading FFmpeg", "Connecting to mirror...")

            def _ffmpeg_cb(pct: float, msg: str):
                if self._is_stopped:
                    return
                self.stage_progress.emit(pct, "Downloading Portable FFmpeg", msg)
                overall_pct = 2.0 + (pct / 100.0) * 3.0
                self.overall_progress.emit(overall_pct, "Stage 2 of 3: FFmpeg Setup", msg)
                if int(pct) % 25 == 0:
                    self.log_received.emit(f"[FFmpeg] {msg}")

            success = FFmpegManager.download_portable_ffmpeg(progress_callback=_ffmpeg_cb)
            if self._is_stopped:
                self.setup_finished.emit(False, "Setup cancelled by user.")
                return

            if not success or not FFmpegManager.is_available():
                self.log_received.emit("[Error] Failed to download or configure portable FFmpeg.")
                self.setup_finished.emit(False, "Failed to download portable FFmpeg binaries.")
                return

            FFmpegManager.setup_path()
            self.log_received.emit("[FFmpeg] Portable FFmpeg configured successfully in ./bin/.")
            self.stage_progress.emit(100.0, "FFmpeg Ready", "Complete")
            self.overall_progress.emit(5.0, "Stage 2 of 3: FFmpeg Complete", "92 MB / ~5.18 GB")

        # ---------------------------------------------------------------------
        # Stage 3: AI Model Weights & Vision Foundation Models (5% -> 100%)
        # ---------------------------------------------------------------------
        if self._is_stopped:
            self.setup_finished.emit(False, "Setup cancelled by user.")
            return

        self.stage_started.emit("weights")
        if WeightsManager.are_all_weights_present():
            self.log_received.emit("[Weights] All 4 model checkpoints are present and verified.")
            self.stage_progress.emit(100.0, "All Models Ready", "Complete")
            self.overall_progress.emit(100.0, "All Models Ready (4 of 4)", "5.08 GB / 5.08 GB (100%)")
            self.setup_finished.emit(True, "All components and weights are verified and ready.")
            return

        self.log_received.emit("[Weights] Initiating download of deep learning weights (~5.08 GB total)...")

        # Execute weights downloader directly inside this thread to avoid nested threads
        worker = WeightsDownloadWorker()
        self._active_weights_worker = worker

        def _on_weights_line(line: str):
            self.log_received.emit(line)

        def _on_weights_stage(pct: float, stage_info: str, speed_eta: str):
            if self._is_stopped:
                return
            self.stage_progress.emit(pct, stage_info, speed_eta)

        def _on_weights_overall(pct: float, stage_title: str, size_stats: str):
            if self._is_stopped:
                return
            scaled_overall = 5.0 + (pct / 100.0) * 95.0
            self.overall_progress.emit(scaled_overall, f"Stage 3 of 3: {stage_title}", size_stats)

        worker.progress_received.connect(_on_weights_line)
        worker.progress_updated.connect(_on_weights_stage)
        worker.overall_progress_updated.connect(_on_weights_overall)

        # Run weights worker synchronously within this thread
        worker.run()
        self._active_weights_worker = None

        if self._is_stopped:
            self.setup_finished.emit(False, "Setup cancelled by user.")
            return

        if WeightsManager.are_all_weights_present():
            self.overall_progress.emit(100.0, "All Components & Weights Ready", "5.18 GB / 5.18 GB (100%)")
            self.stage_progress.emit(100.0, "Setup Complete", "100%")
            self.log_received.emit("=== Setup Completed Successfully ===")
            self.setup_finished.emit(True, "All components and weights are ready!")
        else:
            self.log_received.emit("[Error] One or more model weights failed to download or verify.")
            self.setup_finished.emit(False, "Failed to download model weights. Please check your network connection.")
