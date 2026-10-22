from __future__ import annotations

import os
import sys
import logging
import faulthandler
from pathlib import Path
from PySide6.QtCore import qInstallMessageHandler, QtMsgType

APP_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_FILE = APP_ROOT / "corridorkey_gui.log"
CRASH_LOG_FILE = APP_ROOT / "corridorkey_crash.log"

logger = logging.getLogger("CorridorKeyGUI")


def setup_logging():
    """Initializes multi-sink logging to console and file, with crash handlers and Qt log hooks."""
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s:%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # 2. File handler (appends to corridorkey_gui.log)
    try:
        fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception as e:
        print(f"[Logger] Could not create file handler: {e}")

    # 3. Low-level crash reporter (faulthandler) for fatal Windows/C++ faults
    try:
        crash_fp = open(CRASH_LOG_FILE, "a", encoding="utf-8")
        faulthandler.enable(file=crash_fp, all_threads=True)
    except Exception as e:
        print(f"[Logger] Could not enable faulthandler: {e}")

    # 4. Global unhandled Python exception hook
    def exception_hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("UNHANDLED EXCEPTION:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = exception_hook

    # 5. Qt message redirection hook
    def qt_message_handler(mode, context, message):
        category = context.category if context and context.category else "Qt"
        if mode == QtMsgType.QtDebugMsg:
            logger.debug("[%s] %s", category, message)
        elif mode == QtMsgType.QtInfoMsg:
            logger.info("[%s] %s", category, message)
        elif mode == QtMsgType.QtWarningMsg:
            # Filter non-critical benign QFluentWidgets tips
            if "QFluentWidgets Pro" in message:
                return
            logger.warning("[%s] %s", category, message)
        elif mode == QtMsgType.QtCriticalMsg:
            logger.error("[%s] %s", category, message)
        elif mode == QtMsgType.QtFatalMsg:
            logger.critical("[%s] FATAL: %s", category, message)

    qInstallMessageHandler(qt_message_handler)
    logger.info("CorridorKey 2.0 GUI logging initialized. Log file: %s", LOG_FILE)
    return logger
