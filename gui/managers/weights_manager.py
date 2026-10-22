"""Model Weights and Foundation Models Manager.

Manages downloading, integrity checking, partial resumption, and skipping of already downloaded models.
Ensures zero redundant downloads and real-time streaming progress telemetry.
"""

from __future__ import annotations

import os
import sys
import re
import base64
import hashlib
import shutil
import subprocess
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Tuple, List
from PySide6.QtCore import QObject, Signal, QThread

APP_ROOT = Path(__file__).resolve().parent.parent.parent
WEIGHTS_DIR = APP_ROOT / "weights"
VFMS_DIR = APP_ROOT / "vfms"

RVM_FILE = "pretrain_rvm_small16_256_204031069.npz"
RVM_MD5_B64 = "ZJb6kj8+tasiJbVeplXu7Q=="


def _md5_b64(path: Path) -> str:
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode()


class WeightsManager:
    """Checks and manages model assets stored in ./weights/ and ./vfms/."""

    @staticmethod
    def get_weights_dir() -> Path:
        return WEIGHTS_DIR

    @staticmethod
    def get_vfms_dir() -> Path:
        return VFMS_DIR

    @classmethod
    def get_status(cls) -> Dict[str, bool]:
        """Returns the presence status of each required model file."""
        ck_main = (WEIGHTS_DIR / "corridorkey_v2.safetensors").is_file() and (WEIGHTS_DIR / "corridorkey_v2.safetensors").stat().st_size > 100_000_000
        ck_stats = (WEIGHTS_DIR / "foundation_stats.safetensors").is_file()
        
        # C-RADIO check
        cradio = (VFMS_DIR / "cradio" / "C-RADIOv4-SO400M" / "model.safetensors").is_file()
        
        # MoGe check
        moge = (VFMS_DIR / "moge" / "model.pt").is_file() and (VFMS_DIR / "moge" / "model.pt").stat().st_size > 50_000_000
        
        # RVM check
        rvm_path = VFMS_DIR / "rvm" / RVM_FILE
        rvm = rvm_path.is_file() and rvm_path.stat().st_size > 1_000_000

        return {
            "corridorkey": ck_main and ck_stats,
            "cradio": cradio,
            "moge": moge,
            "rvm": rvm,
        }

    @classmethod
    def are_all_weights_present(cls) -> bool:
        status = cls.get_status()
        return all(status.values())

    @classmethod
    def clean_stale_locks(cls) -> None:
        """Removes stale .lock files from huggingface download cache."""
        lock_dirs = [
            WEIGHTS_DIR / ".cache" / "huggingface" / "download",
            VFMS_DIR / "cradio" / ".cache" / "huggingface" / "download",
            VFMS_DIR / "moge" / ".cache" / "huggingface" / "download",
        ]
        for ld in lock_dirs:
            if ld.exists():
                for lock_file in ld.glob("*.lock"):
                    try:
                        lock_file.unlink()
                    except Exception:
                        pass
                for inc_file in ld.glob("*.incomplete"):
                    if inc_file.stat().st_size == 0:
                        try:
                            inc_file.unlink()
                        except Exception:
                            pass


class WeightsDownloadWorker(QThread):
    """
    Background worker that runs the download script with resume support,
    skipping completed files and emitting live telemetry for both current
    model and overall batch progress.
    """
    progress_received = Signal(str)
    progress_updated = Signal(float, str, str)  # current_pct, stage_info, speed_eta
    overall_progress_updated = Signal(float, str, str)  # overall_pct (0-100), stage_title, size_stats
    download_finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[subprocess.Popen] = None
        self._is_stopped: bool = False

    def stop(self):
        self._is_stopped = True
        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass
            try:
                if self._process.stdout:
                    self._process.stdout.close()
            except Exception:
                pass
            try:
                self._process.wait(timeout=0.5)
            except Exception:
                pass

    def run(self):
        self._is_stopped = False
        WeightsManager.clean_stale_locks()

        # Target script: engine/scripts/download_weights.py or generated resilient runner
        from gui.managers.engine_manager import EngineManager
        engine_dir = EngineManager.get_engine_dir()
        engine_script = engine_dir / "scripts" / "download_weights.py"
        if not engine_script.is_file():
            self.download_finished.emit(False, "Engine scripts not found. Please download engine or link your existing CorridorKey folder first.")
            return

        # Prepare resilient execution command passing --package_root pointing to APP_ROOT
        cmd = [
            sys.executable,
            "-u",
            str(engine_script),
            "--package_root",
            str(APP_ROOT)
        ]

        # Check what is already present to skip
        status = WeightsManager.get_status()
        if status.get("corridorkey"):
            cmd.append("--skip_corridorkey")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["TQDM_POSITION"] = "-1"
        env["HF_HUB_DISABLE_PROGRESS_BARS"] = "0"

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                cwd=str(APP_ROOT),
                env=env
            )

            stages = [
                {"id": "corridorkey", "name": "CorridorKey v2 Weights", "size_mb": 2661.0, "tags": ["[corridorkey]"]},
                {"id": "cradio", "name": "C-RADIOv4 Foundation Model", "size_mb": 1730.0, "tags": ["[c-radio]", "cradio"]},
                {"id": "moge", "name": "MoGe-2 Geometry Model", "size_mb": 419.0, "tags": ["[moge]"]},
                {"id": "rvm", "name": "RVM Matting Model", "size_mb": 270.0, "tags": ["[rvm]"]},
            ]
            total_mb = sum(s["size_mb"] for s in stages)
            stage_offsets = []
            cum = 0.0
            for s in stages:
                stage_offsets.append(cum)
                cum += s["size_mb"]

            if status.get("corridorkey"):
                current_stage_idx = 1
                init_mb = stage_offsets[1]
                init_pct = (init_mb / total_mb) * 100.0
                current_stage = f"{stages[1]['name']} (~1.73 GB)"
                self.overall_progress_updated.emit(
                    init_pct,
                    f"Model 2 of {len(stages)} | {stages[1]['name']}",
                    f"{init_mb / 1000.0:.2f} GB / {total_mb / 1000.0:.2f} GB ({init_pct:.0f}%)"
                )
                self.progress_updated.emit(0.0, current_stage, "Connecting...")
            else:
                current_stage_idx = 0
                current_stage = f"{stages[0]['name']} (~2.66 GB)"
                self.overall_progress_updated.emit(
                    0.0,
                    f"Model 1 of {len(stages)} | {stages[0]['name']}",
                    f"0.00 GB / {total_mb / 1000.0:.2f} GB (0%)"
                )
                self.progress_updated.emit(0.0, current_stage, "Connecting...")

            buf = bytearray()
            total_bytes: Optional[float] = None
            total_str: str = ""

            def _parse_size(s: str) -> Optional[float]:
                units = {'B': 1.0, 'kB': 1e3, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'k': 1e3, 'M': 1e6, 'G': 1e9}
                m_sz = re.search(r'([0-9\.]+)\s*([a-zA-Z]+)', s)
                if not m_sz:
                    return None
                val, u = float(m_sz.group(1)), m_sz.group(2)
                return val * units.get(u, 1.0)

            def _emit_both(pct: float, current_info: str, speed_eta: str):
                self.progress_updated.emit(pct, current_info, speed_eta)
                s_meta = stages[current_stage_idx]
                s_dl_mb = (min(100.0, max(0.0, pct)) / 100.0) * s_meta["size_mb"]
                cur_overall_mb = stage_offsets[current_stage_idx] + s_dl_mb
                cur_overall_pct = min(100.0, (cur_overall_mb / total_mb) * 100.0)
                self.overall_progress_updated.emit(
                    cur_overall_pct,
                    f"Model {current_stage_idx + 1} of {len(stages)} | {s_meta['name']}",
                    f"{cur_overall_mb / 1000.0:.2f} GB / {total_mb / 1000.0:.2f} GB ({cur_overall_pct:.0f}%)"
                )

            # Background thread to monitor file sizes on disk when stdout produces no lines (e.g. urllib copy)
            stop_disk_watcher = threading.Event()
            def _disk_watcher_loop():
                rvm_part = VFMS_DIR / "rvm" / (RVM_FILE + ".part")
                last_bytes = 0
                last_time = time.time()
                while not stop_disk_watcher.is_set():
                    time.sleep(0.3)
                    if current_stage_idx == 3:  # RVM stage
                        if rvm_part.exists():
                            try:
                                cur_bytes = rvm_part.stat().st_size
                                now = time.time()
                                dt = max(0.1, now - last_time)
                                speed_bps = max(0.0, (cur_bytes - last_bytes) / dt)
                                last_bytes = cur_bytes
                                last_time = now

                                rvm_total = 270_086_372
                                pct = min(99.0, (cur_bytes / rvm_total) * 100.0)
                                speed_str = f"{speed_bps / 1e6:.1f} MB/s" if speed_bps > 0 else ""
                                info_str = f"RVM Matting Model | {cur_bytes / 1e6:.1f} MB / 270.1 MB"
                                _emit_both(pct, info_str, speed_str)
                            except Exception:
                                pass

            watcher_thread = threading.Thread(target=_disk_watcher_loop, daemon=True)
            watcher_thread.start()

            while not self._is_stopped:
                try:
                    b = self._process.stdout.read(1)
                except Exception:
                    break
                if not b:
                    break
                if b in (b'\r', b'\n'):
                    raw_str = buf.decode('utf-8', errors='ignore').strip()
                    buf.clear()
                    if raw_str:
                        self.progress_received.emit(raw_str)

                        # Stage detection
                        raw_lower = raw_str.lower()
                        for idx, s_info in enumerate(stages):
                            if any(t in raw_lower for t in s_info["tags"]):
                                if idx != current_stage_idx:
                                    current_stage_idx = idx
                                    total_bytes = None
                                    total_str = ""
                                    current_stage = f"{s_info['name']} (~{int(s_info['size_mb'])} MB)"
                                    _emit_both(0.0, current_stage, "Connecting...")
                                break

                        # 1. Match file total size: e.g. "reconstructing file: 0% | 0.00B / 2.66GB"
                        m_recon = re.search(r'reconstructing file:\s*(\d+)%.*?/\s*([0-9\.]+\s*[a-zA-Z]+)', raw_str)
                        if m_recon:
                            pct = float(m_recon.group(1))
                            total_str = m_recon.group(2)
                            total_bytes = _parse_size(total_str)
                            _emit_both(pct, f"{current_stage}  |  Total: {total_str}", "Downloading...")
                            continue

                        # 2. Match downloading bytes stream: e.g. "downloading bytes: | 2.81MB, 218kB/s"
                        m_bytes = re.search(r'downloading bytes:\s*.*?\|\s*([0-9\.]+\s*[a-zA-Z]+)(?:,\s*([0-9\.]+\s*[a-zA-Z]+/s))?', raw_str)
                        if m_bytes:
                            cur_str = m_bytes.group(1)
                            speed = m_bytes.group(2) or ""
                            cur_bytes = _parse_size(cur_str)
                            pct = 0.0
                            if total_bytes and cur_bytes is not None and total_bytes > 0:
                                pct = min(100.0, (cur_bytes / total_bytes) * 100.0)
                            sub_info = f"{cur_str} / {total_str}" if total_str else cur_str
                            _emit_both(pct, f"{current_stage}  |  {sub_info}", speed)
                            continue

                        # 3. Match standard tqdm progress: e.g. "Fetching 31 files: 97% | 30/31"
                        m_tqdm = re.search(r"(\d+(?:\.\d+)?)%\|.*?\|\s*([^\s\[\]]+)?\s*\[(.*?)\]", raw_str)
                        if m_tqdm:
                            try:
                                pct = float(m_tqdm.group(1))
                                size_info = m_tqdm.group(2) or ""
                                stats_info = m_tqdm.group(3) or ""
                                stage_label = f"{current_stage}  |  {size_info}" if size_info else current_stage
                                _emit_both(pct, stage_label, stats_info)
                            except Exception:
                                pass
                            continue

                        # 4. Fallback percentage match
                        m_simple = re.search(r"(\d+(?:\.\d+)?)%", raw_str)
                        if m_simple:
                            try:
                                pct = float(m_simple.group(1))
                                _emit_both(pct, current_stage, "")
                            except Exception:
                                pass
                else:
                    buf.extend(b)

            stop_disk_watcher.set()
            if self._is_stopped:
                self.download_finished.emit(False, "Download canceled by user.")
                return

            ret = self._process.wait()
            if ret == 0:
                self.overall_progress_updated.emit(
                    100.0,
                    f"All Models Ready ({len(stages)} of {len(stages)})",
                    f"{total_mb / 1000.0:.2f} GB / {total_mb / 1000.0:.2f} GB (100%)"
                )
                self.progress_updated.emit(100.0, "All models verified and ready!", "")
                self.download_finished.emit(True, "All models downloaded and ready!")
            else:
                self.download_finished.emit(False, f"Download failed with code {ret}")
        except Exception as e:
            if not self._is_stopped:
                self.download_finished.emit(False, str(e))
