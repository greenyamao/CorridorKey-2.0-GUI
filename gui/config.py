from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field

CONFIG_PATH = Path(__file__).resolve().parent / "user_settings.json"


@dataclass
class GuiSettings:
    last_input_dir: str = ""
    last_output_dir: str = ""
    last_hint_dir: str = ""
    
    # Inference parameters
    time_awareness: int = 40  # Default Hann stride/chunk profile
    hann_chunk: int = 80
    hann_stride: int = 40
    auto_vram: bool = True
    low_vram: bool = False
    
    # Hint parameters
    use_alpha_hint: bool = False
    alpha_hint_path: str = ""
    hint_mode: str = "first_frame"  # "first_frame" | "all_frames"
    hint_quality: float = 0.95
    carry_hint_quality: float = 0.95
    carry_hint: bool = True
    
    # Despill parameters
    despill_color: str = "green"  # "green" | "blue"
    despill_strength: float = 0.50
    linear_brightness: float = 1.0
    linear_contrast: float = 1.0
    
    # Output parameters
    output_format: str = "video"  # "video" | "exr"
    exr_dtype: str = "half"  # "half" | "float"
    outputs: list[str] = field(default_factory=lambda: ["alpha", "fg"])
    ffmpeg_codec: str = "libx264"
    crf: int = 12
    pix_fmt: str = "yuv444p10le"
    
    def save(self, path: Path = CONFIG_PATH) -> None:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[GUI Config] Warning: failed to save settings: {e}")

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "GuiSettings":
        if not path.is_file():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except Exception as e:
            print(f"[GUI Config] Warning: failed to load settings: {e}")
            return cls()
