from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import cv2
import numpy as np
import subprocess


class ClipInfo:
    def __init__(
        self,
        path: str,
        name: str,
        width: int,
        height: int,
        fps: float,
        total_frames: int,
        is_frame_dir: bool = False,
        frame_files: Optional[List[str]] = None,
        discovered_hint_path: Optional[str] = None,
        discovered_hint_mode: Optional[str] = None,  # "first_frame" | "all_frames"
    ):
        self.path = path
        self.name = name
        self.width = width
        self.height = height
        self.fps = fps
        self.total_frames = max(1, total_frames)
        self.is_frame_dir = is_frame_dir
        self.frame_files = frame_files or []
        self.thumbnail: Optional[np.ndarray] = None  # RGB HxWx3
        self.discovered_hint_path = discovered_hint_path
        self.discovered_hint_mode = discovered_hint_mode

    @property
    def resolution_label(self) -> str:
        if self.width >= 3840 or self.height >= 2160:
            return "UHD"
        if self.width >= 1920 or self.height >= 1080:
            return "1080p"
        if self.width >= 1280 or self.height >= 720:
            return "720p"
        return f"{self.width}x{self.height}"


class StreamingFFmpegReader:
    """High-performance streaming raw RGBA reader using a persistent FFmpeg pipe."""

    def __init__(self, video_path: str, width: int, height: int, fps: float, total_frames: int):
        self.video_path = video_path
        self.width = width
        self.height = height
        self.fps = max(1.0, fps)
        self.total_frames = max(1, total_frames)
        self.frame_bytes = width * height * 4
        self.proc: Optional[subprocess.Popen] = None
        self.current_pipe_frame = -1
        self._cache: Dict[int, np.ndarray] = {}
        self._max_cache = 128

    def _start_pipe_at(self, frame_idx: int):
        self._close_pipe()
        seek_sec = frame_idx / self.fps
        cmd = [
            "ffmpeg",
            "-nostats",
            "-loglevel", "error",
            "-ss", f"{seek_sec:.4f}",
            "-i", self.video_path,
            "-f", "rawvideo",
            "-pix_fmt", "rgba",
            "-",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=self.frame_bytes * 8,
            )
            self.current_pipe_frame = frame_idx
        except Exception:
            self.proc = None
            self.current_pipe_frame = -1

    def _close_pipe(self):
        if self.proc is not None:
            try:
                if self.proc.stdout:
                    self.proc.stdout.close()
                self.proc.terminate()
                self.proc.kill()
                self.proc.wait(timeout=0.2)
            except Exception:
                pass
            self.proc = None
        self.current_pipe_frame = -1

    def get_frame(self, index: int) -> Optional[np.ndarray]:
        index = max(0, min(index, self.total_frames - 1))
        if index in self._cache:
            return self._cache[index]

        if self.proc is None or index != self.current_pipe_frame:
            # If jumping ahead by 1 to 4 frames sequentially, read through without restarting pipe
            if self.proc is not None and 0 < (index - self.current_pipe_frame) <= 4:
                while self.current_pipe_frame < index:
                    try:
                        raw = self.proc.stdout.read(self.frame_bytes)
                        if len(raw) < self.frame_bytes:
                            self._start_pipe_at(index)
                            break
                        self.current_pipe_frame += 1
                    except Exception:
                        self._start_pipe_at(index)
                        break
            else:
                self._start_pipe_at(index)

        if self.proc is None or self.proc.stdout is None:
            return None

        try:
            raw = self.proc.stdout.read(self.frame_bytes)
            if len(raw) < self.frame_bytes:
                return None
            arr = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 4))
            self.current_pipe_frame += 1

            if len(self._cache) >= self._max_cache:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[index] = arr
            return arr
        except Exception:
            return None

    def close(self):
        self._close_pipe()
        self._cache.clear()


class VideoReader:
    """Manages random-access frame reading and thumbnail caching."""

    SUPPORTED_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff", ".webp", ".dpx"}

    def __init__(self, clip_info: ClipInfo):
        self.clip = clip_info
        self.cap: Optional[cv2.VideoCapture] = None
        self._last_index = -1
        self._frame_cache: Dict[int, np.ndarray] = {}  # index -> RGB frame
        self._max_cache = 64
        self._streaming_mov_reader: Optional[StreamingFFmpegReader] = None

    def open(self) -> bool:
        if not self.clip.is_frame_dir:
            self.cap = cv2.VideoCapture(self.clip.path)
            return self.cap.isOpened()
        return len(self.clip.frame_files) > 0

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self._streaming_mov_reader is not None:
            self._streaming_mov_reader.close()
            self._streaming_mov_reader = None
        self._frame_cache.clear()
        self._last_index = -1

    def get_frame(self, index: int) -> Optional[np.ndarray]:
        """Fetch frame at index as an RGB uint8 numpy array with hardware streaming preference."""
        index = max(0, min(index, self.clip.total_frames - 1))
        
        # Cache hit when random seeking (not sequential streaming)
        if index in self._frame_cache and index != self._last_index + 1:
            return self._frame_cache[index]

        rgb = None
        if self.clip.is_frame_dir:
            if index in self._frame_cache:
                return self._frame_cache[index]
            if index < len(self.clip.frame_files):
                fpath = self.clip.frame_files[index]
                bgr = cv2.imread(fpath)
                if bgr is not None:
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            if self.cap is None or not self.cap.isOpened():
                self.open()
            if self.cap is not None and self.cap.isOpened():
                # Avoid expensive keyframe seek when reading sequentially
                if index != self._last_index + 1:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ret, bgr = self.cap.read()
                if ret and bgr is not None:
                    self._last_index = index
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                elif index in self._frame_cache:
                    return self._frame_cache[index]

        if rgb is not None:
            if len(self._frame_cache) >= self._max_cache:
                oldest = next(iter(self._frame_cache))
                del self._frame_cache[oldest]
            self._frame_cache[index] = rgb

        return rgb

    def get_rgba_frame(self, index: int) -> Optional[np.ndarray]:
        """Fetch frame as RGBA uint8 array, streaming embedded alpha from ProRes 4444 containers."""
        index = max(0, min(index, self.clip.total_frames - 1))
        if self._streaming_mov_reader is None:
            self._streaming_mov_reader = StreamingFFmpegReader(
                self.clip.path,
                self.clip.width,
                self.clip.height,
                self.clip.fps,
                self.clip.total_frames,
            )

        frame = self._streaming_mov_reader.get_frame(index)
        if frame is not None:
            return frame

        # Fallback to get_frame + opaque alpha
        rgb = self.get_frame(index)
        if rgb is not None:
            h, w, _ = rgb.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[:, :, :3] = rgb
            rgba[:, :, 3] = 255
            return rgba
        return None


def find_alpha_hint(input_path: Path) -> Optional[Path]:
    """Locate companion full hint video or image (<clip>_alphahint) next to the input."""
    parent_dir = input_path.parent
    base_name = input_path.stem
    allowed_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.png', '.jpg', '.jpeg', '.exr'}
    
    if parent_dir.exists():
        for item in sorted(parent_dir.iterdir()):
            if item.is_file() and item.suffix.lower() in allowed_extensions:
                if item.name.lower().startswith(f"{base_name.lower()}_alphahint"):
                    return item
    return None


def find_first_frame_hint(input_path: Path) -> Optional[Path]:
    """Locate companion first-frame hint image next to input (e.g. <clip>FrameHint.png)."""
    parent_dir = input_path.parent
    base_name = input_path.stem.lower()
    allowed_extensions = {'.png', '.jpg', '.jpeg', '.exr'}

    if parent_dir.exists():
        for item in sorted(parent_dir.iterdir()):
            if item.is_file() and item.suffix.lower() in allowed_extensions:
                name_lower = item.stem.lower()
                if name_lower.startswith(base_name):
                    remainder = name_lower[len(base_name):].lstrip("_- ")
                    if remainder.startswith("framehint") or remainder.startswith("alphahint"):
                        return item
    return None


def resolve_image_seq_dirs(dir_path: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Check for VFX pipeline subfolders: input/ and alphahint/."""
    if not dir_path.is_dir():
        return None, None
    input_dir, alphahint_dir = None, None
    try:
        for item in dir_path.iterdir():
            if item.is_dir():
                if item.name.lower() == "input":
                    input_dir = item
                elif item.name.lower() == "alphahint":
                    alphahint_dir = item
    except Exception:
        pass
    return input_dir, alphahint_dir


def probe_clip(path_str: str) -> Optional[ClipInfo]:
    """Probe video file or frame directory, auto-discovering companion hints."""
    path = Path(path_str).resolve()
    if not path.exists():
        return None

    # Check for VFX image sequence folder (input/ subfolder)
    if path.is_dir():
        seq_input, seq_hint = resolve_image_seq_dirs(path)
        actual_input = seq_input if seq_input else path
        valid_files = sorted([
            str(p) for p in actual_input.iterdir()
            if p.suffix.lower() in VideoReader.IMAGE_EXTS
        ])
        if not valid_files:
            return None
        
        sample = cv2.imread(valid_files[0])
        if sample is None:
            return None
        h, w = sample.shape[:2]

        hint_path = str(seq_hint) if seq_hint else None
        hint_mode = "all_frames" if seq_hint else None

        info = ClipInfo(
            path=str(path),
            name=path.name,
            width=w,
            height=h,
            fps=24.0,
            total_frames=len(valid_files),
            is_frame_dir=True,
            frame_files=valid_files,
            discovered_hint_path=hint_path,
            discovered_hint_mode=hint_mode,
        )
        thumb = cv2.resize(sample, (120, max(20, int(120 * h / max(1, w)))))
        info.thumbnail = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        return info

    if path.is_file() and path.suffix.lower() in VideoReader.SUPPORTED_EXTS:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return None
        
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 24.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            total_frames = 1

        # Check for companion hints
        hint_path = None
        hint_mode = None

        discovered_alpha = find_alpha_hint(path)
        if discovered_alpha:
            hint_path = str(discovered_alpha)
            if discovered_alpha.suffix.lower() in VideoReader.SUPPORTED_EXTS:
                hint_mode = "all_frames"
            else:
                hint_mode = "first_frame"
        else:
            discovered_frame = find_first_frame_hint(path)
            if discovered_frame:
                hint_path = str(discovered_frame)
                hint_mode = "first_frame"

        info = ClipInfo(
            path=str(path),
            name=path.name,
            width=w,
            height=h,
            fps=round(fps, 2),
            total_frames=total_frames,
            is_frame_dir=False,
            discovered_hint_path=hint_path,
            discovered_hint_mode=hint_mode,
        )
        
        ret, frame = cap.read()
        if ret and frame is not None:
            thumb_h = max(20, int(120 * h / max(1, w)))
            thumb = cv2.resize(frame, (120, thumb_h))
            info.thumbnail = cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)
        cap.release()
        return info

    return None


def scan_directory_for_clips(dir_path: str) -> List[ClipInfo]:
    """Scan directory for all valid video files and image sequence folders."""
    p = Path(dir_path).resolve()
    clips = []
    if not p.is_dir():
        return clips

    try:
        for item in sorted(p.iterdir()):
            if item.is_file() and item.suffix.lower() in VideoReader.SUPPORTED_EXTS:
                if "_alphahint" not in item.name.lower() and "framehint" not in item.name.lower():
                    clip = probe_clip(str(item))
                    if clip:
                        clips.append(clip)
            elif item.is_dir():
                # Avoid scanning subfolders of known image sequences
                if item.name.lower() not in {"input", "alphahint", "output"}:
                    clip = probe_clip(str(item))
                    if clip:
                        clips.append(clip)
    except Exception as e:
        print(f"[VideoLoader] Warning: error scanning directory: {e}")
    return clips
