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


def ensure_environment():
    """Fast non-blocking check using find_spec; only triggers pip if packages are truly missing."""
    # 1. Fast check PyTorch without slow DLL initialization
    if importlib.util.find_spec("torch") is None:
        print("PyTorch is not installed. Installing PyTorch with CUDA support...")
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
    required = ["PySide6", "qfluentwidgets", "huggingface_hub", "timm", "transformers", "einops", "utils3d", "openexr"]
    missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]

    if missing:
        print(f"Missing required packages: {missing}. Installing requirements.txt...")
        req_file = ROOT_DIR / "requirements.txt"
        if req_file.is_file():
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])


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
