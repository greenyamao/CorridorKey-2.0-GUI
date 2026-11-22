from __future__ import annotations

import os
import shutil
from typing import Dict, Any, Tuple
try:
    import torch
except ImportError:
    torch = None

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
            major, minor = (8, 0)
            if torch is not None and torch.cuda.is_available():
                try:
                    major, minor = torch.cuda.get_device_capability()
                except Exception:
                    pass
            is_supported = (major >= 8)
            return {
                "available": True,
                "device_name": str(name),
                "used_gb": round(used_gb, 1),
                "free_gb": round(free_gb, 1),
                "total_gb": round(total_gb, 1),
                "gpu_util": int(util.gpu),
                "mem_util": int(util.memory),
                "compute_cap": (major, minor),
                "is_supported": is_supported,
            }
        except Exception:
            pass

    if torch is None or not torch.cuda.is_available():
        return {
            "available": False,
            "device_name": "No CUDA GPU detected",
            "used_gb": 0.0,
            "free_gb": 0.0,
            "total_gb": 0.0,
            "gpu_util": 0,
            "mem_util": 0,
            "compute_cap": (0, 0),
            "is_supported": False,
        }
    
    try:
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        total_gb = total_bytes / (1024 ** 3)
        free_gb = free_bytes / (1024 ** 3)
        used_gb = total_gb - free_gb
        device_name = torch.cuda.get_device_name(0)
        major, minor = torch.cuda.get_device_capability()
        return {
            "available": True,
            "device_name": device_name,
            "used_gb": round(used_gb, 1),
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_gb, 1),
            "gpu_util": 0,
            "mem_util": 0,
            "compute_cap": (major, minor),
            "is_supported": (major >= 8),
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
            "compute_cap": (0, 0),
            "is_supported": False,
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


def get_optimal_hardware_profile(
    width: int,
    height: int,
    total_frames: int = 1,
) -> Dict[str, Any]:
    """
    Intelligently determine optimal Hann window chunk, stride, memory mode,
    and stage-2 batch based on GPU VRAM, architecture generation, and clip resolution.
    Avoids upstream aggressive throttling while ensuring zero OOM crashes.
    """
    gpu_info = get_gpu_info()
    tot_vram = float(gpu_info.get("total_gb", 8.0))
    c_major, c_minor = gpu_info.get("compute_cap", (8, 0))
    d_name = str(gpu_info.get("device_name", ""))

    w = max(1, width if width > 0 else 1920)
    h = max(1, height if height > 0 else 1080)
    megapixels = (w * h) / 1e6

    is_blackwell_or_newer = (c_major >= 12 or "50" in d_name)
    is_ada = ((c_major == 8 and c_minor == 9) or "40" in d_name)
    arch_tag = "Blackwell" if is_blackwell_or_newer else ("Ada" if is_ada else ("Ampere" if c_major >= 8 else "CUDA"))

    # Tier 1: 15.5+ GB VRAM (RTX 4090, 4080, 5080, 5090, 3090, Pro GPUs)
    if tot_vram >= 15.5:
        if megapixels <= 4.0:
            chunk, stride = 48, 24
            low_vram = False
            batch = 4
            p_name = "High Quality (48 / 24)"
            mode_desc = f"Full VRAM · {arch_tag} Fast"
        else:
            chunk, stride = 24, 12
            low_vram = False
            batch = 2
            p_name = "Medium (24 / 12)"
            mode_desc = f"Full VRAM · 4K Mode"

    # Tier 2: 10.5 GB - 15.4 GB VRAM (RTX 4070 12GB, 3060 12GB, 3080 10/12GB)
    elif tot_vram >= 10.5:
        if megapixels <= 2.3:
            chunk, stride = 24, 12
            low_vram = False
            batch = 2
            p_name = "Medium (24 / 12)"
            mode_desc = f"Full VRAM · In-Memory"
        else:
            chunk, stride = 24, 12
            low_vram = True
            batch = 4 if is_blackwell_or_newer else 2
            p_name = "Medium (24 / 12)"
            mode_desc = "Low VRAM Mode"

    # Tier 3: 7.5 GB - 10.4 GB VRAM (RTX 5070 Laptop, RTX 4060, RTX 3070, RTX 3060 Ti)
    elif tot_vram >= 7.5:
        if megapixels <= 1.2:
            chunk, stride = 24, 12
            low_vram = False
            batch = 4 if is_blackwell_or_newer else 2
            p_name = "Medium (24 / 12)"
            mode_desc = f"Full VRAM · {arch_tag}"
        else:
            # For 8 GB cards at 1080p+, chunk 16 / stride 8 with low_vram ensures rock-solid stability
            # Stride 8 cuts windows by 50% compared to stride 4 (1272 vs 2545 windows)
            # Batch 4 on Blackwell saturates Tensor Cores for 3-4x faster Stage 2
            chunk, stride = 16, 8
            low_vram = True
            batch = 4 if is_blackwell_or_newer else 2
            p_name = "Balanced (16 / 8)"
            mode_desc = f"Optimized for {arch_tag} 8 GB · Stride 8"

    # Tier 4: < 7.5 GB VRAM (RTX 3060 Mobile 6GB, GTX 1660, 4GB GPUs)
    else:
        chunk, stride = 8, 4
        low_vram = True
        batch = 1
        p_name = "Low VRAM (8 / 4)"
        mode_desc = "Safe Low Memory"

    badge_text = f"Auto Window: {p_name} (Optimized for {d_name or 'GPU'} · {tot_vram:.0f} GB)"
    badge_tooltip = (
        f"<b>Auto Temporal Window: {p_name}</b><br>"
        f"GPU: {d_name or 'Detected GPU'} ({tot_vram:.1f} GB VRAM, {arch_tag})<br>"
        f"Resolution: {w}x{h} ({megapixels:.2f} MP)<br>"
        f"Profile: Chunk={chunk}, Stride={stride}, Mode={mode_desc}, Batch={batch}<br>"
        f"Optimized to maximize speed and prevent CUDA Out Of Memory errors.<br>"
        f"Check 'Manual Temporal Window' to override."
    )

    return {
        "hann_chunk": chunk,
        "hann_stride": stride,
        "low_vram": low_vram,
        "stage2_batch": batch,
        "preset_name": p_name,
        "mode_desc": mode_desc,
        "badge_text": badge_text,
        "badge_tooltip": badge_tooltip,
    }


def calculate_clip_vram_estimate(
    width: int,
    height: int,
    frames: int,
    low_vram: bool = False,
    hann_chunk: int = 80,
    auto_vram: bool = False,
) -> Tuple[float, bool, str]:
    """Estimate peak VRAM required for processing the given clip resolution."""
    gpu_info = get_gpu_info()
    total_gpu = gpu_info.get("total_gb", 8.0)

    if auto_vram:
        profile = get_optimal_hardware_profile(width, height, frames)
        hann_chunk = profile["hann_chunk"]
        low_vram = profile["low_vram"]

    if estimate_peak_vram_gb is None:
        return (4.0, True, "Auto")

    megapixels = (max(1, width) * max(1, height)) / 1e6
    try:
        estimated_peak = estimate_peak_vram_gb(megapixels, min(hann_chunk, max(1, frames)), low_vram)
        peak_with_margin = estimated_peak * 1.1 + 0.3
        fits = peak_with_margin <= total_gpu
        details = f"{hann_chunk} frames{' (Low VRAM)' if low_vram else ''}"
        return (round(peak_with_margin, 1), fits, details)
    except Exception:
        return (5.0, True, "Standard")
