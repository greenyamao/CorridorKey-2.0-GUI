"""Upstream CorridorKey 2.0 Engine Manager.

Manages the core CorridorKey 2.0 repository layer in ./engine/.
Handles initial clone/download, verification, and non-blocking update checks against GitHub.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Callable

APP_ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE_DIR = APP_ROOT / "engine"
UPSTREAM_REPO_URL = "https://github.com/nikopueringer/CorridorKey2.0.git"
UPSTREAM_API_COMMITS = "https://api.github.com/repos/nikopueringer/CorridorKey2.0/commits/master"
UPSTREAM_ZIP_URL = "https://github.com/nikopueringer/CorridorKey2.0/archive/refs/heads/master.zip"


class EngineManager:
    """Manages the isolated upstream CorridorKey 2.0 engine layer."""

    @staticmethod
    def get_engine_dir() -> Path:
        return ENGINE_DIR

    @classmethod
    def get_infer_script(cls) -> Optional[Path]:
        """Returns path to engine/infer.py if valid, otherwise None."""
        infer_py = ENGINE_DIR / "infer.py"
        corridorkey_pkg = ENGINE_DIR / "corridorkey"
        if infer_py.is_file() and corridorkey_pkg.is_dir():
            return infer_py
        return None

    @classmethod
    def is_engine_installed(cls) -> bool:
        installed = cls.get_infer_script() is not None
        if installed:
            cls.ensure_junctions()
        return installed

    @classmethod
    def ensure_junctions(cls) -> None:
        """Links root ./weights and ./vfms into ./engine/ via directory junctions/symlinks."""
        if not ENGINE_DIR.is_dir():
            return
        weights_dir = APP_ROOT / "weights"
        vfms_dir = APP_ROOT / "vfms"
        weights_dir.mkdir(parents=True, exist_ok=True)
        vfms_dir.mkdir(parents=True, exist_ok=True)

        for name, target in [("weights", weights_dir), ("vfms", vfms_dir)]:
            engine_link = ENGINE_DIR / name
            if not engine_link.exists():
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["cmd", "/c", "mklink", "/J", str(engine_link), str(target)],
                            capture_output=True,
                            timeout=5
                        )
                    else:
                        engine_link.symlink_to(target, target_is_directory=True)
                except Exception as e:
                    print(f"[EngineManager] Link creation error: {e}")

    @classmethod
    def get_local_commit_hash(cls) -> Optional[str]:
        """Returns short commit hash of the local engine git repo, if available."""
        if not (ENGINE_DIR / ".git").is_dir():
            return None
        try:
            res = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(ENGINE_DIR),
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return None

    @classmethod
    def check_for_updates(cls) -> Optional[Tuple[str, str]]:
        """
        Asynchronously checks if a newer commit exists in upstream repository.
        Returns (commit_hash, commit_message) if an update is available, else None.
        """
        local_hash = cls.get_local_commit_hash()
        
        # Check via GitHub API
        try:
            req = urllib.request.Request(
                UPSTREAM_API_COMMITS,
                headers={"User-Agent": "CorridorKey-Workbench-GUI"}
            )
            with urllib.request.urlopen(req, timeout=6) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    remote_sha = data.get("sha", "")
                    remote_short = remote_sha[:7]
                    msg = data.get("commit", {}).get("message", "").split("\n")[0]
                    
                    if local_hash and remote_short and not remote_sha.startswith(local_hash):
                        return (remote_short, msg)
        except Exception:
            pass

        return None

    @classmethod
    def install_or_update_engine(cls, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """Clones or updates the engine repository."""
        # 1. If git is installed and engine/.git exists: run git pull
        if (ENGINE_DIR / ".git").is_dir() and shutil.which("git"):
            try:
                if progress_callback:
                    progress_callback("Updating engine via git pull...")
                res = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=str(ENGINE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if res.returncode == 0:
                    if progress_callback:
                        progress_callback("Engine successfully updated!")
                    return True
            except Exception as e:
                print(f"[EngineManager] git pull failed: {e}")

        # 2. If engine is not installed, try git clone
        if not cls.is_engine_installed():
            if shutil.which("git"):
                try:
                    if progress_callback:
                        progress_callback("Cloning CorridorKey 2.0 repository...")
                    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
                    res = subprocess.run(
                        ["git", "clone", "--depth", "1", UPSTREAM_REPO_URL, str(ENGINE_DIR)],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if res.returncode == 0 and cls.is_engine_installed():
                        if progress_callback:
                            progress_callback("Engine successfully cloned!")
                        return True
                except Exception as e:
                    print(f"[EngineManager] git clone failed: {e}")

            # 3. Fallback: download ZIP from GitHub
            try:
                if progress_callback:
                    progress_callback("Downloading CorridorKey 2.0 source archive...")
                zip_path = APP_ROOT / "temp_engine.zip"
                urllib.request.urlretrieve(UPSTREAM_ZIP_URL, zip_path)

                if progress_callback:
                    progress_callback("Extracting engine files...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    # Extracts into a subfolder like CorridorKey2.0-master/
                    for member in zip_ref.namelist():
                        parts = member.split('/', 1)
                        if len(parts) > 1 and parts[1]:
                            target_file = ENGINE_DIR / parts[1]
                            if member.endswith('/'):
                                target_file.mkdir(parents=True, exist_ok=True)
                            else:
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                with zip_ref.open(member) as src, open(target_file, "wb") as dst:
                                    shutil.copyfileobj(src, dst)

                try:
                    zip_path.unlink()
                except Exception:
                    pass

                return cls.is_engine_installed()
            except Exception as e:
                print(f"[EngineManager] Archive download failed: {e}")
                return False

        return True
