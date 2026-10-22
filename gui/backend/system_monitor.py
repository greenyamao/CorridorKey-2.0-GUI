from __future__ import annotations

import os
import shutil
from typing import Dict, Any, Tuple
import torch

try:
    from corridorkey.runtime import estimate_peak_vram_gb, select_vram_profile
except ImportError:
    estimate_peak_vram_gb = None
    select_vram_profile = None


def get_gpu_info() -> Dict[str, Any]:
    """Retrieve current GPU device memory info using PyTorch CUDA."""
    if not torch.cuda.is_available():
        return {
            "available": False,
            "device_name": "No CUDA GPU detected",
            "used_gb": 0.0,
            "free_gb": 0.0,
            "total_gb": 0.0,
        }
    
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        total_gb = total_bytes / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)
        used_gb = total_gb - free_gb
        device_name = torch.cuda.get_device_name(0)
        return {
            "available": True,
            "device_name": device_name,
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_gb, 1),
        }
    except Exception as e:
        return {
            "available": False,
            "device_name": f"Error: {e}",
            "used_gb": 0.0,
            "free_gb": 0.0,
            "total_gb": 0.0,
        }


def get_disk_free_gb(path: str = ".") -> float:
    """Return free disk space in GB for given path or current drive."""
    try:
        target = os.path.abspath(path)
        if not os.path.exists(target):
            target = os.path.dirname(target)
            if not os.path.exists(target):
                target = "."
        usage = shutil.disk_usage(target)
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return 0.0


def calculate_clip_vram_estimate(
    width: int,
    height: int,
    frames: int,
    low_vram: bool = False,
    hann_chunk: int = 80
) -> Tuple[float, bool]:
    """Estimate peak VRAM required for processing the given clip resolution."""
    if estimate_peak_vram_gb is None:
        return (4.0, True)
    
    megapixels = (width * height) / 1e6
    try:
        estimated_peak = estimate_peak_vram_gb(megapixels, min(hann_chunk, max(1, frames)), low_vram)
        # Apply safety margin like in runtime.py
        peak_with_margin = estimated_peak * 1.1 + 0.3
        
        gpu_info = get_gpu_info()
        fits = peak_with_margin <= gpu_info.get("total_gb", 8.0)
        return (round(peak_with_margin, 1), fits)
    except Exception:
        return (5.0, True)
