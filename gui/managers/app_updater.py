"""GUI Application Auto-Updater.

Checks for new commits pushed to https://github.com/greenyamao/CorridorKey-2.0-GUI
and allows updating via Git or direct GitHub zip archive with automatic restart.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional, Tuple, Callable

APP_ROOT = Path(__file__).resolve().parent.parent.parent
GUI_REPO_URL = "https://github.com/greenyamao/CorridorKey-2.0-GUI.git"
GUI_API_COMMITS = "https://api.github.com/repos/greenyamao/CorridorKey-2.0-GUI/commits/main"
GUI_ZIP_URL = "https://github.com/greenyamao/CorridorKey-2.0-GUI/archive/refs/heads/main.zip"


class AppUpdater:
    """Manages updates for the CorridorKey Workbench GUI itself."""

    @staticmethod
    def get_local_commit() -> Optional[str]:
        """Returns the local commit hash of this repository, if available."""
        if (APP_ROOT / ".git").is_dir():
            try:
                res = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=str(APP_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    return res.stdout.strip()
            except Exception:
                pass

        # Fallback to .version file if present
        version_file = APP_ROOT / ".version"
        if version_file.is_file():
            try:
                return version_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return None

    _latest_remote_sha: Optional[str] = None

    @classmethod
    def check_for_update(cls) -> Optional[Tuple[str, str]]:
        """
        Queries GitHub API to check if a newer commit is available.
        Returns (short_sha, commit_message) if newer commit exists, otherwise None.
        """
        local_sha = cls.get_local_commit()
        try:
            req = urllib.request.Request(
                GUI_API_COMMITS,
                headers={"User-Agent": "CorridorKey-Workbench-GUI-Updater"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    remote_sha = data.get("sha", "")
                    short_sha = remote_sha[:7]
                    msg = data.get("commit", {}).get("message", "").split("\n")[0]
                    cls._latest_remote_sha = remote_sha

                    if local_sha:
                        if not remote_sha.startswith(local_sha):
                            return (short_sha, msg)
                    elif remote_sha:
                        # Fresh ZIP download without .git or .version.
                        # Since the user just downloaded the latest main archive from GitHub,
                        # record remote_sha into .version to prevent infinite auto-restart loops!
                        try:
                            (APP_ROOT / ".version").write_text(remote_sha, encoding="utf-8")
                        except Exception:
                            pass
                        return None
        except Exception:
            pass
        return None

    @classmethod
    def update_gui(cls, progress_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Updates the GUI repository via git pull or GitHub archive download.
        """
        # 1. If .git exists and git is installed: git pull
        if (APP_ROOT / ".git").is_dir() and shutil.which("git"):
            try:
                if progress_callback:
                    progress_callback("Pulling latest GUI changes via Git...")
                res = subprocess.run(
                    ["git", "pull", "--ff-only", "origin", "main"],
                    cwd=str(APP_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if res.returncode == 0:
                    return True
                # Fallback fetch and reset if local tree is clean
                subprocess.run(["git", "fetch", "origin", "main"], cwd=str(APP_ROOT), capture_output=True, timeout=30)
                res_reset = subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=str(APP_ROOT), capture_output=True, timeout=10)
                if res_reset.returncode == 0:
                    return True
            except Exception as e:
                print(f"[AppUpdater] Git update error: {e}")

        # 2. Fallback: Download ZIP from GitHub and replace GUI files
        try:
            if progress_callback:
                progress_callback("Downloading GUI update archive from GitHub...")
            zip_tmp = APP_ROOT / "gui_update.zip"
            urllib.request.urlretrieve(GUI_ZIP_URL, zip_tmp)

            if progress_callback:
                progress_callback("Extracting updated files...")

            with zipfile.ZipFile(zip_tmp, 'r') as zip_ref:
                for member in zip_ref.namelist():
                    # Format: CorridorKey-2.0-GUI-main/...
                    parts = member.split('/', 1)
                    if len(parts) > 1 and parts[1]:
                        rel_path = parts[1]
                        # Only update GUI source files, never touch engine or weights
                        if any(rel_path.startswith(prefix) for prefix in ("engine", "weights", "vfms", "bin")):
                            continue

                        target_path = APP_ROOT / rel_path
                        if member.endswith('/'):
                            target_path.mkdir(parents=True, exist_ok=True)
                        else:
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            with zip_ref.open(member) as src, open(target_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)

            try:
                zip_tmp.unlink()
            except Exception:
                pass

            # Persist the latest updated commit hash into .version
            try:
                if cls._latest_remote_sha:
                    (APP_ROOT / ".version").write_text(cls._latest_remote_sha, encoding="utf-8")
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"[AppUpdater] Archive update error: {e}")
            return False

    @staticmethod
    def restart_application() -> None:
        """Restarts the running Python GUI application."""
        from PySide6.QtWidgets import QApplication
        python_exe = sys.executable
        args = [python_exe] + sys.argv
        subprocess.Popen(args, cwd=str(APP_ROOT))
        QApplication.quit()
