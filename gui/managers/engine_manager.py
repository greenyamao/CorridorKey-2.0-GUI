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
        custom_file = APP_ROOT / ".engine_path"
        if custom_file.is_file():
            try:
                p = Path(custom_file.read_text("utf-8").strip())
                if (p / "infer.py").is_file():
                    return p
            except Exception:
                pass
        return ENGINE_DIR

    @classmethod
    def get_infer_script(cls) -> Optional[Path]:
        """Returns path to engine/infer.py if valid, otherwise None."""
        engine_path = cls.get_engine_dir()
        infer_py = engine_path / "infer.py"
        corridorkey_pkg = engine_path / "corridorkey"
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
    def link_existing_engine(cls, source_folder: Path | str) -> bool:
        """Links an existing CorridorKey 2.0 folder into ./engine/ or saves to .engine_path."""
        src = Path(source_folder).resolve()
        if not (src / "infer.py").is_file():
            return False

        # 1. Save path to .engine_path
        try:
            (APP_ROOT / ".engine_path").write_text(str(src), encoding="utf-8")
        except Exception:
            pass

        # 2. Try creating directory junction ./engine -> src
        if not ENGINE_DIR.exists() and not ENGINE_DIR.is_symlink():
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["cmd", "/c", "mklink", "/J", str(ENGINE_DIR), str(src)],
                        capture_output=True,
                        timeout=5
                    )
                else:
                    ENGINE_DIR.symlink_to(src, target_is_directory=True)
            except Exception:
                pass

        cls.ensure_junctions()
        return True

    @classmethod
    def ensure_junctions(cls) -> None:
        """Links root ./weights and ./vfms into the engine directory."""
        engine_dir = cls.get_engine_dir()
        if not engine_dir.is_dir():
            return
        weights_dir = APP_ROOT / "weights"
        vfms_dir = APP_ROOT / "vfms"
        weights_dir.mkdir(parents=True, exist_ok=True)
        vfms_dir.mkdir(parents=True, exist_ok=True)

        for name, target in [("weights", weights_dir), ("vfms", vfms_dir)]:
            engine_link = engine_dir / name
            
            # Check if engine_link is already a valid junction or symlink
            is_linked = False
            try:
                os.readlink(engine_link)
                is_linked = True
            except OSError:
                if engine_link.is_symlink():
                    is_linked = True
            except Exception:
                pass

            if is_linked:
                continue

            # If it's a directory containing only .gitkeep or empty, safely replace with junction
            if engine_link.is_dir():
                real_files = [f for f in engine_link.rglob("*") if f.is_file() and f.name != ".gitkeep"]
                if not real_files:
                    try:
                        try:
                            os.rmdir(engine_link)
                        except OSError:
                            shutil.rmtree(engine_link)
                    except Exception as e:
                        print(f"[EngineManager] Could not remove empty dir {engine_link}: {e}")

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
    def install_or_update_engine(cls, progress_callback: Optional[Callable[..., None]] = None) -> bool:
        """Clones or updates the engine repository with flexible progress reporting."""
        def _notify(pct: float, msg: str):
            if progress_callback:
                try:
                    progress_callback(pct, msg)
                except TypeError:
                    progress_callback(msg)

        # 1. If git is installed and engine/.git exists: run git pull
        if (ENGINE_DIR / ".git").is_dir() and shutil.which("git"):
            try:
                _notify(10.0, "Updating engine via git pull...")
                res = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=str(ENGINE_DIR),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if res.returncode == 0:
                    _notify(100.0, "Engine successfully updated!")
                    return True
            except Exception as e:
                print(f"[EngineManager] git pull failed: {e}")

        # 2. If engine is not installed, try git clone
        if not cls.is_engine_installed():
            if shutil.which("git"):
                try:
                    _notify(10.0, "Cloning CorridorKey 2.0 repository...")
                    ENGINE_DIR.mkdir(parents=True, exist_ok=True)
                    res = subprocess.run(
                        ["git", "clone", "--depth", "1", UPSTREAM_REPO_URL, str(ENGINE_DIR)],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )
                    if res.returncode == 0 and cls.is_engine_installed():
                        _notify(100.0, "Engine successfully cloned!")
                        return True
                except Exception as e:
                    print(f"[EngineManager] git clone failed: {e}")

            # 3. Fallback: download ZIP from GitHub
            try:
                _notify(10.0, "Downloading CorridorKey 2.0 source archive...")
                zip_path = APP_ROOT / "temp_engine.zip"

                def _reporthook(block_num, block_size, total_size):
                    if total_size > 0:
                        pct = min(70.0, 10.0 + (block_num * block_size / total_size) * 60.0)
                        dl_mb = (block_num * block_size) / (1024 * 1024)
                        tot_mb = total_size / (1024 * 1024)
                        _notify(pct, f"Downloading Engine: {dl_mb:.1f} / {tot_mb:.1f} MB")

                urllib.request.urlretrieve(UPSTREAM_ZIP_URL, zip_path, reporthook=_reporthook)

                _notify(75.0, "Extracting repository files into ./engine/...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    # Extracts into a subfolder like CorridorKey2.0-master/
                    namelist = zip_ref.namelist()
                    tot_members = len(namelist)
                    for i, member in enumerate(namelist):
                        parts = member.split('/', 1)
                        if len(parts) > 1 and parts[1]:
                            target_file = ENGINE_DIR / parts[1]
                            if member.endswith('/'):
                                target_file.mkdir(parents=True, exist_ok=True)
                            else:
                                target_file.parent.mkdir(parents=True, exist_ok=True)
                                with zip_ref.open(member) as src, open(target_file, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                        if i % 10 == 0 and tot_members > 0:
                            pct = 75.0 + (i / tot_members) * 23.0
                            _notify(pct, f"Extracting files ({i}/{tot_members})...")

                try:
                    zip_path.unlink()
                except Exception:
                    pass

                _notify(100.0, "Engine extracted successfully.")
                return cls.is_engine_installed()
            except Exception as e:
                print(f"[EngineManager] Archive download failed: {e}")
                return False

        return True
