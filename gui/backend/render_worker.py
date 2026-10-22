from __future__ import annotations

import sys
import os
import re
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from PySide6.QtCore import QObject, Signal, QThread


@dataclass
class RenderTask:
    task_id: str
    clip_path: str
    output_dir: str
    clip_name: str
    total_frames: int
    
    # Model Weights
    weights_path: Optional[str] = None
    
    # Hints
    use_alpha_hint: bool = False
    alpha_hint_path: str = ""
    hint_mode: str = "first_frame"  # "first_frame" | "all_frames"
    hint_quality: float = 0.95
    carry_hint_quality: float = 0.95
    carry_hint: bool = True
    
    # Hann Window & Memory
    hann_chunk: Optional[int] = None
    hann_stride: Optional[int] = None
    low_vram: bool = False
    auto_vram: bool = True
    temp_dir: Optional[str] = None
    
    # Outputs Selection: alpha, fg, cutout, checker
    outputs: List[str] = field(default_factory=lambda: ["alpha", "fg", "cutout", "checker"])
    
    # Frame sampling & limits
    num_frames: int = -1
    start_mode: str = "begin"  # "begin", "middle", "random_middle"
    seed: int = 0
    model_scale: float = 1.0
    frame_dir_fps: float = 24.0
    
    # Color spaces & Despill
    frame_dir_linear: bool = False
    cutout_linear: bool = False
    despill_strength: float = 0.50
    linear_brightness: float = 1.0
    linear_contrast: float = 1.0
    linear_contrast_pivot: float = 0.18
    
    # Delivery & Encoding
    output_format: str = "video"  # "video" | "exr"
    exr_dtype: str = "half"  # "half" | "float"
    ffmpeg_bin: str = "ffmpeg"
    ffmpeg_codec: str = "libx264"
    crf: int = 12
    preset: str = "medium"
    pix_fmt: str = "yuv444p10le"
    bitrate: Optional[str] = None
    ffmpeg_threads: int = 2
    stage2_batch: int = 1
    
    # Low VRAM tuning
    low_vram_foundation_chunk: int = 4
    low_vram_mlp_chunk_tokens: int = 65536
    low_vram_enc_frame_chunk: int = 1
    low_vram_swin_window_batch: int = 16
    low_vram_full_attn_query_chunk_tokens: int = 2048


class RenderRunner(QThread):
    progress_changed = Signal(str, int, int, float, str)  # task_id, frame, total, percent, status
    log_received = Signal(str, str)  # task_id, line
    finished_signal = Signal(str, bool, str)  # task_id, success, message

    def __init__(self, task: RenderTask, parent=None):
        super().__init__(parent)
        self.task = task
        self._process: Optional[subprocess.Popen] = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
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
        root_dir = Path(__file__).resolve().parent.parent.parent
        from gui.managers.engine_manager import EngineManager
        infer_script = EngineManager.get_infer_script()
        if infer_script is None or not infer_script.is_file():
            # Fallback check if infer.py is at root
            if (root_dir / "infer.py").is_file():
                infer_script = root_dir / "infer.py"
            else:
                self.finished_signal.emit(self.task.task_id, False, "CorridorKey engine (infer.py) not found. Please download engine or link your existing CorridorKey folder.")
                return

        # Ensure portable FFmpeg is in PATH if present in ./bin
        bin_dir = root_dir / "bin"
        if bin_dir.is_dir():
            bin_str = str(bin_dir.resolve())
            cur_p = os.environ.get("PATH", "")
            if bin_str not in cur_p.split(os.pathsep):
                os.environ["PATH"] = bin_str + os.pathsep + cur_p

        # Build complete CLI arguments covering 100% of infer.py
        cmd = [
            sys.executable,
            "-u",
            str(infer_script),
            "--input", self.task.clip_path,
            "--output_dir", self.task.output_dir,
            "--despill_strength", str(self.task.despill_strength),
            "--linear_brightness", str(self.task.linear_brightness),
            "--linear_contrast", str(self.task.linear_contrast),
            "--linear_contrast_pivot", str(self.task.linear_contrast_pivot),
            "--model_scale", str(self.task.model_scale),
            "--seed", str(self.task.seed),
            "--frame_dir_fps", str(self.task.frame_dir_fps),
            "--output_format", self.task.output_format,
            "--exr_dtype", self.task.exr_dtype,
            "--ffmpeg_bin", self.task.ffmpeg_bin,
            "--ffmpeg_codec", self.task.ffmpeg_codec,
            "--crf", str(self.task.crf),
            "--preset", self.task.preset,
            "--pix_fmt", self.task.pix_fmt,
            "--ffmpeg_threads", str(self.task.ffmpeg_threads),
            "--stage2_batch", str(self.task.stage2_batch),
        ]

        if self.task.weights_path:
            cmd.extend(["--weights", self.task.weights_path])

        if self.task.bitrate:
            cmd.extend(["--bitrate", self.task.bitrate])

        if self.task.outputs:
            cmd.extend(["--outputs"] + self.task.outputs)

        if self.task.cutout_linear:
            cmd.append("--cutout_linear")

        if self.task.frame_dir_linear:
            cmd.append("--frame_dir_linear")

        if self.task.num_frames > 0:
            cmd.extend(["--num_frames", str(self.task.num_frames)])
            cmd.extend(["--start_mode", self.task.start_mode])

        # Memory / VRAM options
        if self.task.temp_dir:
            cmd.extend(["--temp_dir", self.task.temp_dir])

        if not self.task.auto_vram:
            if self.task.hann_chunk is not None:
                cmd.extend(["--hann_chunk", str(self.task.hann_chunk)])
            if self.task.hann_stride is not None:
                cmd.extend(["--hann_stride", str(self.task.hann_stride)])
            if self.task.low_vram:
                cmd.append("--low_vram")
                cmd.extend(["--low_vram_foundation_chunk", str(self.task.low_vram_foundation_chunk)])
                cmd.extend(["--low_vram_mlp_chunk_tokens", str(self.task.low_vram_mlp_chunk_tokens)])
                cmd.extend(["--low_vram_enc_frame_chunk", str(self.task.low_vram_enc_frame_chunk)])
                cmd.extend(["--low_vram_swin_window_batch", str(self.task.low_vram_swin_window_batch)])
                cmd.extend(["--low_vram_full_attn_query_chunk_tokens", str(self.task.low_vram_full_attn_query_chunk_tokens)])

        # Hints
        if self.task.use_alpha_hint and self.task.alpha_hint_path:
            if self.task.hint_mode == "first_frame":
                cmd.extend(["--hint_first_frame", self.task.alpha_hint_path])
            else:
                cmd.extend(["--hint_video", self.task.alpha_hint_path])
            
            cmd.extend(["--hint_quality", str(self.task.hint_quality)])
            if not self.task.carry_hint:
                cmd.append("--no_carry_hint")
            else:
                cmd.extend(["--carry_hint_quality", str(self.task.carry_hint_quality)])

        self.log_received.emit(self.task.task_id, f"Command: {' '.join(cmd)}\n")
        self.progress_changed.emit(self.task.task_id, 0, self.task.total_frames, 0.0, "Starting inference...")

        try:
            env = os.environ.copy()
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(root_dir / "engine" if (root_dir / "engine").is_dir() else root_dir),
                env=env,
            )

            current_frame = 0
            for raw_line in iter(self._process.stdout.readline, ""):
                if self._is_cancelled:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                self.log_received.emit(self.task.task_id, line)

                match_frame = re.search(r"(\d+)/(\d+)", line)
                if match_frame:
                    try:
                        cur, tot = int(match_frame.group(1)), int(match_frame.group(2))
                        if tot > 0:
                            pct = min(100.0, (cur / tot) * 100.0)
                            self.progress_changed.emit(
                                self.task.task_id, cur, tot, pct, f"Processing {cur}/{tot} frames..."
                            )
                    except Exception:
                        pass

                if "Auto VRAM:" in line:
                    self.progress_changed.emit(
                        self.task.task_id, 0, self.task.total_frames, 5.0, line
                    )
                elif "stage 1" in line.lower():
                    self.progress_changed.emit(
                        self.task.task_id, 0, self.task.total_frames, 35.0, "Stage 1: Temporal context analysis..."
                    )
                elif "stage 2" in line.lower():
                    self.progress_changed.emit(
                        self.task.task_id, 0, self.task.total_frames, 75.0, "Stage 2: Full-res matte synthesis..."
                    )

            self._process.stdout.close()
            return_code = self._process.wait()

            if self._is_cancelled:
                self.finished_signal.emit(self.task.task_id, False, "Render cancelled by user.")
            elif return_code == 0:
                self.progress_changed.emit(
                    self.task.task_id, self.task.total_frames, self.task.total_frames, 100.0, "Completed!"
                )
                self.finished_signal.emit(self.task.task_id, True, "Render finished successfully!")
            else:
                self.finished_signal.emit(
                    self.task.task_id, False, f"Inference exited with code {return_code}"
                )

        except Exception as e:
            self.finished_signal.emit(self.task.task_id, False, f"Execution error: {e}")


from gui.managers.weights_manager import WeightsDownloadWorker as WeightDownloader

