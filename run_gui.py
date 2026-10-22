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

    # 2. Check GUI requirements
    try:
        import PySide6
        import qfluentwidgets
        import huggingface_hub
    except ImportError:
        print("Required packages are missing. Installing requirements.txt...")
        req_file = ROOT_DIR / "requirements.txt"
        if req_file.is_file():
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(req_file)])


if __name__ == "__main__":
    ensure_environment()
    from gui.app import main
    sys.exit(main())
