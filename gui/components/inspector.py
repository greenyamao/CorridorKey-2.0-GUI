from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QSize, QPoint, QEvent, QSettings
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QLineEdit,
    QFileDialog,
    QScrollArea,
    QFrame,
)
from PySide6.QtGui import QFont, QCursor, QColor, QMouseEvent
from qfluentwidgets import (
    FluentIcon as FI,
    Theme,
    CheckBox,
    Slider,
    ComboBox,
)

from gui.backend.video_loader import ClipInfo
from gui.backend.system_monitor import calculate_clip_vram_estimate, get_gpu_info, get_disk_free_gb
from gui.backend.render_worker import RenderTask
from gui.styles.theme import (
    ACCENT_BLUE,
    CORRIDOR_YELLOW,
    CORRIDOR_GREEN,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_MUTED,
)


def create_section_header(title: str, tooltip: str = "") -> QWidget:
    """Helper to create a flat studio section header with an accent pip."""
    w = QWidget()
    w.setStyleSheet("background: transparent; border: none;")
    hl = QHBoxLayout(w)
    hl.setContentsMargins(0, 2, 0, 0)
    hl.setSpacing(6)

    pip = QFrame()
    pip.setFixedSize(3, 11)
    pip.setStyleSheet(f"background-color: {ACCENT_BLUE}; border-radius: 1px;")
    hl.addWidget(pip)

    lbl = QLabel(title.upper())
    lbl.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
    if tooltip:
        lbl.setToolTip(tooltip)
        w.setToolTip(tooltip)
    hl.addWidget(lbl, stretch=1)
    return w


def create_separator() -> QFrame:
    """Subtle flat separator line between sections."""
    sep = QFrame()
    sep.setFixedHeight(1)
    sep.setStyleSheet("background-color: #222228; border: none;")
    return sep


class StudioSlider(Slider):
    """
    Precision Fluent Slider that:
    1. Strictly requires Left Mouse Button to be actively pressed down to change value.
       Eliminates phantom jumps and accidental movements when the mouse cursor hovers over the slider.
    2. Ignores mouse wheel scrolling so the parent scroll area scrolls smoothly without altering settings.
    3. Handles knob dragging cleanly via internal event filtering.
    """
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent=parent)
        self.setMouseTracking(False)
        self._is_pressed = False
        if hasattr(self, 'handle') and self.handle:
            self.handle.setMouseTracking(False)
            self.handle.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == getattr(self, 'handle', None):
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._is_pressed = True
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._is_pressed = False
            elif event.type() == QEvent.Type.MouseMove:
                if not (self._is_pressed and (event.buttons() & Qt.MouseButton.LeftButton)):
                    return True  # Block hover movement on handle
                delta = event.position().x() - self.handle.width() / 2
                new_x = self.handle.x() + delta
                val = self._posToValue(QPoint(int(new_x), int(self.height() / 2)))
                self.setValue(val)
                self.sliderMoved.emit(self.value())
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_pressed = True
            super().mousePressEvent(event)
        else:
            event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent):
        # Strictly require LeftButton to be actively held down!
        if self._is_pressed and (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
        else:
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._is_pressed = False
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._is_pressed:
            self._is_pressed = False
        super().leaveEvent(event)

    def wheelEvent(self, event):
        # Ignore mouse wheel so the parent QScrollArea scrolls instead of altering settings
        event.ignore()


class StudioSpinBox(QSpinBox):
    """QSpinBox that ignores wheelEvent to avoid accidental changes while scrolling the panel."""
    def wheelEvent(self, event):
        event.ignore()


class StudioDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that ignores wheelEvent to avoid accidental changes while scrolling the panel."""
    def wheelEvent(self, event):
        event.ignore()


class InspectorPanel(QFrame):
    """Clean, flat Windows 11 Workbench Inspector Panel in English with comprehensive Russian hover tooltips."""

    render_requested = Signal(RenderTask)
    add_queue_requested = Signal(RenderTask)
    download_weights_requested = Signal()
    hint_changed = Signal(str)
    despill_changed = Signal(float)
    despill_color_changed = Signal(str)
    paint_mask_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inspectorPanel")
        self.setMinimumWidth(320)
        self.setStyleSheet("""
            QFrame#inspectorPanel {
                background-color: #16161A;
                border: 1px solid #28282E;
                border-radius: 8px;
            }
        """)

        self.current_clip: Optional[ClipInfo] = None
        self.output_dir: str = str(Path.home() / "Videos" / "CorridorKey_Renders")
        self.custom_weights_path: str = ""
        self.custom_temp_dir: str = ""
        self.hint_file_path: str = ""

        # Outer layout
        panel_layout = QVBoxLayout(self)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        # Scroll area
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        panel_layout.addWidget(self.scroll)

        self.container = QWidget(self.scroll)
        self.scroll.setWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        # 0. Missing Weights Alert (Clean single-layer notification banner)
        self.weights_card = QFrame()
        self.weights_card.setObjectName("weightsBanner")
        self.weights_card.setStyleSheet("""
            QFrame#weightsBanner {
                background-color: rgba(245, 158, 11, 0.12);
                border: 1px solid #D97706;
                border-radius: 6px;
            }
            QFrame#weightsBanner QLabel {
                border: none;
                background: transparent;
                color: #FCD34D;
            }
        """)
        wb_layout = QHBoxLayout(self.weights_card)
        wb_layout.setContentsMargins(8, 5, 8, 5)
        wb_layout.setSpacing(8)

        icon_warn = QLabel()
        icon_warn.setPixmap(FI.INFO.icon(color=QColor("#F59E0B")).pixmap(14, 14))
        wb_layout.addWidget(icon_warn)

        wc_title = QLabel("Weights missing (~5 GB)")
        wc_title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        wc_title.setToolTip("CorridorKey 2.0 model weights are missing from the weights/ folder. Click Download to download automatically.")
        wb_layout.addWidget(wc_title, stretch=1)

        btn_dl = QPushButton("Download")
        btn_dl.setIcon(FI.DOWNLOAD.icon(color=QColor("#FFFFFF")))
        btn_dl.setIconSize(QSize(12, 12))
        btn_dl.setProperty("class", "yellow-btn")
        btn_dl.setStyleSheet("""
            QPushButton {
                background-color: #D97706;
                color: #FFFFFF;
                font-weight: 700;
                font-size: 11px;
                border: 1px solid #F59E0B;
                border-radius: 4px;
                padding: 2px 10px;
            }
            QPushButton:hover {
                background-color: #B45309;
                border-color: #FBBF24;
            }
            QPushButton:pressed {
                background-color: #92400E;
            }
        """)
        btn_dl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_dl.setFixedHeight(24)
        btn_dl.setToolTip("<b>Download CorridorKey 2.0 Weights (~5 GB)</b><br>Automatically downloads weights from Hugging Face and auxiliary models C-RADIOv4, MoGe-2, RVM.")
        btn_dl.clicked.connect(self.download_weights_requested.emit)
        wb_layout.addWidget(btn_dl)
        layout.addWidget(self.weights_card)
        self._check_weights_exist()

        # =====================================================================
        # 1. INFERENCE & VRAM
        # =====================================================================
        tip_vram_sec = "<b>Inference & VRAM</b><br>CorridorKey 2.0 neural network inference settings and VRAM allocation."
        layout.addWidget(create_section_header("Inference & VRAM", tip_vram_sec))

        # Hann Window row
        h_box = QHBoxLayout()
        h_box.setSpacing(6)
        lbl_preset = QLabel("Hann Window:")
        lbl_preset.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_hann = (
            "<b>Hann Window (Temporal Context Window)</b><br>"
            "Groups neighboring frames into overlapping temporal batches (Chunk/Stride) for edge stability and motion blur:<br>"
            "&bull; <b>Auto VRAM</b>: automatically selects maximum window size within 8 GB VRAM budget.<br>"
            "&bull; <b>High Quality (48 / 24)</b>: cinematic production standard, minimizes edge flicker.<br>"
            "&bull; <b>Medium (24 / 12)</b>: balanced performance and quality.<br>"
            "&bull; <b>Low VRAM (8 / 4)</b>: compact temporal window for limited memory.<br>"
            "&bull; <b>Single Frame (1 / 1)</b>: frame-by-frame processing without temporal context (minimum VRAM)."
        )
        lbl_preset.setToolTip(tip_hann)
        h_box.addWidget(lbl_preset)

        self.cmb_hann_preset = ComboBox()
        self.cmb_hann_preset.addItems([
            "Auto VRAM (Optimized for 8 GB)",
            "High Quality (48 / 24)",
            "Medium (24 / 12)",
            "Low VRAM (8 / 4)",
            "Max Continuity (80 / 40)",
            "Single Frame (1 / 1)",
            "Custom...",
        ])
        self.cmb_hann_preset.setToolTip(tip_hann)
        self.cmb_hann_preset.currentIndexChanged.connect(self._on_hann_preset_changed)
        h_box.addWidget(self.cmb_hann_preset, stretch=1)
        layout.addLayout(h_box)

        # Custom Chunk / Stride row (hidden by default)
        self.custom_hann_row = QWidget()
        chr_layout = QHBoxLayout(self.custom_hann_row)
        chr_layout.setContentsMargins(0, 0, 0, 0)
        chr_layout.setSpacing(6)

        lbl_chunk = QLabel("Chunk:")
        lbl_chunk.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_chunk = "<b>Chunk (Window Size)</b><br>Number of consecutive frames processed together in each neural step."
        lbl_chunk.setToolTip(tip_chunk)
        chr_layout.addWidget(lbl_chunk)

        self.spin_hann_chunk = StudioSpinBox()
        self.spin_hann_chunk.setRange(1, 128)
        self.spin_hann_chunk.setValue(48)
        self.spin_hann_chunk.setToolTip(tip_chunk)
        self.spin_hann_chunk.valueChanged.connect(self._recalc_vram)
        chr_layout.addWidget(self.spin_hann_chunk)

        lbl_stride = QLabel("Stride:")
        lbl_stride.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_stride = "<b>Stride (Step Offset)</b><br>Temporal stride between consecutive windows (typically half of Chunk)."
        lbl_stride.setToolTip(tip_stride)
        chr_layout.addWidget(lbl_stride)

        self.spin_hann_stride = StudioSpinBox()
        self.spin_hann_stride.setRange(1, 128)
        self.spin_hann_stride.setValue(24)
        self.spin_hann_stride.setToolTip(tip_stride)
        chr_layout.addWidget(self.spin_hann_stride)
        self.custom_hann_row.hide()
        layout.addWidget(self.custom_hann_row)

        # Low VRAM mode
        self.chk_low_vram = CheckBox("Low GPU Memory (Disk Caching)")
        self.chk_low_vram.setChecked(False)
        self.chk_low_vram.setToolTip(
            "<b>Low GPU Memory (Disk Caching)</b><br>"
            "Offloads intermediate attention feature maps to disk (memory map).<br>"
            "Enables rendering 4K video on 8 GB VRAM with zero risk of Out Of Memory (OOM) errors."
        )
        self.chk_low_vram.stateChanged.connect(self._recalc_vram)
        layout.addWidget(self.chk_low_vram)

        # Model Scale row
        scale_box = QHBoxLayout()
        scale_box.setSpacing(6)
        lbl_scale = QLabel("Model Scale:")
        lbl_scale.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_scale = (
            "<b>Model Scale (Inference Resolution)</b><br>"
            "Resolution at which the neural network processes frames:<br>"
            "&bull; <b>1.0x (Native)</b>: full resolution without downsampling.<br>"
            "&bull; <b>0.50x (Fast)</b>: 2x downscaled input, 3-4x faster rendering."
        )
        lbl_scale.setToolTip(tip_scale)
        scale_box.addWidget(lbl_scale)

        self.cmb_model_scale = ComboBox()
        self.cmb_model_scale.addItems(["1.0x (Native)", "0.75x", "0.50x (Fast)", "1.50x", "2.00x"])
        self.cmb_model_scale.setToolTip(tip_scale)
        scale_box.addWidget(self.cmb_model_scale, stretch=1)
        layout.addLayout(scale_box)

        # Cache folder row
        temp_box = QHBoxLayout()
        temp_box.setSpacing(6)
        lbl_cache = QLabel("Cache Folder:")
        lbl_cache.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_cache = "<b>Cache Folder</b><br>Directory for temporary feature maps when Low GPU Memory mode is enabled."
        lbl_cache.setToolTip(tip_cache)
        temp_box.addWidget(lbl_cache)

        self.txt_temp_dir = QLineEdit("System Temp")
        self.txt_temp_dir.setReadOnly(True)
        self.txt_temp_dir.setToolTip(tip_cache)
        self.txt_temp_dir.setStyleSheet("background-color: #1A1A20; border: 1px solid #282830; border-radius: 4px; padding: 2px 6px; color: #94A3B8; font-size: 11px;")
        self.lbl_temp_dir = self.txt_temp_dir
        temp_box.addWidget(self.txt_temp_dir, stretch=1)

        btn_temp = QPushButton("...")
        btn_temp.setProperty("class", "pill-btn")
        btn_temp.setFixedSize(26, 22)
        btn_temp.setToolTip("Select custom directory for feature cache (recommended if C: drive is low on free space)")
        btn_temp.clicked.connect(self._on_choose_temp_dir)
        temp_box.addWidget(btn_temp)
        layout.addLayout(temp_box)

        layout.addWidget(create_separator())

        # =====================================================================
        # 2. ALPHA HINT & TRACKING
        # =====================================================================
        tip_hint_sec = "<b>Alpha Hint & Tracking</b><br>Guide the neural network with an auxiliary mask for complex scenes or shots without green screen."
        layout.addWidget(create_section_header("Alpha Hint & Tracking", tip_hint_sec))

        # Hint Header row: Title on left, Browse & Clear buttons on right
        hint_head_row = QHBoxLayout()
        hint_head_row.setSpacing(6)
        lbl_hint_title = QLabel("Hint File:")
        lbl_hint_title.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_hint_file = (
            "<b>Hint File</b><br>"
            "&bull; First frame mask image (PNG, JPG, EXR)<br>"
            "&bull; Video matte / rotoscope sequence (MP4, MOV)<br>"
            "White indicates subject, black indicates background."
        )
        lbl_hint_title.setToolTip(tip_hint_file)
        hint_head_row.addWidget(lbl_hint_title)
        hint_head_row.addStretch()

        self.btn_paint_mask = QPushButton("Paint Mask...")
        self.btn_paint_mask.setIcon(FI.PENCIL_INK.icon(Theme.DARK))
        self.btn_paint_mask.setIconSize(QSize(12, 12))
        self.btn_paint_mask.setProperty("class", "pill-btn")
        self.btn_paint_mask.setFixedHeight(22)
        tip_paint_mask = (
            "<b>Paint First-Frame Mask</b><br>"
            "Interactive tool to paint a rough subject guidance mask on frame 1 by hand.<br><br>"
            "<b>How to paint:</b><br>"
            "&bull; Paint over the body/silhouette with broad brush strokes.<br>"
            "&bull; No need to trace fine hair, fingers, or micro-details — the AI refiner reconstructs them automatically!<br>"
            "&bull; Avoid painting outside the subject onto the background.<br>"
            "&bull; Hint Trust will be automatically set to the optimal 0.75 for hand-painted masks."
        )
        self.btn_paint_mask.setToolTip(tip_paint_mask)
        self.btn_paint_mask.clicked.connect(self.paint_mask_requested.emit)
        self.btn_paint_mask.setVisible(False)
        hint_head_row.addWidget(self.btn_paint_mask)

        self.btn_pick_hint = QPushButton("Browse...")
        self.btn_pick_hint.setIcon(FI.FOLDER.icon(Theme.DARK))
        self.btn_pick_hint.setIconSize(QSize(12, 12))
        self.btn_pick_hint.setProperty("class", "pill-btn")
        self.btn_pick_hint.setFixedHeight(22)
        self.btn_pick_hint.setToolTip(tip_hint_file)
        self.btn_pick_hint.clicked.connect(self._on_choose_hint)
        hint_head_row.addWidget(self.btn_pick_hint)

        self.btn_clear_hint = QPushButton()
        self.btn_clear_hint.setIcon(FI.CLOSE.icon(color=QColor("#FFFFFF")))
        self.btn_clear_hint.setIconSize(QSize(12, 12))
        self.btn_clear_hint.setFixedSize(22, 22)
        self.btn_clear_hint.setStyleSheet("QPushButton { background-color: #222228; border: 1px solid #363640; border-radius: 4px; } QPushButton:hover { background-color: #32323A; }")
        self.btn_clear_hint.setToolTip("Reset selected hint and return to automatic segmentation")
        self.btn_clear_hint.clicked.connect(self._on_clear_hint)
        hint_head_row.addWidget(self.btn_clear_hint)
        layout.addLayout(hint_head_row)

        # Full-width hint file display
        self.txt_hint_path = QLineEdit("None (Auto Segmentation)")
        self.txt_hint_path.setReadOnly(True)
        self.txt_hint_path.setToolTip("Neural network automatically segments the primary subject without hints.")
        self.txt_hint_path.setStyleSheet("background-color: #1A1A20; border: 1px solid #282830; border-radius: 4px; padding: 2px 6px; color: #94A3B8; font-size: 11px;")
        self.lbl_hint_name = self.txt_hint_path
        layout.addWidget(self.txt_hint_path)

        # Hint Mode row
        hm_box = QHBoxLayout()
        hm_box.setSpacing(6)
        lbl_hm = QLabel("Hint Mode:")
        lbl_hm.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_hm = (
            "<b>Hint Mode</b><br>"
            "&bull; <b>Auto (No Hint)</b> [Default]: neural network automatically discovers and segments the primary subject without masks.<br>"
            "&bull; <b>First Frame (Hint)</b>: rough mask on the first frame (click 'Paint Mask...' to sketch or browse a PNG). The model locks onto the subject and tracks it through time.<br>"
            "&bull; <b>Video Matte</b>: frame-by-frame companion mask video for the entire clip."
        )
        lbl_hm.setToolTip(tip_hm)
        hm_box.addWidget(lbl_hm)

        self.cmb_hint_frames = ComboBox()
        self.cmb_hint_frames.addItems(["Auto (No Hint)", "First Frame (Hint)", "Video Matte"])
        self.cmb_hint_frames.setToolTip(tip_hm)
        self.cmb_hint_frames.currentIndexChanged.connect(self._on_hint_mode_changed)
        hm_box.addWidget(self.cmb_hint_frames, stretch=1)
        layout.addLayout(hm_box)

        # Hint Trust inline row: Label | Slider | Value
        ht_box = QHBoxLayout()
        ht_box.setSpacing(8)
        lbl_ht = QLabel("Trust:")
        lbl_ht.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_trust = (
            "<b>Hint Trust</b><br>"
            "Model confidence weighting for the provided hint mask (hint_quality):<br>"
            "&bull; <b>0.95</b>: precise rotoscope/matte from an artist.<br>"
            "&bull; <b>0.70</b>: rough scribble or approximate outline."
        )
        lbl_ht.setToolTip(tip_trust)
        ht_box.addWidget(lbl_ht)

        self.slider_hint_quality = StudioSlider(Qt.Orientation.Horizontal)
        self.slider_hint_quality.setRange(10, 100)
        self.slider_hint_quality.setValue(95)
        self.slider_hint_quality.setToolTip(tip_trust)
        ht_box.addWidget(self.slider_hint_quality, stretch=1)

        self.lbl_ht_val = QLabel("0.95")
        self.lbl_ht_val.setFixedWidth(28)
        self.lbl_ht_val.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 11px;")
        self.lbl_ht_val.setToolTip(tip_trust)
        self.slider_hint_quality.valueChanged.connect(lambda v: self.lbl_ht_val.setText(f"{v/100:.2f}"))
        ht_box.addWidget(self.lbl_ht_val)
        layout.addLayout(ht_box)

        # Carry Hint Switch
        self.chk_carry_hint = CheckBox("Hann Temporal Carry Hint")
        self.chk_carry_hint.setChecked(True)
        self.chk_carry_hint.setToolTip(
            "<b>Hann Temporal Carry Hint</b><br>"
            "Model propagates high-confidence predictions from previous windows as temporal guidance for subsequent frames, stabilizing tracking on long shots."
        )
        layout.addWidget(self.chk_carry_hint)

        layout.addWidget(create_separator())

        # =====================================================================
        # 3. DESPILL & COLOR SCIENCE
        # =====================================================================
        tip_despill_sec = "<b>Despill & Color</b><br>Suppresses green or blue background bounce and spill contamination on hair and edges."
        layout.addWidget(create_section_header("Despill & Color", tip_despill_sec))

        dc_box = QHBoxLayout()
        dc_box.setSpacing(6)
        lbl_dc = QLabel("Screen Color:")
        lbl_dc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_dc = (
            "<b>Screen Color</b><br>"
            "Backdrop color to neutralize spill reflections from.<br>"
            "&bull; <b>Auto</b>: automatically samples frame edges to detect green or blue screen.<br>"
            "&bull; <b>Green</b>: suppresses green bounce on hair and edges.<br>"
            "&bull; <b>Blue</b>: suppresses blue bounce on hair and edges."
        )
        lbl_dc.setToolTip(tip_dc)
        dc_box.addWidget(lbl_dc)

        self.cmb_despill_color = ComboBox()
        self.cmb_despill_color.addItems(["Auto", "Green", "Blue"])
        self.cmb_despill_color.setToolTip(tip_dc)
        self.cmb_despill_color.currentTextChanged.connect(self.despill_color_changed.emit)
        dc_box.addWidget(self.cmb_despill_color, stretch=1)
        layout.addLayout(dc_box)

        # Despill Strength inline row: Label | Slider | Value
        ds_box = QHBoxLayout()
        ds_box.setSpacing(8)
        lbl_ds = QLabel("Despill:")
        lbl_ds.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_ds = (
            "<b>Despill Strength</b><br>"
            "&bull; <b>0.50</b>: standard strength for green screen / blue screen footage.<br>"
            "&bull; <b>0.00</b>: OFF (mandatory for non-green footage, white walls, or arbitrary backgrounds to preserve natural skin tones).<br>"
            "&bull; <b>1.00</b>: maximum spill neutralization."
        )
        lbl_ds.setToolTip(tip_ds)
        ds_box.addWidget(lbl_ds)

        self.slider_despill = StudioSlider(Qt.Orientation.Horizontal)
        self.slider_despill.setRange(0, 100)
        self.slider_despill.setValue(50)
        self.slider_despill.setToolTip(tip_ds)
        ds_box.addWidget(self.slider_despill, stretch=1)

        self.lbl_ds_val = QLabel("0.50")
        self.lbl_ds_val.setFixedWidth(28)
        self.lbl_ds_val.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 11px;")
        self.lbl_ds_val.setToolTip(tip_ds)
        self.slider_despill.valueChanged.connect(self._on_despill_slider_changed)
        ds_box.addWidget(self.lbl_ds_val)
        layout.addLayout(ds_box)

        # Linear Brightness & Contrast (clean side-by-side)
        bc_layout = QHBoxLayout()
        bc_layout.setSpacing(6)
        tip_bc = "<b>Linear Brightness & Contrast</b><br>Exposure and contrast adjustment of foreground subject in scene-linear color space."

        lbl_bright = QLabel("Brightness:")
        lbl_bright.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        lbl_bright.setToolTip(tip_bc)
        bc_layout.addWidget(lbl_bright)

        self.spin_brightness = StudioDoubleSpinBox()
        self.spin_brightness.setRange(0.0, 5.0)
        self.spin_brightness.setSingleStep(0.05)
        self.spin_brightness.setValue(1.0)
        self.spin_brightness.setFixedWidth(58)
        self.spin_brightness.setToolTip(tip_bc)
        bc_layout.addWidget(self.spin_brightness)

        bc_layout.addSpacing(6)

        lbl_contrast = QLabel("Contrast:")
        lbl_contrast.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        lbl_contrast.setToolTip(tip_bc)
        bc_layout.addWidget(lbl_contrast)

        self.spin_contrast = StudioDoubleSpinBox()
        self.spin_contrast.setRange(0.0, 5.0)
        self.spin_contrast.setSingleStep(0.05)
        self.spin_contrast.setValue(1.0)
        self.spin_contrast.setFixedWidth(58)
        self.spin_contrast.setToolTip(tip_bc)
        bc_layout.addWidget(self.spin_contrast)
        layout.addLayout(bc_layout)

        # Advanced VFX Linear Flags
        self.chk_cutout_linear = CheckBox("Cutout Straight Linear RGB (32-bit VFX)")
        self.chk_cutout_linear.setChecked(False)
        self.chk_cutout_linear.setToolTip(
            "<b>Cutout Straight Linear RGB</b><br>"
            "Export cutout clip in un-premultiplied straight scene-linear RGB for professional compositing in DaVinci Fusion, Nuke, or After Effects."
        )
        layout.addWidget(self.chk_cutout_linear)

        self.chk_frame_dir_linear = CheckBox("Input EXR as Scene-Linear")
        self.chk_frame_dir_linear.setChecked(False)
        self.chk_frame_dir_linear.setToolTip(
            "<b>Input EXR as Scene-Linear</b><br>"
            "Interpret incoming OpenEXR frame sequences as scene-linear gamma instead of sRGB."
        )
        layout.addWidget(self.chk_frame_dir_linear)

        layout.addWidget(create_separator())

        # =====================================================================
        # 4. DELIVER & EXPORT
        # =====================================================================
        tip_deliver_sec = "<b>Deliver</b><br>Output passes, video codec settings, export directory, and render dispatch."
        layout.addWidget(create_section_header("Deliver", tip_deliver_sec))

        # Passes 2x2 grid
        passes_grid = QHBoxLayout()
        self.chk_out_cutout = CheckBox("Cutout (RGBA)")
        self.chk_out_cutout.setChecked(True)
        self.chk_out_cutout.setToolTip(
            "<b>Cutout Pass (ProRes 4444 MOV)</b><br>"
            "Master production delivery file: video with transparent alpha channel and despill applied for NLE editing."
        )
        passes_grid.addWidget(self.chk_out_cutout)

        self.chk_out_alpha = CheckBox("Alpha (Matte)")
        self.chk_out_alpha.setChecked(True)
        self.chk_out_alpha.setToolTip(
            "<b>Alpha Matte Pass (MP4)</b><br>"
            "Black & white silhouette matte (white is subject, black is background) for compositing and live viewport preview."
        )
        passes_grid.addWidget(self.chk_out_alpha)
        layout.addLayout(passes_grid)

        passes_grid2 = QHBoxLayout()
        self.chk_out_fg = CheckBox("FG (Foreground)")
        self.chk_out_fg.setChecked(False)
        self.chk_out_fg.setToolTip(
            "<b>Foreground Pass (RGB)</b><br>"
            "Despilled RGB foreground image without alpha channel. Disabled by default to save disk space."
        )
        passes_grid2.addWidget(self.chk_out_fg)

        self.chk_out_checker = CheckBox("Checker (Preview)")
        self.chk_out_checker.setChecked(True)
        self.chk_out_checker.setToolTip(
            "<b>Checker Preview Pass (MP4)</b><br>"
            "Universal preview video composited over transparency checkerboard. Plays directly in Windows Media Player."
        )
        passes_grid2.addWidget(self.chk_out_checker)
        layout.addLayout(passes_grid2)

        fmt_box = QHBoxLayout()
        fmt_box.setSpacing(6)
        lbl_fmt = QLabel("Format:")
        lbl_fmt.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_fmt = (
            "<b>Output Format</b><br>"
            "&bull; <b>MP4 Video (Universal - Windows Compatible)</b>: standard 8-bit H.264 yuv420p, plays in all Windows players (Media Player, Films & TV), web browsers, and phones.<br>"
            "&bull; <b>MP4 Video (Studio 10-bit - High 4:4:4)</b>: studio x264 profile without gradient banding for NLE compositing (requires VLC, Premiere, DaVinci).<br>"
            "&bull; <b>EXR Sequence (16-bit Half)</b>: VFX frame sequence for DaVinci Fusion / Nuke.<br>"
            "&bull; <b>EXR Sequence (32-bit Float)</b>: full 32-bit float linear frames for high-end VFX."
        )
        lbl_fmt.setToolTip(tip_fmt)
        fmt_box.addWidget(lbl_fmt)

        self.cmb_format = ComboBox()
        self.cmb_format.addItems([
            "MP4 Video (Universal - Windows Compatible)",
            "MP4 Video (Studio 10-bit - High 4:4:4)",
            "EXR Sequence (16-bit Half)",
            "EXR Sequence (32-bit Float)",
        ])
        self.cmb_format.setToolTip(tip_fmt)
        fmt_box.addWidget(self.cmb_format, stretch=1)
        layout.addLayout(fmt_box)

        # Output folder header: Label on left, Open & Browse on right
        out_f_head = QHBoxLayout()
        out_f_head.setSpacing(6)
        lbl_out = QLabel("Output Folder:")
        lbl_out.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500; font-size: 11px;")
        tip_out = "<b>Output Folder</b><br>Target directory where render sets will be saved."
        lbl_out.setToolTip(tip_out)
        out_f_head.addWidget(lbl_out)
        out_f_head.addStretch()

        btn_open_out = QPushButton("Open")
        btn_open_out.setIcon(FI.FOLDER.icon(Theme.DARK))
        btn_open_out.setIconSize(QSize(12, 12))
        btn_open_out.setProperty("class", "pill-btn")
        btn_open_out.setFixedHeight(22)
        btn_open_out.setToolTip("Open output directory in Windows Explorer")
        btn_open_out.clicked.connect(self._on_open_out_dir)
        out_f_head.addWidget(btn_open_out)

        btn_out_dir = QPushButton("Browse...")
        btn_out_dir.setIcon(FI.FOLDER.icon(Theme.DARK))
        btn_out_dir.setIconSize(QSize(12, 12))
        btn_out_dir.setProperty("class", "pill-btn")
        btn_out_dir.setFixedHeight(22)
        btn_out_dir.setToolTip("Select destination folder for exported renders")
        btn_out_dir.clicked.connect(self._on_choose_out_dir)
        out_f_head.addWidget(btn_out_dir)
        layout.addLayout(out_f_head)

        # Full-width output directory display
        self.txt_out_dir = QLineEdit(self.output_dir)
        self.txt_out_dir.setReadOnly(True)
        self.txt_out_dir.setToolTip(self.output_dir)
        self.txt_out_dir.setStyleSheet("background-color: #1A1A20; border: 1px solid #282830; border-radius: 4px; padding: 2px 6px; color: #94A3B8; font-size: 11px;")
        self.lbl_out_dir = self.txt_out_dir
        layout.addWidget(self.txt_out_dir)

        # Frame limit test row
        limit_box = QHBoxLayout()
        limit_box.setSpacing(8)
        self.chk_limit_frames = CheckBox("Limit Frames:")
        self.chk_limit_frames.setChecked(False)
        tip_limit = "<b>Limit Frames</b><br>Render only the first N frames for quick quality inspection."
        self.chk_limit_frames.setToolTip(tip_limit)
        limit_box.addWidget(self.chk_limit_frames)

        self.spin_num_frames = StudioSpinBox()
        self.spin_num_frames.setRange(1, 999999)
        self.spin_num_frames.setValue(60)
        self.spin_num_frames.setFixedWidth(65)
        self.spin_num_frames.setEnabled(False)
        self.spin_num_frames.setToolTip(tip_limit)
        self.chk_limit_frames.stateChanged.connect(lambda s: self.spin_num_frames.setEnabled(bool(s)))
        limit_box.addWidget(self.spin_num_frames)
        limit_box.addStretch()
        layout.addLayout(limit_box)

        # Calculated memory requirements
        self.lbl_vram_info = QLabel("Select a clip to estimate VRAM requirements.")
        self.lbl_vram_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 2px;")
        self.lbl_vram_info.setToolTip("<b>VRAM Estimate</b><br>Estimated VRAM requirement calculated for clip resolution and Hann window size against your 8 GB GPU.")
        layout.addWidget(self.lbl_vram_info)

        # Notification & Versioning controls
        self.chk_sound_on_finish = CheckBox("Play notification sound on completion")
        self.chk_sound_on_finish.setChecked(True)
        self.chk_sound_on_finish.setToolTip("<b>Completion Sound</b><br>Play a soft, gentle Windows notification chime when rendering finishes.")
        layout.addWidget(self.chk_sound_on_finish)

        self.chk_versioned_sets = CheckBox("Versioned output sets (set_01, set_02...)")
        self.chk_versioned_sets.setChecked(False)
        self.chk_versioned_sets.setToolTip("<b>Versioned Sets</b><br>When enabled, every new render is saved into a new subfolder (set_01, set_02...). When disabled, renders save directly to the clip directory, overwriting previous files.")
        layout.addWidget(self.chk_versioned_sets)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_render = QPushButton("Render Active Clip")
        self.btn_render.setIcon(FI.PLAY.icon(color=QColor("#FFFFFF")))
        self.btn_render.setIconSize(QSize(13, 13))
        self.btn_render.setProperty("class", "primary-btn")
        self.btn_render.setFixedHeight(32)
        self.btn_render.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_render.setToolTip("<b>Render Active Clip (Ctrl+R)</b><br>Process currently selected clip with current settings.")
        self.btn_render.clicked.connect(self._on_render)
        action_row.addWidget(self.btn_render, stretch=1)

        layout.addLayout(action_row)
        layout.addStretch()

    def _check_weights_exist(self):
        try:
            from gui.managers.weights_manager import WeightsManager
            has_weights = WeightsManager.are_all_weights_present()
        except Exception:
            root = Path(__file__).resolve().parent.parent.parent
            weights_file = root / "weights" / "corridorkey_v2.safetensors"
            has_weights = weights_file.exists() or (root / "weights" / "corridorkey_v2.pt").exists()
        self.weights_card.setVisible(not has_weights)

    def set_clip(self, clip: Optional[ClipInfo]):
        self.current_clip = clip
        if clip is not None:
            # Clean Slate: Always default to Auto (No Hint) when loading clips
            self.hint_file_path = ""
            self.cmb_hint_frames.setCurrentIndex(0)
            self.txt_hint_path.setText("None (Auto Segmentation)")
            self.txt_hint_path.setToolTip("Neural network automatically segments the primary subject without hints.")
        self._recalc_vram()

    def _on_despill_slider_changed(self, v: int):
        val = v / 100.0
        self.lbl_ds_val.setText(f"{val:.2f}")
        self.despill_changed.emit(val)

    def _on_hann_preset_changed(self, idx: int):
        self.custom_hann_row.setVisible(idx == 6)
        presets = {1: (48, 24), 2: (24, 12), 3: (8, 4), 4: (80, 40), 5: (1, 1)}
        if idx in presets:
            c, s = presets[idx]
            self.spin_hann_chunk.setValue(c)
            self.spin_hann_stride.setValue(s)
        self._recalc_vram()

    def _recalc_vram(self):
        if self.current_clip is None:
            self.lbl_vram_info.setText("Select a clip to estimate VRAM requirements.")
            self.lbl_vram_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; padding: 2px;")
            return

        low_vram = self.chk_low_vram.isChecked()
        preset_idx = self.cmb_hann_preset.currentIndex()
        if preset_idx == 0:
            hann_chunk = 80
        elif preset_idx == 6:
            hann_chunk = self.spin_hann_chunk.value()
        else:
            hann_chunk = {1: 48, 2: 24, 3: 8, 4: 80, 5: 1}.get(preset_idx, 40)

        vram_needed, fits = calculate_clip_vram_estimate(
            self.current_clip.width,
            self.current_clip.height,
            self.current_clip.total_frames,
            low_vram=low_vram,
            hann_chunk=hann_chunk,
        )

        gpu_info = get_gpu_info()
        total_gpu = gpu_info.get("total_gb", 8.0)

        if not gpu_info.get("is_supported", True) and gpu_info.get("available", False):
            self.lbl_vram_info.setText("Warning: GPU older than RTX 30-series (missing hardware bfloat16 support)")
            self.lbl_vram_info.setStyleSheet("color: #F87171; font-size: 11px; padding: 2px;")
            return

        status_color = CORRIDOR_GREEN if fits else "#F87171"
        status_text = "VRAM OK" if fits else "Warning: VRAM may exceed capacity"

        self.lbl_vram_info.setText(f"{status_text}: ~{vram_needed:.1f} of {total_gpu:.1f} GB required")
        self.lbl_vram_info.setStyleSheet(
            f"color: {status_color}; font-size: 11px; padding: 2px;"
        )

    def _on_choose_hint(self):
        fpath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Alpha Hint File",
            "",
            "Matte and Video Files (*.png *.jpg *.jpeg *.mp4 *.mov *.exr);;All Files (*.*)",
        )
        if fpath:
            self.hint_file_path = fpath
            self.txt_hint_path.setText(os.path.basename(fpath))
            self.txt_hint_path.setToolTip(fpath)
            ext = Path(fpath).suffix.lower()
            if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
                self.cmb_hint_frames.setCurrentIndex(2)
            else:
                self.cmb_hint_frames.setCurrentIndex(1)
            self.hint_changed.emit(fpath)

    def _on_clear_hint(self):
        self.hint_file_path = ""
        self.cmb_hint_frames.setCurrentIndex(0)
        self.txt_hint_path.setText("None (Auto Segmentation)")
        self.txt_hint_path.setToolTip("Neural network automatically segments the primary subject without hints.")
        self.btn_paint_mask.setVisible(False)
        self.hint_changed.emit("")

    def _on_hint_mode_changed(self, idx: int):
        if idx == 0:  # Auto (No Hint)
            self.btn_paint_mask.setVisible(False)
            self.btn_pick_hint.setEnabled(False)
            self.slider_hint_quality.setEnabled(False)
            self.txt_hint_path.setText("None (Auto Segmentation)")
            self.txt_hint_path.setToolTip("Neural network automatically segments the primary subject without hints.")
            self.hint_file_path = ""
            self.hint_changed.emit("")
        elif idx == 1:  # First Frame (Hint)
            self.btn_paint_mask.setVisible(True)
            self.btn_pick_hint.setEnabled(True)
            self.slider_hint_quality.setEnabled(True)
            if self.hint_file_path:
                self.txt_hint_path.setText(os.path.basename(self.hint_file_path))
                self.txt_hint_path.setToolTip(self.hint_file_path)
            else:
                self.txt_hint_path.setText("No mask selected (click 'Paint Mask...' or 'Browse...')")
                self.txt_hint_path.setToolTip("Click 'Paint Mask...' to sketch the subject or select a PNG matte.")
        else:  # Video Matte
            self.btn_paint_mask.setVisible(False)
            self.btn_pick_hint.setEnabled(True)
            self.slider_hint_quality.setEnabled(True)
            if self.hint_file_path:
                self.txt_hint_path.setText(os.path.basename(self.hint_file_path))
                self.txt_hint_path.setToolTip(self.hint_file_path)
            else:
                self.txt_hint_path.setText("No video matte selected (click 'Browse...')")

    def set_painted_mask(self, mask_path: str):
        """Called when user successfully paints and applies a mask from MaskPainterDialog."""
        self.hint_file_path = mask_path
        self.cmb_hint_frames.setCurrentIndex(1)  # First Frame (Hint)
        self.btn_paint_mask.setVisible(True)
        self.txt_hint_path.setText(os.path.basename(mask_path))
        self.txt_hint_path.setToolTip(mask_path)
        self.slider_hint_quality.setValue(75)  # 0.75 is optimal trust for hand-painted masks
        self.hint_changed.emit(mask_path)

    def _on_choose_temp_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Feature Cache Directory")
        if d:
            self.custom_temp_dir = d
            self.txt_temp_dir.setText(os.path.basename(d))
            self.txt_temp_dir.setToolTip(d)

    def _on_choose_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Export Directory", self.output_dir)
        if d:
            self.output_dir = d
            self.txt_out_dir.setText(d)
            self.txt_out_dir.setToolTip(d)
            self._recalc_vram()

    def _on_open_out_dir(self):
        target = self.output_dir
        if self.current_clip:
            stem = Path(self.current_clip.path).stem
            clip_base = Path(self.output_dir) / stem
            if clip_base.is_dir():
                set_dirs = sorted([d for d in clip_base.iterdir() if d.is_dir() and d.name.startswith("set_")], reverse=True)
                target = str(set_dirs[0]) if set_dirs else str(clip_base)
            else:
                clip_sub = Path(self.output_dir) / f"out_{stem}"
                if clip_sub.is_dir():
                    target = str(clip_sub)
        if os.path.exists(target):
            try:
                os.startfile(target)
            except Exception as e:
                print(f"[Inspector] Could not open folder: {e}")

    def get_render_task(self, clip: Optional[ClipInfo] = None) -> Optional[RenderTask]:
        target_clip = clip or self.current_clip
        if target_clip is None:
            return None

        outputs = []
        if self.chk_out_cutout.isChecked():
            outputs.append("cutout")
        if self.chk_out_alpha.isChecked():
            outputs.append("alpha")
        if self.chk_out_fg.isChecked():
            outputs.append("fg")
        if self.chk_out_checker.isChecked():
            outputs.append("checker")
        if not outputs:
            outputs = ["cutout", "alpha"]

        fmt_idx = self.cmb_format.currentIndex()
        if fmt_idx == 0:
            out_fmt = "video"
            pix_fmt = "yuv420p"  # Universal standard playback in Windows Media Player & browsers
            exr_dtype = "half"
        elif fmt_idx == 1:
            out_fmt = "video"
            pix_fmt = "yuv444p10le"  # Studio 10-bit x264 without gradient banding
            exr_dtype = "half"
        elif fmt_idx == 2:
            out_fmt = "exr"
            pix_fmt = "yuv420p"
            exr_dtype = "half"
        else:
            out_fmt = "exr"
            pix_fmt = "yuv420p"
            exr_dtype = "float"

        preset_idx = self.cmb_hann_preset.currentIndex()
        auto_vram = (preset_idx == 0) and not self.chk_low_vram.isChecked()

        if preset_idx == 6:
            hann_chunk = self.spin_hann_chunk.value()
            hann_stride = self.spin_hann_stride.value()
        else:
            hann_map = {1: (48, 24), 2: (24, 12), 3: (8, 4), 4: (80, 40), 5: (1, 1)}
            hann_chunk, hann_stride = hann_map.get(preset_idx, (48, 24))

        scale_vals = [1.0, 0.75, 0.50, 1.50, 2.00]
        model_scale = scale_vals[self.cmb_model_scale.currentIndex()]

        num_frames = self.spin_num_frames.value() if self.chk_limit_frames.isChecked() else -1

        import uuid
        task_id = str(uuid.uuid4())[:8]
        stem = Path(target_clip.name).stem
        clip_base_dir = os.path.join(self.output_dir, stem)
        os.makedirs(clip_base_dir, exist_ok=True)

        if self.chk_versioned_sets.isChecked():
            # Isolated auto-incrementing set subdirectories (set_01, set_02...)
            set_idx = 1
            while True:
                candidate = os.path.join(clip_base_dir, f"set_{set_idx:02d}")
                if not os.path.exists(candidate) or not os.listdir(candidate):
                    clip_out_dir = candidate
                    break
                set_idx += 1
        else:
            clip_out_dir = clip_base_dir
        os.makedirs(clip_out_dir, exist_ok=True)

        hint_idx = self.cmb_hint_frames.currentIndex()
        use_hint = (hint_idx != 0) and bool(self.hint_file_path)
        hint_mode = "first_frame" if hint_idx <= 1 else "all_frames"

        return RenderTask(
            task_id=task_id,
            clip_path=target_clip.path,
            output_dir=clip_out_dir,
            clip_name=target_clip.name,
            total_frames=target_clip.total_frames,
            weights_path=self.custom_weights_path or None,
            use_alpha_hint=use_hint,
            alpha_hint_path=self.hint_file_path if use_hint else "",
            hint_mode=hint_mode,
            hint_quality=self.slider_hint_quality.value() / 100.0,
            carry_hint_quality=self.slider_hint_quality.value() / 100.0,
            carry_hint=self.chk_carry_hint.isChecked(),
            hann_chunk=hann_chunk,
            hann_stride=hann_stride,
            low_vram=self.chk_low_vram.isChecked(),
            auto_vram=auto_vram,
            temp_dir=self.custom_temp_dir or None,
            outputs=outputs,
            num_frames=num_frames,
            start_mode="begin",
            seed=0,
            model_scale=model_scale,
            frame_dir_fps=target_clip.fps or 24.0,
            frame_dir_linear=self.chk_frame_dir_linear.isChecked(),
            cutout_linear=self.chk_cutout_linear.isChecked(),
            despill_strength=self.slider_despill.value() / 100.0,
            linear_brightness=self.spin_brightness.value(),
            linear_contrast=self.spin_contrast.value(),
            linear_contrast_pivot=0.18,
            output_format=out_fmt,
            exr_dtype=exr_dtype,
            ffmpeg_codec="libx264",
            crf=12,
            preset="medium",
            pix_fmt=pix_fmt,
            ffmpeg_threads=4,
            stage2_batch=2,
        )

    def _on_render(self):
        task = self.get_render_task()
        if task is not None:
            self.render_requested.emit(task)

    def _on_add_queue(self):
        task = self.get_render_task()
        if task is not None:
            self.add_queue_requested.emit(task)

    def save_settings(self, settings: QSettings):
        settings.beginGroup("Inference")
        settings.setValue("hann_preset", self.cmb_hann_preset.currentIndex())
        settings.setValue("hann_chunk", self.spin_hann_chunk.value())
        settings.setValue("hann_stride", self.spin_hann_stride.value())
        settings.setValue("low_vram", self.chk_low_vram.isChecked())
        settings.setValue("model_scale", self.cmb_model_scale.currentIndex())
        settings.endGroup()

        settings.beginGroup("AlphaHint")
        settings.setValue("hint_frames", self.cmb_hint_frames.currentIndex())
        settings.setValue("hint_quality", self.slider_hint_quality.value())
        settings.setValue("carry_hint", self.chk_carry_hint.isChecked())
        settings.endGroup()

        settings.beginGroup("Despill")
        settings.setValue("despill_color", self.cmb_despill_color.currentIndex())
        settings.setValue("despill_strength", self.slider_despill.value())
        settings.setValue("brightness", self.spin_brightness.value())
        settings.setValue("contrast", self.spin_contrast.value())
        settings.setValue("cutout_linear", self.chk_cutout_linear.isChecked())
        settings.setValue("frame_dir_linear", self.chk_frame_dir_linear.isChecked())
        settings.endGroup()

        settings.beginGroup("Deliver")
        settings.setValue("out_cutout", self.chk_out_cutout.isChecked())
        settings.setValue("out_alpha", self.chk_out_alpha.isChecked())
        settings.setValue("out_fg", self.chk_out_fg.isChecked())
        settings.setValue("out_checker", self.chk_out_checker.isChecked())
        settings.setValue("format", self.cmb_format.currentIndex())
        settings.setValue("output_dir", self.output_dir)
        settings.setValue("sound_on_finish", self.chk_sound_on_finish.isChecked())
        settings.setValue("versioned_sets", self.chk_versioned_sets.isChecked())
        settings.setValue("limit_frames", self.chk_limit_frames.isChecked())
        settings.setValue("num_frames", self.spin_num_frames.value())
        settings.endGroup()

    def load_settings(self, settings: QSettings):
        settings.beginGroup("Inference")
        if settings.contains("hann_preset"):
            self.cmb_hann_preset.setCurrentIndex(int(settings.value("hann_preset", 0)))
        if settings.contains("hann_chunk"):
            self.spin_hann_chunk.setValue(int(settings.value("hann_chunk", 48)))
        if settings.contains("hann_stride"):
            self.spin_hann_stride.setValue(int(settings.value("hann_stride", 24)))
        if settings.contains("low_vram"):
            self.chk_low_vram.setChecked(settings.value("low_vram", False, type=bool))
        if settings.contains("model_scale"):
            self.cmb_model_scale.setCurrentIndex(int(settings.value("model_scale", 0)))
        settings.endGroup()

        settings.beginGroup("AlphaHint")
        if settings.contains("hint_frames"):
            self.cmb_hint_frames.setCurrentIndex(int(settings.value("hint_frames", 0)))
        if settings.contains("hint_quality"):
            self.slider_hint_quality.setValue(int(settings.value("hint_quality", 95)))
        if settings.contains("carry_hint"):
            self.chk_carry_hint.setChecked(settings.value("carry_hint", True, type=bool))
        settings.endGroup()

        settings.beginGroup("Despill")
        if settings.contains("despill_color"):
            self.cmb_despill_color.setCurrentIndex(int(settings.value("despill_color", 0)))
        if settings.contains("despill_strength"):
            self.slider_despill.setValue(int(settings.value("despill_strength", 50)))
        if settings.contains("brightness"):
            self.spin_brightness.setValue(float(settings.value("brightness", 1.0)))
        if settings.contains("contrast"):
            self.spin_contrast.setValue(float(settings.value("contrast", 1.0)))
        if settings.contains("cutout_linear"):
            self.chk_cutout_linear.setChecked(settings.value("cutout_linear", False, type=bool))
        if settings.contains("frame_dir_linear"):
            self.chk_frame_dir_linear.setChecked(settings.value("frame_dir_linear", False, type=bool))
        settings.endGroup()

        settings.beginGroup("Deliver")
        if settings.contains("out_cutout"):
            self.chk_out_cutout.setChecked(settings.value("out_cutout", True, type=bool))
        if settings.contains("out_alpha"):
            self.chk_out_alpha.setChecked(settings.value("out_alpha", True, type=bool))
        if settings.contains("out_fg"):
            self.chk_out_fg.setChecked(settings.value("out_fg", False, type=bool))
        if settings.contains("out_checker"):
            self.chk_out_checker.setChecked(settings.value("out_checker", True, type=bool))
        if settings.contains("format"):
            self.cmb_format.setCurrentIndex(int(settings.value("format", 0)))
        if settings.contains("output_dir"):
            saved_dir = str(settings.value("output_dir"))
            if saved_dir and os.path.isdir(saved_dir):
                self.output_dir = saved_dir
                self.txt_out_dir.setText(saved_dir)
                self.txt_out_dir.setToolTip(saved_dir)
        if settings.contains("sound_on_finish"):
            self.chk_sound_on_finish.setChecked(settings.value("sound_on_finish", True, type=bool))
        if settings.contains("versioned_sets"):
            self.chk_versioned_sets.setChecked(settings.value("versioned_sets", False, type=bool))
        if settings.contains("limit_frames"):
            self.chk_limit_frames.setChecked(settings.value("limit_frames", False, type=bool))
        if settings.contains("num_frames"):
            self.spin_num_frames.setValue(int(settings.value("num_frames", 60)))
        settings.endGroup()
        self._recalc_vram()
