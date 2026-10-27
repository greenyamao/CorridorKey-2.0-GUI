#!/usr/bin/env python3
"""Entry point for CorridorKey 2.0 Workbench GUI with fast dependency validation and process tuning."""

import sys
import os
import subprocess
import importlib.util
from pathlib import Path

# Ensure repo root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def optimize_windows_process():
    """Tunes Windows process scheduling, disables EcoQoS power throttling, and prevents console freezes."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h_proc = kernel32.GetCurrentProcess()

        # 1. Elevate process priority to ABOVE_NORMAL to prevent CPU starvation when window is unfocused
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass(h_proc, 0x00008000)  # ABOVE_NORMAL_PRIORITY_CLASS

        # 2. Disable Windows 11 EcoQoS (Power Throttling) to ensure background tasks run on P-cores
        class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
            _fields_ = [
                ("Version", wintypes.DWORD),
                ("ControlMask", wintypes.DWORD),
                ("StateMask", wintypes.DWORD),
            ]

        state = PROCESS_POWER_THROTTLING_STATE()
        state.Version = 1
        state.ControlMask = 1  # PROCESS_POWER_THROTTLING_EXECUTION_SPEED
        state.StateMask = 0  # Disable EcoQoS throttling
        kernel32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetProcessInformation(h_proc, 4, ctypes.byref(state), ctypes.sizeof(state))

        # 3. Disable console QuickEdit mode so accidental clicks into console don't freeze stdout
        h_stdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
            new_mode = (mode.value & ~0x0040) | 0x0080  # Remove ENABLE_QUICK_EDIT_MODE (0x40)
            kernel32.SetConsoleMode(h_stdin, new_mode)
    except Exception:
        pass


def _has_module(name: str) -> bool:
    """Case-insensitive check for installed module without triggering full DLL imports."""
    candidates = [name, name.lower(), name.upper(), name.capitalize()]
    if name.lower() == "openexr":
        candidates.append("OpenEXR")
    for candidate in candidates:
        try:
            if importlib.util.find_spec(candidate) is not None:
                return True
        except Exception:
            pass
    return False


def ensure_environment():
    """Fast non-blocking check using find_spec; only triggers targeted pip installs if packages are missing."""
    # 1. Fast check PyTorch with CUDA acceleration support
    torch_needs_install = False
    if not _has_module("torch"):
        torch_needs_install = True
    else:
        try:
            import torch
            if getattr(torch.version, "cuda", None) is None:
                print("[Warning] Installed PyTorch is CPU-only. Reinstalling with CUDA 12.8 support...")
                torch_needs_install = True
        except Exception:
            torch_needs_install = True

    if torch_needs_install:
        print("Installing PyTorch with CUDA support...")
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            "torch",
            "torchvision",
            "--index-url",
            "https://download.pytorch.org/whl/cu128",
        ])

    # 2. Fast check GUI and inference packages in milliseconds without importing them
    # Maps module name -> pip package name or URL
    required_modules = {
        "PySide6": "PySide6>=6.6.0",
        "qfluentwidgets": "PySide6-Fluent-Widgets>=1.6.0",
        "cv2": "opencv-python>=4.11",
        "numpy": "numpy>=1.26,<2",
        "huggingface_hub": "huggingface-hub>=0.36",
        "timm": "timm>=1.0",
        "transformers": "transformers>=4.57,<5",
        "einops": "einops>=0.8",
        "safetensors": "safetensors>=0.6",
        "PIL": "pillow>=11",
        "scipy": "scipy>=1.16",
        "tqdm": "tqdm>=4.67",
        "OpenEXR": "openexr",
        "pynvml": "nvidia-ml-py",
        "utils3d": "https://github.com/EasternJournalist/utils3d/archive/83bfa5bda008803f6521ce9547f94023b8afeddd.zip",
    }

    missing_packages = [
        pip_name
        for mod_name, pip_name in required_modules.items()
        if not _has_module(mod_name)
    ]

    if missing_packages:
        print(f"Installing missing package(s): {missing_packages}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_packages)


if __name__ == "__main__":
    optimize_windows_process()
    ensure_environment()
    try:
        from gui.backend.logger import setup_logging
        setup_logging()
    except Exception as e:
        print(f"[Warning] Could not initialize logger: {e}")
    from gui.app import main
    sys.exit(main())
