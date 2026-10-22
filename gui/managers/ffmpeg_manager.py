"""Portable FFmpeg binary detection and management.

Ensures ffmpeg and ffprobe are available for video probing and transcoding.
If missing from the system PATH on Windows, downloads a portable build into ./bin/.
"""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
import urllib.request
from pathlib import Path
from typing import Optional, Callable

# Project root (100% relative)
APP_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_DIR = APP_ROOT / "bin"

# Lightweight static Windows FFmpeg build URL
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
# Alternative fallback mirror: GitHub release
FFMPEG_GITHUB_MIRROR = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


class FFmpegManager:
    """Detects and manages portable FFmpeg binaries."""

    @staticmethod
    def get_bin_dir() -> Path:
        return BIN_DIR

    @classmethod
    def get_ffmpeg_executable(cls) -> Optional[Path]:
        """Returns path to ffmpeg executable or None if not found."""
        # 1. Check local bin/ folder first
        local_bin = BIN_DIR / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        if local_bin.is_file():
            return local_bin

        # 2. Check system PATH
        system_path = shutil.which("ffmpeg")
        if system_path:
            return Path(system_path)

        return None

    @classmethod
    def is_available(cls) -> bool:
        """Returns True if both ffmpeg and ffprobe are available."""
        exe = cls.get_ffmpeg_executable()
        probe = shutil.which("ffprobe") or (BIN_DIR / ("ffprobe.exe" if sys.platform == "win32" else "ffprobe")).is_file()
        return (exe is not None and exe.is_file()) and bool(probe)

    @classmethod
    def setup_path(cls) -> None:
        """Adds ./bin to os.environ['PATH'] so child processes can invoke ffmpeg."""
        if BIN_DIR.is_dir():
            bin_str = str(BIN_DIR.resolve())
            current_path = os.environ.get("PATH", "")
            if bin_str not in current_path.split(os.pathsep):
                os.environ["PATH"] = bin_str + os.pathsep + current_path

    @classmethod
    def download_portable_ffmpeg(cls, progress_callback: Optional[Callable[[float, str], None]] = None) -> bool:
        """Downloads and extracts portable ffmpeg and ffprobe binaries into ./bin/."""
        if cls.is_available():
            cls.setup_path()
            return True

        BIN_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = BIN_DIR / "ffmpeg_download.zip"

        def _report(block_num, block_size, total_size):
            if progress_callback and total_size > 0:
                pct = min(100.0, (block_num * block_size / total_size) * 100.0)
                downloaded_mb = (block_num * block_size) / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                progress_callback(pct, f"Downloading FFmpeg: {downloaded_mb:.1f} / {total_mb:.1f} MB ({pct:.0f}%)")

        # Try download
        success = False
        for url in (FFMPEG_WIN_URL, FFMPEG_GITHUB_MIRROR):
            try:
                if progress_callback:
                    progress_callback(0.0, f"Connecting to {url}...")
                urllib.request.urlretrieve(url, zip_path, reporthook=_report)
                success = True
                break
            except Exception as e:
                print(f"[FFmpegManager] Download from {url} failed: {e}")
                continue

        if not success or not zip_path.is_file():
            if progress_callback:
                progress_callback(0.0, "FFmpeg download failed. Please install FFmpeg manually.")
            return False

        if progress_callback:
            progress_callback(100.0, "Extracting FFmpeg binaries...")

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    filename = os.path.basename(member)
                    if filename.lower() in ("ffmpeg.exe", "ffprobe.exe"):
                        source = zip_ref.open(member)
                        target = open(BIN_DIR / filename, "wb")
                        with source, target:
                            shutil.copyfileobj(source, target)

            # Cleanup zip
            try:
                zip_path.unlink()
            except Exception:
                pass

            cls.setup_path()
            return cls.is_available()
        except Exception as e:
            print(f"[FFmpegManager] Extraction error: {e}")
            return False
