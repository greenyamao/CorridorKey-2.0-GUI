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
)
from PySide6.QtGui import QFont, QCursor
from qfluentwidgets import FluentIcon as FI, Theme

from gui.backend.video_loader import ClipInfo, probe_clip, scan_directory_for_clips
from gui.styles.theme import (
    ACCENT_BLUE,
    ACCENT_CYAN,
    CORRIDOR_YELLOW,
    CORRIDOR_GREEN,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
)


def create_flat_card() -> QFrame:
    card = QFrame()
    card.setProperty("class", "flat-card")
    card.setStyleSheet("""
        QFrame.flat-card {
            background-color: #1A1A1E;
            border: 1px solid #28282E;
            border-radius: 8px;
        }
    """)
    return card


class MediaPanel(QWidget):
    """Media browser and queue in English with detailed Russian hover tooltips."""

    clip_selected = Signal(ClipInfo)
    queue_selected_requested = Signal(ClipInfo)
    queue_all_requested = Signal(list)
    start_queue_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(290)

        self.clips: List[ClipInfo] = []
        self.selected_clip: Optional[ClipInfo] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 1. Media Library Card
        media_card = create_flat_card()
        mc_layout = QVBoxLayout(media_card)
        mc_layout.setContentsMargins(10, 10, 10, 10)
        mc_layout.setSpacing(8)

        m_head = QHBoxLayout()
        lbl_m = QLabel("Clips")
        lbl_m.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        lbl_m.setToolTip("<b>Clips (Медиатека)</b><br>Список загруженных видеофайлов и секвенций кадров.<br>Кликните по клипу для выбора и настройки.")
        m_head.addWidget(lbl_m)
        m_head.addStretch()

        btn_add_f = QPushButton("+ File")
        btn_add_f.setIcon(FI.DOCUMENT.icon(Theme.DARK))
        btn_add_f.setIconSize(QSize(12, 12))
        btn_add_f.setProperty("class", "pill-btn")
        btn_add_f.setToolTip("<b>+ File (Добавить файл, Ctrl+O)</b><br>Открыть видеофайл (MP4, MOV, MKV, AVI) или первый кадр секвенции (EXR, PNG, JPG).")
        btn_add_f.clicked.connect(self._on_import_file)
        m_head.addWidget(btn_add_f)

        btn_add_dir = QPushButton("+ Folder")
        btn_add_dir.setIcon(FI.FOLDER.icon(Theme.DARK))
        btn_add_dir.setIconSize(QSize(12, 12))
        btn_add_dir.setProperty("class", "pill-btn")
        btn_add_dir.setToolTip("<b>+ Folder (Импорт папки, Ctrl+Shift+O)</b><br>Сканировать каталог на наличие видео или загрузить папку с секвенцией кадров.")
        btn_add_dir.clicked.connect(self._on_import_folder)
        m_head.addWidget(btn_add_dir)
        mc_layout.addLayout(m_head)

        # Scroll area for clips
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")

        self.clip_list_container = QWidget(self.scroll)
        self.clip_list_layout = QVBoxLayout(self.clip_list_container)
        self.clip_list_layout.setContentsMargins(0, 0, 0, 0)
        self.clip_list_layout.setSpacing(4)
        self.clip_list_layout.addStretch()

        self.scroll.setWidget(self.clip_list_container)
        mc_layout.addWidget(self.scroll, stretch=1)

        q_btn_row = QHBoxLayout()
        q_btn_row.setSpacing(6)

        self.btn_queue_selected = QPushButton("+ Queue Clip")
        self.btn_queue_selected.setProperty("class", "pill-btn")
        self.btn_queue_selected.setToolTip("<b>+ Queue Clip (Добавить клип в очередь)</b><br>Добавить выбранный клип в список очереди рендера.")
        self.btn_queue_selected.clicked.connect(self._on_queue_selected)
        q_btn_row.addWidget(self.btn_queue_selected)

        self.btn_queue_all = QPushButton("Queue All")
        self.btn_queue_all.setProperty("class", "pill-btn")
        self.btn_queue_all.setToolTip("<b>Queue All (Добавить все в очередь)</b><br>Отправить все клипы из списка в очередь рендера с текущими настройками.")
        self.btn_queue_all.clicked.connect(self._on_queue_all)
        q_btn_row.addWidget(self.btn_queue_all)

        mc_layout.addLayout(q_btn_row)

        layout.addWidget(media_card, stretch=3)

        # 2. Queue Card
        queue_card = create_flat_card()
        qc_layout = QVBoxLayout(queue_card)
        qc_layout.setContentsMargins(10, 10, 10, 10)
        qc_layout.setSpacing(6)

        q_head = QHBoxLayout()
        lbl_q = QLabel("Queue")
        lbl_q.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        lbl_q.setToolTip("<b>Queue (Очередь задач)</b><br>Список заданий для последовательного пакетного рендеринга CorridorKey.")
        q_head.addWidget(lbl_q)
        q_head.addStretch()

        btn_start_q = QPushButton("Start")
        btn_start_q.setIcon(FI.PLAY.icon(Theme.DARK))
        btn_start_q.setIconSize(QSize(11, 11))
        btn_start_q.setProperty("class", "pill-btn")
        btn_start_q.setToolTip("<b>Start (Запуск очереди)</b><br>Начать последовательную обработку всех заданий в очереди.")
        btn_start_q.clicked.connect(self.start_queue_requested.emit)
        q_head.addWidget(btn_start_q)

        btn_clear = QPushButton("Clear")
        btn_clear.setIcon(FI.DELETE.icon(Theme.DARK))
        btn_clear.setIconSize(QSize(11, 11))
        btn_clear.setStyleSheet(f"border: none; color: {TEXT_MUTED}; font-size: 11px; padding: 2px 4px; background: transparent;")
        btn_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_clear.setToolTip("<b>Clear (Очистить очередь)</b><br>Удалить все ожидающие задания из списка.")
        btn_clear.clicked.connect(self.clear_queue)
        q_head.addWidget(btn_clear)
        qc_layout.addLayout(q_head)

        self.q_scroll = QScrollArea(self)
        self.q_scroll.setWidgetResizable(True)
        self.q_scroll.setStyleSheet("border: none; background: transparent;")

        self.q_container = QWidget(self.q_scroll)
        self.q_layout = QVBoxLayout(self.q_container)
        self.q_layout.setContentsMargins(0, 0, 0, 0)
        self.q_layout.setSpacing(4)

        self.lbl_empty_queue = QLabel("Queue is empty")
        self.lbl_empty_queue.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 4px; border: none; background: transparent;")
        self.lbl_empty_queue.setToolTip("Очередь пуста. Добавьте клипы кнопкой 'Add to Queue' в панели Deliver.")
        self.q_layout.addWidget(self.lbl_empty_queue)
        self.q_layout.addStretch()

        self.q_scroll.setWidget(self.q_container)
        qc_layout.addWidget(self.q_scroll, stretch=1)

        layout.addWidget(queue_card, stretch=2)

    def add_clip(self, clip_path: str):
        clip = probe_clip(clip_path)
        if clip is not None:
            for existing in self.clips:
                if existing.path == clip.path:
                    self.select_clip(existing)
                    return
            self.clips.append(clip)
            row = self._create_clip_row(clip)
            self.clip_list_layout.insertWidget(self.clip_list_layout.count() - 1, row)
            self.select_clip(clip)

    def add_clips_batch(self, clips: List[ClipInfo]):
        for clip in clips:
            if not any(c.path == clip.path for c in self.clips):
                self.clips.append(clip)
                row = self._create_clip_row(clip)
                self.clip_list_layout.insertWidget(self.clip_list_layout.count() - 1, row)
        if self.clips and not self.selected_clip:
            self.select_clip(self.clips[0])

    def _create_clip_row(self, clip: ClipInfo) -> QFrame:
        row = QFrame()
        row.setObjectName("clipRow")
        row.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        row.setFixedHeight(44)
        row.clip = clip

        hint_status = f"<br>Alpha Hint: найден ({os.path.basename(clip.discovered_hint_path)})" if clip.discovered_hint_path else ""
        row.setToolTip(
            f"<b>{clip.name}</b><br>"
            f"Путь: {clip.path}<br>"
            f"Разрешение: {clip.width}x{clip.height}<br>"
            f"Кадров: {clip.total_frames} ({clip.fps:.1f} fps)"
            f"{hint_status}<br>"
            f"Кликните для выбора клипа."
        )

        rl = QVBoxLayout(row)
        rl.setContentsMargins(10, 5, 10, 5)
        rl.setSpacing(2)

        # Top row: Clip Name
        name_lbl = QLabel(clip.name)
        name_lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 600; border: none; background: transparent;")
        rl.addWidget(name_lbl)

        # Bottom row: Metadata + Hint Badge
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(6)

        info_lbl = QLabel(f"{clip.total_frames} frames  ·  {clip.resolution_label}  ·  {clip.fps:.0f} fps")
        info_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        bot_row.addWidget(info_lbl, stretch=1)

        if clip.discovered_hint_path:
            hint_badge = QLabel("HINT")
            hint_badge.setStyleSheet(f"color: {CORRIDOR_GREEN}; font-size: 9px; font-weight: 700; border: none; background: transparent;")
            bot_row.addWidget(hint_badge)

        rl.addLayout(bot_row)

        row.mousePressEvent = lambda e: self.select_clip(clip)
        self._update_row_style(row, is_selected=False)
        return row

    def _update_row_style(self, row: QFrame, is_selected: bool):
        if is_selected:
            row.setStyleSheet(f"""
                QFrame#clipRow {{
                    background-color: #222228;
                    border: 1px solid {ACCENT_BLUE};
                    border-radius: 6px;
                }}
                QFrame#clipRow QLabel {{
                    border: none;
                    background: transparent;
                }}
            """)
        else:
            row.setStyleSheet("""
                QFrame#clipRow {
                    background-color: #17171B;
                    border: 1px solid #28282E;
                    border-radius: 6px;
                }
                QFrame#clipRow:hover {
                    background-color: #1E1E24;
                    border: 1px solid #383842;
                }
                QFrame#clipRow QLabel {
                    border: none;
                    background: transparent;
                }
            """)

    def select_clip(self, clip: ClipInfo):
        self.selected_clip = clip
        for i in range(self.clip_list_layout.count() - 1):
            w = self.clip_list_layout.itemAt(i).widget()
            if isinstance(w, QFrame) and hasattr(w, "clip"):
                self._update_row_style(w, is_selected=(w.clip.path == clip.path))
        self.clip_selected.emit(clip)

    def add_queue_item(self, task_id: str, title: str, status: str = "Queued"):
        self.lbl_empty_queue.hide()
        item = QueueItemWidget(task_id, title, status)
        self.q_layout.insertWidget(self.q_layout.count() - 1, item)
        return item

    def clear_queue(self):
        while self.q_layout.count() > 1:
            item = self.q_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lbl_empty_queue.show()

    def _on_import_file(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Open Video or First Frame of Sequence",
            "",
            "Media Files (*.mp4 *.mov *.avi *.mkv *.exr *.png *.jpg);;All Files (*.*)",
        )
        if fpath:
            self.add_clip(fpath)

    def _on_import_folder(self):
        dpath = QFileDialog.getExistingDirectory(
            self,
            "Import Directory with Media or Frame Sequence",
            "",
        )
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

    def _on_queue_selected(self):
        if self.selected_clip is not None:
            self.queue_selected_requested.emit(self.selected_clip)
        elif self.clips:
            self.queue_selected_requested.emit(self.clips[0])

    def _on_queue_all(self):
        if self.clips:
            self.queue_all_requested.emit(self.clips)


class QueueItemWidget(QFrame):
    """Queue card showing clip name and progress."""

    def __init__(self, task_id: str, title: str, status: str = "Queued", parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.setObjectName("queueItem")
        self.setFixedHeight(36)
        self.setStyleSheet("""
            QFrame#queueItem {
                background-color: #17171B;
                border: 1px solid #28282E;
                border-radius: 4px;
            }
            QFrame#queueItem QLabel {
                border: none;
                background: transparent;
            }
        """)
        self.setToolTip(f"<b>Задание рендера</b><br>Клип: {title}<br>ID задачи: {task_id}<br>Статус: {status}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)

        top = QHBoxLayout()
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("color: #EEEEEE; font-size: 11px; font-weight: 500;")
        top.addWidget(self.title_lbl, stretch=1)

        self.status_label = QLabel(status)
        self.status_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        top.addWidget(self.status_label)
        layout.addLayout(top)

        self.pbar = QProgressBar()
        self.pbar.setFixedHeight(2)
        self.pbar.setTextVisible(False)
        self.pbar.setRange(0, 100)
        self.pbar.setValue(0)
        self.pbar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #222228;
                border: none;
                border-radius: 1px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_BLUE};
                border-radius: 1px;
            }}
        """)
        layout.addWidget(self.pbar)
