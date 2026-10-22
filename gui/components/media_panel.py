from __future__ import annotations

import os
from typing import Optional, List, Dict
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFrame,
    QFileDialog,
    QProgressBar,
    QSizePolicy,
)
from PySide6.QtGui import QFont, QCursor, QPainter, QColor
from qfluentwidgets import FluentIcon as FI, Theme

from gui.backend.video_loader import ClipInfo, probe_clip, scan_directory_for_clips
from gui.styles.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    CORRIDOR_GREEN,
    TEXT_MUTED,
)


class ElidedLabel(QLabel):
    """A QLabel that gracefully truncates and elides overflowing text with '...' in the middle."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full_text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(30)

    def setText(self, text: str):
        self._full_text = text
        super().setText(text)
        self.update()

    def text(self) -> str:
        return self._full_text

    def paintEvent(self, event):
        painter = QPainter(self)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideMiddle, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), self.alignment() | Qt.AlignmentFlag.AlignVCenter, elided)


class ClipRow(QFrame):
    """Individual clip card with thumbnail, metadata, hint badge, and real-time status/progress."""

    def __init__(self, clip: ClipInfo, on_select_cb, parent=None):
        super().__init__(parent)
        self.clip = clip
        self._on_select = on_select_cb
        self.setObjectName("clipRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(54)

        hint_status = f"<br>Alpha Hint: attached ({os.path.basename(clip.discovered_hint_path)})" if clip.discovered_hint_path else ""
        self.setToolTip(
            f"<b>{clip.name}</b><br>"
            f"Path: {clip.path}<br>"
            f"Resolution: {clip.width}x{clip.height}<br>"
            f"Frames: {clip.total_frames} ({clip.fps:.1f} fps)"
            f"{hint_status}<br>"
            f"Click to select clip."
        )

        rl = QVBoxLayout(self)
        rl.setContentsMargins(10, 5, 10, 5)
        rl.setSpacing(3)

        # Top row: Name + Status Badge
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(6)

        self.name_lbl = ElidedLabel(clip.name)
        self.name_lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        top_row.addWidget(self.name_lbl, stretch=1)

        self.status_badge = QLabel("Ready")
        self.status_badge.setStyleSheet(
            "color: #94A3B8; font-size: 10px; font-weight: 700; background: #202026; "
            "border: 1px solid #303038; border-radius: 3px; padding: 1px 5px;"
        )
        top_row.addWidget(self.status_badge)
        rl.addLayout(top_row)

        # Bottom row: Meta + Hint Badge
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(6)

        self.info_lbl = QLabel(f"{clip.total_frames}f | {clip.resolution_label} | {clip.fps:.0f}fps")
        self.info_lbl.setStyleSheet("color: #64748B; font-size: 10px; border: none; background: transparent;")
        bot_row.addWidget(self.info_lbl, stretch=1)

        if clip.discovered_hint_path:
            self.hint_badge = QLabel("HINT")
            self.hint_badge.setStyleSheet("color: #10B981; font-size: 9px; font-weight: 700; border: none; background: transparent;")
            bot_row.addWidget(self.hint_badge)

        rl.addLayout(bot_row)

        # Embedded Progress bar (visible during active inference)
        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(3)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setStyleSheet("""
            QProgressBar { background: #222228; border: none; border-radius: 1px; }
            QProgressBar::chunk { background: #00D2FF; border-radius: 1px; }
        """)
        self.pbar.hide()
        rl.addWidget(self.pbar)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self.clip)
        super().mousePressEvent(event)

    def set_status(self, status: str, pct: float = -1.0):
        s_lower = status.lower()
        if "render" in s_lower or "process" in s_lower:
            self.status_badge.setText(f"{int(pct)}%" if pct >= 0 else "Rendering")
            self.status_badge.setStyleSheet(
                "color: #00D2FF; font-weight: 700; background: #12222E; "
                "border: 1px solid #00D2FF; border-radius: 3px; padding: 1px 5px;"
            )
            self.pbar.show()
            if pct >= 0:
                self.pbar.setValue(int(pct))
        elif "done" in s_lower or "complete" in s_lower:
            self.status_badge.setText("Done")
            self.status_badge.setStyleSheet(
                "color: #10B981; font-weight: 700; background: #12281C; "
                "border: 1px solid #10B981; border-radius: 3px; padding: 1px 5px;"
            )
            self.pbar.hide()
        elif "error" in s_lower or "fail" in s_lower:
            self.status_badge.setText("Error")
            self.status_badge.setStyleSheet(
                "color: #EF4444; font-weight: 700; background: #281418; "
                "border: 1px solid #EF4444; border-radius: 3px; padding: 1px 5px;"
            )
            self.pbar.hide()
        elif "queued" in s_lower:
            self.status_badge.setText("Queued")
            self.status_badge.setStyleSheet(
                "color: #38BDF8; font-weight: 700; background: #16202A; "
                "border: 1px solid #38BDF8; border-radius: 3px; padding: 1px 5px;"
            )
            self.pbar.hide()
        else:
            self.status_badge.setText("Ready")
            self.status_badge.setStyleSheet(
                "color: #94A3B8; font-size: 10px; font-weight: 700; background: #202026; "
                "border: 1px solid #303038; border-radius: 3px; padding: 1px 5px;"
            )
            self.pbar.hide()

    def set_selected(self, selected: bool):
        if selected:
            self.setStyleSheet(f"""
                QFrame#clipRow {{
                    background-color: #22222A;
                    border: 1px solid {ACCENT_BLUE};
                    border-radius: 6px;
                }}
            """)
        else:
            self.setStyleSheet("""
                QFrame#clipRow {
                    background-color: #17171B;
                    border: 1px solid #28282E;
                    border-radius: 6px;
                }
                QFrame#clipRow:hover {
                    background-color: #1E1E24;
                    border: 1px solid #383842;
                }
            """)


class MediaPanel(QWidget):
    """
    Unified Media Library and Batch Processing Panel.
    Eliminates duplicated queues, redundant copy steps, and conflicting render buttons.
    """

    clip_selected = Signal(ClipInfo)
    render_all_requested = Signal()
    stop_batch_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(290)

        self.clips: List[ClipInfo] = []
        self.selected_clip: Optional[ClipInfo] = None
        self._clip_rows: Dict[str, ClipRow] = {}
        self._is_batch_running: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Single Flat Container
        container = QFrame()
        container.setObjectName("mediaContainer")
        container.setStyleSheet("""
            QFrame#mediaContainer {
                background-color: #16161A;
                border: 1px solid #28282E;
                border-radius: 8px;
            }
        """)
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(10, 10, 10, 10)
        c_layout.setSpacing(8)

        # 1. Header Row
        head_row = QHBoxLayout()
        self.lbl_title = QLabel("Clips (0)")
        self.lbl_title.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        self.lbl_title.setToolTip("<b>Clips</b><br>Imported video files and frame sequences for processing.")
        head_row.addWidget(self.lbl_title)
        head_row.addStretch()

        btn_add_f = QPushButton("+ File")
        btn_add_f.setIcon(FI.DOCUMENT.icon(Theme.DARK))
        btn_add_f.setIconSize(QSize(12, 12))
        btn_add_f.setProperty("class", "pill-btn")
        btn_add_f.setToolTip("<b>+ File (Ctrl+O)</b><br>Open video file (MP4, MOV, MKV, AVI) or first frame of an image sequence.")
        btn_add_f.clicked.connect(self._on_import_file)
        head_row.addWidget(btn_add_f)

        btn_add_dir = QPushButton("+ Folder")
        btn_add_dir.setIcon(FI.FOLDER.icon(Theme.DARK))
        btn_add_dir.setIconSize(QSize(12, 12))
        btn_add_dir.setProperty("class", "pill-btn")
        btn_add_dir.setToolTip("<b>+ Folder (Ctrl+Shift+O)</b><br>Scan folder for videos or load an image sequence directory.")
        btn_add_dir.clicked.connect(self._on_import_folder)
        head_row.addWidget(btn_add_dir)

        btn_clear = QPushButton()
        btn_clear.setIcon(FI.DELETE.icon(Theme.DARK))
        btn_clear.setIconSize(QSize(12, 12))
        btn_clear.setFixedSize(24, 24)
        btn_clear.setStyleSheet("QPushButton { background-color: #202026; border: 1px solid #303038; border-radius: 4px; } QPushButton:hover { background-color: #2A2A34; }")
        btn_clear.setToolTip("<b>Clear All</b><br>Remove all clips from the project.")
        btn_clear.clicked.connect(self.clear_clips)
        head_row.addWidget(btn_clear)

        c_layout.addLayout(head_row)

        # 2. Scroll Area for Clips
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("border: none; background: transparent;")

        self.list_widget = QWidget(self.scroll)
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)

        self.lbl_empty = QLabel("No clips added.\nClick '+ File', '+ Folder', or drag & drop video here.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 20px; border: none; background: transparent;")
        self.list_layout.addWidget(self.lbl_empty)
        self.list_layout.addStretch()

        self.scroll.setWidget(self.list_widget)
        c_layout.addWidget(self.scroll, stretch=1)

        # 3. Footer Batch Action
        self.btn_batch = QPushButton("Render All Clips")
        self.btn_batch.setIcon(FI.PLAY.icon(color=QColor("#FFFFFF")))
        self.btn_batch.setIconSize(QSize(12, 12))
        self.btn_batch.setProperty("class", "pill-btn")
        self.btn_batch.setFixedHeight(30)
        self.btn_batch.setStyleSheet("""
            QPushButton {
                background-color: #202028;
                border: 1px solid #38BDF8;
                color: #FFFFFF;
                font-weight: 700;
                font-size: 11px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0284C7;
                border-color: #38BDF8;
            }
        """)
        self.btn_batch.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_batch.setToolTip("<b>Render All Clips</b><br>Sequentially process all clips in the project.")
        self.btn_batch.clicked.connect(self._on_batch_btn_clicked)
        self.btn_batch.setEnabled(False)
        c_layout.addWidget(self.btn_batch)

        layout.addWidget(container)

    def add_clip(self, clip_path: str):
        clip = probe_clip(clip_path)
        if clip is not None:
            for existing in self.clips:
                if existing.path == clip.path:
                    self.select_clip(existing)
                    return
            self.clips.append(clip)
            self._render_clip_row(clip)
            self.select_clip(clip)
            self._update_header_and_buttons()

    def add_clips_batch(self, clips: List[ClipInfo]):
        for clip in clips:
            if not any(c.path == clip.path for c in self.clips):
                self.clips.append(clip)
                self._render_clip_row(clip)
        if self.clips and not self.selected_clip:
            self.select_clip(self.clips[0])
        self._update_header_and_buttons()

    def _render_clip_row(self, clip: ClipInfo):
        self.lbl_empty.hide()
        row = ClipRow(clip, on_select_cb=self.select_clip)
        self._clip_rows[clip.path] = row
        # Insert before bottom stretch
        self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def select_clip(self, clip: ClipInfo):
        self.selected_clip = clip
        for path, row in self._clip_rows.items():
            row.set_selected(path == clip.path)
        self.clip_selected.emit(clip)

    def set_clip_status(self, clip_path: str, status: str, pct: float = -1.0):
        if clip_path in self._clip_rows:
            self._clip_rows[clip_path].set_status(status, pct)

    def set_batch_running(self, running: bool):
        self._is_batch_running = running
        if running:
            self.btn_batch.setText("Stop Batch")
            self.btn_batch.setIcon(FI.CLOSE.icon(color=QColor("#FFFFFF")))
            self.btn_batch.setStyleSheet("""
                QPushButton {
                    background-color: #7F1D1D;
                    border: 1px solid #EF4444;
                    color: #FFFFFF;
                    font-weight: 700;
                    font-size: 11px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #991B1B;
                }
            """)
        else:
            self.btn_batch.setText("Render All Clips")
            self.btn_batch.setIcon(FI.PLAY.icon(color=QColor("#FFFFFF")))
            self.btn_batch.setStyleSheet("""
                QPushButton {
                    background-color: #202028;
                    border: 1px solid #38BDF8;
                    color: #FFFFFF;
                    font-weight: 700;
                    font-size: 11px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #0284C7;
                    border-color: #38BDF8;
                }
            """)

    def _on_batch_btn_clicked(self):
        if self._is_batch_running:
            self.stop_batch_requested.emit()
        else:
            self.render_all_requested.emit()

    def clear_clips(self):
        self.clips.clear()
        self.selected_clip = None
        for row in self._clip_rows.values():
            row.deleteLater()
        self._clip_rows.clear()
        self.lbl_empty.show()
        self._update_header_and_buttons()

    def _update_header_and_buttons(self):
        n = len(self.clips)
        self.lbl_title.setText(f"Clips ({n})")
        self.btn_batch.setEnabled(n > 0)

    def _on_import_file(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video or Image Sequence",
            "",
            "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;Images (*.exr *.png *.jpg *.jpeg *.tif *.tiff);;All Files (*.*)",
        )
        if fpath:
            self.add_clip(fpath)

    def _on_import_folder(self):
        dpath = QFileDialog.getExistingDirectory(self, "Select Folder Containing Clips or Image Sequences")
        if dpath:
            single = probe_clip(dpath)
            if single and single.is_frame_dir:
                self.add_clip(dpath)
            else:
                found = scan_directory_for_clips(dpath)
                if found:
                    self.add_clips_batch(found)
                elif single:
                    self.add_clip(dpath)
