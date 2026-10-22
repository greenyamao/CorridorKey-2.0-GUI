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


_nvml_initialized = False
_nvml_handle = None


def _init_nvml():
    global _nvml_initialized, _nvml_handle
    if _nvml_initialized and _nvml_handle is not None:
        return _nvml_handle
    try:
        import pynvml
        pynvml.nvmlInit()
        _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        _nvml_initialized = True
        return _nvml_handle
    except Exception:
        _nvml_initialized = False
        _nvml_handle = None
        return None


def get_gpu_info() -> Dict[str, Any]:
    """Retrieve current GPU device memory and compute utilization info using NVML with PyTorch fallback."""
    handle = _init_nvml()
    if handle is not None:
        try:
            import pynvml
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            total_gb = mem.total / (1024 ** 3)
            used_gb = mem.used / (1024 ** 3)
            free_gb = mem.free / (1024 ** 3)
            return {
                "available": True,
                "device_name": str(name),
                "used_gb": round(used_gb, 1),
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
                "gpu_util": int(util.gpu),
                "mem_util": int(util.memory),
            }
        except Exception:
            pass

    if not torch.cuda.is_available():
        return {
            "available": False,
            "device_name": "No CUDA GPU detected",
            "used_gb": 0.0,
            "free_gb": 0.0,
            "total_gb": 0.0,
            "gpu_util": 0,
            "mem_util": 0,
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
            "gpu_util": 0,
            "mem_util": 0,
        }
    except Exception as e:
        return {
            "available": False,
            "device_name": f"Error: {e}",
            "used_gb": 0.0,
            "free_gb": 0.0,
            "total_gb": 0.0,
            "gpu_util": 0,
            "mem_util": 0,
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
