#!/usr/bin/env python3
"""Entry point for CorridorKey 2.0 Workbench GUI with automatic dependency setup."""

import sys
import subprocess
from pathlib import Path

# Ensure repo root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def ensure_environment():
    """Checks and automatically installs missing packages before importing the GUI."""
    # 1. Check PyTorch with CUDA
    try:
        import torch
    except ImportError:
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

    # 2. Check all GUI and inference engine requirements
    missing = []
    for pkg in ["PySide6", "qfluentwidgets", "huggingface_hub", "timm", "transformers", "einops", "utils3d"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"Missing required packages: {missing}. Installing requirements.txt...")
        req_file = ROOT_DIR / "requirements.txt"
        if req_file.is_file():
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])


if __name__ == "__main__":
    ensure_environment()
    try:
        from gui.backend.logger import setup_logging
        setup_logging()
    except Exception as e:
        print(f"[Warning] Could not initialize logger: {e}")
    from gui.app import main
    sys.exit(main())
