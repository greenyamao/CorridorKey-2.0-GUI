"""Interactive First-Frame Mask Painter Dialog for CorridorKey 2.0.

Provides a responsive, high-performance canvas to paint a rough subject guidance mask
directly on the first frame of a video clip with zero lag, zoom/pan support, and undo.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List

import numpy as np
import cv2
from PySide6.QtCore import Qt, QPoint, QPointF, QRect, QRectF, QSize, Signal
from PySide6.QtGui import (
    QImage,
    QPainter,
    QPen,
    QColor,
    QBrush,
    QCursor,
    QKeyEvent,
    QWheelEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QFrame,
    QMessageBox,
)
from qfluentwidgets import FluentIcon as FI, Theme

from gui.styles.theme import (
    BG_DARK,
    TEXT_SECONDARY,
    ACCENT_BLUE,
    CORRIDOR_GREEN,
    CORRIDOR_YELLOW,
)


class PaintCanvas(QWidget):
    """Zero-lag hardware-accelerated painting canvas with pan, zoom, and undo."""

    tool_changed = Signal(str)
    brush_size_changed = Signal(int)

    def __init__(self, bg_image: QImage, initial_mask: Optional[QImage] = None, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.bg_image = bg_image
        self.img_w = bg_image.width()
        self.img_h = bg_image.height()

        # Visual overlay buffer (Format_RGBA8888 for native per-pixel alpha transparency)
        self.overlay_image = QImage(self.img_w, self.img_h, QImage.Format.Format_RGBA8888)
        self.overlay_image.fill(QColor(0, 0, 0, 0))

        # Tool parameters
        self.tool_mode = "brush"  # "brush" | "eraser"
        self.brush_size = 45  # In image pixels
        self.overlay_opacity = 0.55  # 0.20 to 0.90
        self.mask_color = QColor(0, 225, 255)  # High-visibility neon cyan

        # Populate from existing initial mask if provided
        if initial_mask is not None and not initial_mask.isNull():
            self._load_initial_mask(initial_mask)

        # Undo stack (stores up to 15 snapshot copies of the overlay)
        self.undo_stack: List[QImage] = []

        # Pan and Zoom transform
        self.zoom_factor = 1.0
        self.pan_offset = QPoint(0, 0)
        self._is_panning = False
        self._is_drawing = False
        self._space_held = False
        self._last_mouse_pos = QPoint()
        self._last_img_pt: Optional[QPointF] = None
        self._cursor_widget_pos = QPoint(-100, -100)

        # Initial fit
        self._first_show = True

    def _load_initial_mask(self, initial_mask: QImage):
        """Populates overlay_image RGBA from an existing grayscale or color mask."""
        if initial_mask.size() != QSize(self.img_w, self.img_h):
            initial_mask = initial_mask.scaled(
                self.img_w,
                self.img_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        mono_qimg = initial_mask.convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = mono_qimg.constBits()
        mono_arr = np.frombuffer(ptr, dtype=np.uint8).reshape((self.img_h, self.img_w))
        mask_active = mono_arr > 128

        ov_ptr = self.overlay_image.bits()
        ov_arr = np.frombuffer(ov_ptr, dtype=np.uint8).reshape((self.img_h, self.img_w, 4))
        # Format_RGBA8888: R=0, G=1, B=2, A=3
        ov_arr[mask_active, 0] = self.mask_color.red()
        ov_arr[mask_active, 1] = self.mask_color.green()
        ov_arr[mask_active, 2] = self.mask_color.blue()
        ov_arr[mask_active, 3] = 255

    def _push_undo(self):
        if len(self.undo_stack) >= 15:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.overlay_image.copy())

    def undo(self):
        if self.undo_stack:
            self.overlay_image = self.undo_stack.pop()
            self.update()

    def clear_mask(self):
        self._push_undo()
        self.overlay_image.fill(QColor(0, 0, 0, 0))
        self.update()

    def reset_view(self):
        vw = self.width()
        vh = self.height()
        if self.img_w > 0 and self.img_h > 0 and vw > 0 and vh > 0:
            scale = min((vw - 40) / self.img_w, (vh - 40) / self.img_h)
            self.zoom_factor = max(0.05, min(scale, 5.0))
            dest_w = int(self.img_w * self.zoom_factor)
            dest_h = int(self.img_h * self.zoom_factor)
            self.pan_offset = QPoint((vw - dest_w) // 2, (vh - dest_h) // 2)
            self.update()

    def set_brush_size(self, size: int):
        new_size = max(4, min(size, 300))
        if new_size != self.brush_size:
            self.brush_size = new_size
            self.brush_size_changed.emit(self.brush_size)
            self.update()

    def set_overlay_opacity(self, opacity: float):
        self.overlay_opacity = max(0.1, min(opacity, 0.95))
        self.update()

    def set_tool(self, tool: str):
        if tool in ("brush", "eraser") and tool != self.tool_mode:
            self.tool_mode = tool
            self.tool_changed.emit(self.tool_mode)
            self.update()

    def widget_to_image(self, pt: QPoint) -> QPointF:
        """Converts widget pixel position to floating-point image coordinates."""
        ix = (pt.x() - self.pan_offset.x()) / self.zoom_factor
        iy = (pt.y() - self.pan_offset.y()) / self.zoom_factor
        return QPointF(ix, iy)

    def image_to_widget(self, pt: QPointF) -> QPoint:
        """Converts image coordinates to widget coordinates."""
        wx = int(pt.x() * self.zoom_factor + self.pan_offset.x())
        wy = int(pt.y() * self.zoom_factor + self.pan_offset.y())
        return QPoint(wx, wy)

    def _draw_dot(self, pt: QPointF):
        """Draws a solid circular dot at pt for single mouse clicks."""
        painter = QPainter(self.overlay_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        radius = self.brush_size / 2.0
        if self.tool_mode == "brush":
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(self.mask_color))
            painter.drawEllipse(pt, radius, radius)
        else:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(Qt.GlobalColor.transparent))
            painter.drawEllipse(pt, radius, radius)
        painter.end()

    def _draw_stroke_segment(self, p1: QPointF, p2: QPointF):
        """Draws smooth anti-aliased line stroke with round caps between p1 and p2."""
        painter = QPainter(self.overlay_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.tool_mode == "brush":
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            pen = QPen(
                self.mask_color,
                self.brush_size,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            painter.drawLine(p1, p2)
        else:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            pen = QPen(
                Qt.GlobalColor.transparent,
                self.brush_size,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            painter.drawLine(p1, p2)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        is_pan_click = (
            event.button() == Qt.MouseButton.MiddleButton
            or self._space_held
            or (
                event.button() == Qt.MouseButton.LeftButton
                and (
                    event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    or event.modifiers() & Qt.KeyboardModifier.AltModifier
                )
            )
        )
        if is_pan_click:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._push_undo()
            self._is_drawing = True
            img_pt = self.widget_to_image(event.pos())
            self._last_img_pt = img_pt
            # Draw initial dot on mouse down
            self._draw_dot(img_pt)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        self._cursor_widget_pos = event.pos()

        if self._is_panning:
            delta = event.pos() - self._last_mouse_pos
            self.pan_offset += delta
            self._last_mouse_pos = event.pos()
            self.update()
            return

        if self._is_drawing and (event.buttons() & Qt.MouseButton.LeftButton):
            img_pt = self.widget_to_image(event.pos())
            if self._last_img_pt is not None:
                self._draw_stroke_segment(self._last_img_pt, img_pt)
            self._last_img_pt = img_pt
            self.update()
            return

        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or self._is_panning:
            self._is_panning = False
            cursor_to_restore = (
                Qt.CursorShape.OpenHandCursor if self._space_held else Qt.CursorShape.CrossCursor
            )
            self.setCursor(cursor_to_restore)

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
            self._is_drawing = False
            self._last_img_pt = None
            self.update()

    def leaveEvent(self, event):
        self._cursor_widget_pos = QPoint(-100, -100)
        self.update()

    def wheelEvent(self, event: QWheelEvent):
        # Ctrl + Wheel adjusts brush size
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = 5 if event.angleDelta().y() > 0 else -5
            self.set_brush_size(self.brush_size + delta)
            return

        # Regular wheel zooms centered on cursor
        factor = 1.15 if event.angleDelta().y() > 0 else (1.0 / 1.15)
        new_zoom = max(0.05, min(self.zoom_factor * factor, 8.0))

        mouse_pos = event.position().toPoint()
        img_pt = self.widget_to_image(mouse_pos)

        self.zoom_factor = new_zoom
        new_wx = int(img_pt.x() * self.zoom_factor + self.pan_offset.x())
        new_wy = int(img_pt.y() * self.zoom_factor + self.pan_offset.y())
        self.pan_offset += (mouse_pos - QPoint(new_wx, new_wy))

        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            if not self._is_panning:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        elif key == Qt.Key.Key_B:
            self.set_tool("brush")
        elif key == Qt.Key.Key_E:
            self.set_tool("eraser")
        elif key == Qt.Key.Key_BracketLeft:
            self.set_brush_size(self.brush_size - 5)
        elif key == Qt.Key.Key_BracketRight:
            self.set_brush_size(self.brush_size + 5)
        elif key == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.undo()
        elif key == Qt.Key.Key_F:
            self.reset_view()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            if not self._is_panning:
                self.setCursor(Qt.CursorShape.CrossCursor)
        super().keyReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Dark canvas background
        painter.fillRect(self.rect(), QColor(BG_DARK))

        if self._first_show:
            self._first_show = False
            self.reset_view()

        # Destination rect on screen
        dest_w = int(self.img_w * self.zoom_factor)
        dest_h = int(self.img_h * self.zoom_factor)
        dest_rect = QRect(self.pan_offset.x(), self.pan_offset.y(), dest_w, dest_h)

        # 2. Draw base video frame
        painter.drawImage(dest_rect, self.bg_image)

        # 3. Draw semi-transparent painted mask overlay directly with zero lag
        painter.save()
        painter.setOpacity(self.overlay_opacity)
        painter.drawImage(dest_rect, self.overlay_image)
        painter.restore()

        # 4. Draw image border
        painter.setPen(QPen(QColor("#383842"), 1))
        painter.drawRect(dest_rect)

        # 4.5. Floating Viewport HUD Guidance Badge (Top-Center)
        if self.width() > 420:
            hud_w = min(600, self.width() - 40)
            hud_h = 24
            hud_x = (self.width() - hud_w) // 2
            hud_y = 10
            hud_rect = QRect(hud_x, hud_y, hud_w, hud_h)

            painter.save()
            painter.setPen(QPen(QColor("#242A38"), 1))
            painter.setBrush(QBrush(QColor(15, 18, 25, 215)))
            painter.drawRoundedRect(hud_rect, 4, 4)

            font = painter.font()
            font.setPixelSize(11)
            painter.setFont(font)
            painter.setPen(QColor(CORRIDOR_YELLOW))
            painter.drawText(
                hud_rect,
                Qt.AlignmentFlag.AlignCenter,
                "Paint what to KEEP  |  Stay inside edges  |  Rough strokes only (AI downsamples hint)",
            )
            painter.restore()

        # 5. Draw Brush circle cursor preview
        if not self._is_panning and self.rect().contains(self._cursor_widget_pos):
            screen_brush_radius = (self.brush_size * self.zoom_factor) / 2.0
            painter.save()
            cursor_color = (
                QColor(0, 225, 255) if self.tool_mode == "brush" else QColor(255, 75, 75)
            )
            pen = QPen(cursor_color, 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(
                QBrush(QColor(cursor_color.red(), cursor_color.green(), cursor_color.blue(), 35))
            )
            painter.drawEllipse(
                QPointF(self._cursor_widget_pos),
                screen_brush_radius,
                screen_brush_radius,
            )
            # Center crosshair
            cx = self._cursor_widget_pos.x()
            cy = self._cursor_widget_pos.y()
            painter.drawLine(cx - 4, cy, cx + 4, cy)
            painter.drawLine(cx, cy - 4, cx, cy + 4)
            painter.restore()

    def get_mask_image(self) -> QImage:
        """Returns an 8-bit grayscale QImage (0 = background, 255 = foreground)."""
        ptr = self.overlay_image.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((self.img_h, self.img_w, 4))
        alpha = arr[:, :, 3]
        mask_bytes = np.where(alpha > 15, 255, 0).astype(np.uint8)
        mask_bytes = np.ascontiguousarray(mask_bytes)
        return QImage(
            mask_bytes.data, self.img_w, self.img_h, self.img_w, QImage.Format.Format_Grayscale8
        ).copy()

    @property
    def mask_image(self) -> QImage:
        """Backward-compatible property returning the 8-bit grayscale mask."""
        return self.get_mask_image()

    def has_drawn_strokes(self) -> bool:
        """Returns True if at least one mask pixel has been painted."""
        ptr = self.overlay_image.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((self.img_h, self.img_w, 4))
        return bool(np.any(arr[:, :, 3] > 15))


class MaskPainterDialog(QDialog):
    """Modern, high-performance modal workspace for drawing rough first-frame masks."""

    mask_applied = Signal(str)  # Emits saved PNG file path

    def __init__(
        self,
        frame_rgb: np.ndarray,
        clip_path: str,
        initial_mask_path: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("CorridorKey 2.0 — Paint First-Frame Mask")
        self.resize(1180, 780)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #141416;
                color: #FFFFFF;
            }}
            QPushButton {{
                background-color: #222228;
                border: 1px solid #32323A;
                border-radius: 4px;
                color: #CCCCCC;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: #2A2A34;
                border-color: #484856;
                color: #FFFFFF;
            }}
            QPushButton:checked {{
                background-color: {ACCENT_BLUE};
                color: #FFFFFF;
                border-color: {ACCENT_BLUE};
                font-weight: 700;
            }}
        """)

        self.clip_path = clip_path
        self.saved_mask_path = ""

        # Convert input frame_rgb to QImage
        h, w = frame_rgb.shape[:2]
        c = frame_rgb.shape[2] if frame_rgb.ndim == 3 else 1
        rgb_contig = np.ascontiguousarray(frame_rgb)
        if rgb_contig.dtype != np.uint8:
            rgb_contig = np.clip(rgb_contig, 0, 255).astype(np.uint8)

        self.bg_qimage = QImage(rgb_contig.data, w, h, w * c, QImage.Format.Format_RGB888).copy()

        # Load initial mask if available
        initial_mask_img = None
        if initial_mask_path and os.path.isfile(initial_mask_path):
            initial_mask_img = QImage(initial_mask_path)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)

        # 1. Top Header Toolbar
        tb = QFrame()
        tb.setFixedHeight(44)
        tb.setStyleSheet("background-color: #1A1A20; border: 1px solid #282830; border-radius: 6px;")
        tb_layout = QHBoxLayout(tb)
        tb_layout.setContentsMargins(10, 0, 10, 0)
        tb_layout.setSpacing(10)

        # Title
        lbl_head = QLabel("MASK PAINTER")
        lbl_head.setStyleSheet(
            "color: #FFFFFF; font-weight: 700; font-size: 11px; letter-spacing: 0.5px;"
        )
        tb_layout.addWidget(lbl_head)

        tb_layout.addSpacing(6)

        # Tool segmented buttons: Brush & Eraser
        self.btn_brush = QPushButton("Brush")
        self.btn_brush.setIcon(FI.BRUSH.icon(Theme.DARK))
        self.btn_brush.setIconSize(QSize(13, 13))
        self.btn_brush.setCheckable(True)
        self.btn_brush.setChecked(True)
        tip_brush = (
            "<b>Brush [B]</b><br>"
            "Paints foreground subject to <b>KEEP</b> (unpainted background is keyed out).<br>"
            "• <b>Stay inside edges:</b> Better to leave an unpainted margin inside than bleed onto green/blue background.<br>"
            "• <b>Rough strokes only:</b> No need for fine detail; the AI vision model downsamples hints to low resolution."
        )
        self.btn_brush.setToolTip(tip_brush)
        self.btn_brush.clicked.connect(lambda: self._set_tool("brush"))
        tb_layout.addWidget(self.btn_brush)

        self.btn_eraser = QPushButton("Eraser")
        self.btn_eraser.setIcon(FI.DELETE.icon(Theme.DARK))
        self.btn_eraser.setIconSize(QSize(13, 13))
        self.btn_eraser.setCheckable(True)
        tip_eraser = "<b>Eraser [E]</b><br>Erases unwanted strokes from the background."
        self.btn_eraser.setToolTip(tip_eraser)
        self.btn_eraser.clicked.connect(lambda: self._set_tool("eraser"))
        tb_layout.addWidget(self.btn_eraser)

        tb_layout.addSpacing(10)

        # Brush Size Slider
        lbl_sz = QLabel("Size:")
        lbl_sz.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        tip_sz = "<b>Brush Size</b><br>Brush diameter in pixels (hotkeys: <b>[</b> and <b>]</b>, or <b>Ctrl + Mouse Wheel</b>)."
        lbl_sz.setToolTip(tip_sz)
        tb_layout.addWidget(lbl_sz)

        self.slider_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_size.setRange(4, 250)
        self.slider_size.setValue(45)
        self.slider_size.setFixedWidth(100)
        self.slider_size.setToolTip(tip_sz)
        tb_layout.addWidget(self.slider_size)

        self.lbl_size_val = QLabel("45 px")
        self.lbl_size_val.setFixedWidth(40)
        self.lbl_size_val.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 11px;")
        self.lbl_size_val.setToolTip(tip_sz)
        self.slider_size.valueChanged.connect(self._on_size_changed)
        tb_layout.addWidget(self.lbl_size_val)

        tb_layout.addSpacing(10)

        # Opacity Slider
        lbl_op = QLabel("Opacity:")
        lbl_op.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        tip_op = "<b>Mask Opacity</b><br>Transparency of the paint overlay over the frame to clearly see the underlying subject."
        lbl_op.setToolTip(tip_op)
        tb_layout.addWidget(lbl_op)

        self.slider_op = QSlider(Qt.Orientation.Horizontal)
        self.slider_op.setRange(20, 90)
        self.slider_op.setValue(55)
        self.slider_op.setFixedWidth(80)
        self.slider_op.setToolTip(tip_op)
        tb_layout.addWidget(self.slider_op)

        self.lbl_op_val = QLabel("55%")
        self.lbl_op_val.setFixedWidth(32)
        self.lbl_op_val.setStyleSheet("color: #FFFFFF; font-weight: 600; font-size: 11px;")
        self.lbl_op_val.setToolTip(tip_op)
        self.slider_op.valueChanged.connect(self._on_opacity_changed)
        tb_layout.addWidget(self.lbl_op_val)

        tb_layout.addSpacing(10)

        # Undo & Clear buttons
        btn_undo = QPushButton("Undo")
        btn_undo.setToolTip("<b>Undo [Ctrl+Z]</b><br>Revert the last stroke.")
        btn_undo.clicked.connect(lambda: self.canvas.undo())
        tb_layout.addWidget(btn_undo)

        btn_clear = QPushButton("Clear")
        btn_clear.setIcon(FI.CLEAR_SELECTION.icon(Theme.DARK))
        btn_clear.setIconSize(QSize(12, 12))
        btn_clear.setToolTip("<b>Clear</b><br>Erase the entire mask.")
        btn_clear.clicked.connect(lambda: self.canvas.clear_mask())
        tb_layout.addWidget(btn_clear)

        btn_fit = QPushButton("Fit")
        btn_fit.setToolTip("<b>Fit View [F]</b><br>Scale frame to fit the window.")
        btn_fit.clicked.connect(lambda: self.canvas.reset_view())
        tb_layout.addWidget(btn_fit)

        tb_layout.addStretch()

        # Cancel button
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        tb_layout.addWidget(btn_cancel)

        # Save & Apply Button
        btn_save = QPushButton("Save & Apply Mask")
        btn_save.setIcon(FI.ACCEPT.icon(color=QColor("#FFFFFF")))
        btn_save.setIconSize(QSize(13, 13))
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background-color: {CORRIDOR_GREEN};
                color: #000000;
                font-weight: 700;
                border-radius: 4px;
                padding: 5px 14px;
            }}
            QPushButton:hover {{
                background-color: #00FF88;
            }}
        """)
        tip_save = (
            "<b>Save & Apply Mask</b><br>"
            "Saves the mask as a companion PNG file and attaches it to the active clip.<br>"
            "Hint Trust will be automatically set to optimal 0.75."
        )
        btn_save.setToolTip(tip_save)
        btn_save.clicked.connect(self._on_save_mask)
        tb_layout.addWidget(btn_save)

        main_layout.addWidget(tb)

        # 1.5 Prominent Subject Guidance Banner
        info_banner = QFrame()
        info_banner.setObjectName("guidanceBanner")
        info_banner.setFixedHeight(42)
        info_banner.setStyleSheet(f"""
            QFrame#guidanceBanner {{
                background-color: #161A23;
                border: 1px solid #232D3F;
                border-left: 3px solid {ACCENT_BLUE};
                border-radius: 4px;
            }}
        """)
        info_layout = QHBoxLayout(info_banner)
        info_layout.setContentsMargins(12, 4, 12, 4)
        info_layout.setSpacing(10)

        lbl_info_icon = QLabel()
        lbl_info_icon.setPixmap(FI.INFO.icon(color=QColor(ACCENT_BLUE)).pixmap(18, 18))
        info_layout.addWidget(lbl_info_icon)

        txt_vbox = QVBoxLayout()
        txt_vbox.setSpacing(2)
        txt_vbox.setContentsMargins(0, 0, 0, 0)

        lbl_keep_title = QLabel(
            "<b>PAINT WHAT TO KEEP:</b> Paint the actor or foreground subject you want to <b>PRESERVE</b> (unpainted background is keyed out)."
        )
        lbl_keep_title.setStyleSheet("color: #FFFFFF; font-size: 11px;")
        txt_vbox.addWidget(lbl_keep_title)

        lbl_keep_desc = QLabel(
            "<b>Stay slightly inside borders:</b> an inner margin is better than bleeding onto green/blue background. "
            "<b>Rough broad strokes only:</b> do not trace hair or fine edges; the AI model downsamples hints to low resolution anyway."
        )
        lbl_keep_desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        txt_vbox.addWidget(lbl_keep_desc)

        info_layout.addLayout(txt_vbox, stretch=1)
        main_layout.addWidget(info_banner)

        # 2. Main Interactive Canvas
        self.canvas = PaintCanvas(self.bg_qimage, initial_mask=initial_mask_img, parent=self)
        self.canvas.tool_changed.connect(self._on_canvas_tool_changed)
        self.canvas.brush_size_changed.connect(self._on_canvas_size_changed)
        main_layout.addWidget(self.canvas, stretch=1)

        # 3. Bottom Guidance Strip
        tip_banner = QFrame()
        tip_banner.setFixedHeight(28)
        tip_banner.setStyleSheet(
            "background-color: #16161A; border: 1px solid #222228; border-radius: 4px;"
        )
        tb_in_layout = QHBoxLayout(tip_banner)
        tb_in_layout.setContentsMargins(10, 0, 10, 0)
        lbl_info = QLabel(
            "Quick Tips:  [B] Brush  |  [E] Eraser  |  [ [ / ] ] Size  |  [Ctrl+Z] Undo  |  [Space / Middle Mouse / Ctrl+Drag] Pan  |  [Wheel] Zoom"
        )
        lbl_info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        tb_in_layout.addWidget(lbl_info)
        tb_in_layout.addStretch()

        lbl_hint_advice = QLabel(
            "Rule: Stay slightly inside subject edges. Rough strokes only — AI downsamples hint to low-res feature space."
        )
        lbl_hint_advice.setStyleSheet(f"color: {CORRIDOR_YELLOW}; font-size: 11px; font-weight: 600;")
        tb_in_layout.addWidget(lbl_hint_advice)

        main_layout.addWidget(tip_banner)

    def _set_tool(self, tool: str):
        self.btn_brush.setChecked(tool == "brush")
        self.btn_eraser.setChecked(tool == "eraser")
        self.canvas.set_tool(tool)

    def _on_canvas_tool_changed(self, tool: str):
        self.btn_brush.setChecked(tool == "brush")
        self.btn_eraser.setChecked(tool == "eraser")

    def _on_size_changed(self, val: int):
        self.lbl_size_val.setText(f"{val} px")
        self.canvas.set_brush_size(val)

    def _on_canvas_size_changed(self, val: int):
        self.slider_size.blockSignals(True)
        self.slider_size.setValue(val)
        self.lbl_size_val.setText(f"{val} px")
        self.slider_size.blockSignals(False)

    def _on_opacity_changed(self, val: int):
        self.lbl_op_val.setText(f"{val}%")
        self.canvas.set_overlay_opacity(val / 100.0)

    def _on_save_mask(self):
        """Saves mask to disk as <clip_stem>FrameHint.png and closes dialog."""
        if not self.canvas.has_drawn_strokes():
            reply = QMessageBox.question(
                self,
                "Empty Mask Warning",
                "No mask strokes have been painted.\nDo you want to save an empty mask anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        clip_p = Path(self.clip_path)
        stem = clip_p.stem

        # Save next to clip if folder writable, else save in Video cache
        candidate_dir = clip_p.parent
        out_path = candidate_dir / f"{stem}FrameHint.png"

        try:
            # Check write permission
            test_file = candidate_dir / f".test_perm_{os.getpid()}"
            test_file.touch()
            test_file.unlink()
        except Exception:
            # Fallback to user Videos directory
            candidate_dir = Path.home() / "Videos" / "CorridorKey_Hints"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            out_path = candidate_dir / f"{stem}FrameHint.png"

        # Save QImage mask to disk as standard 8-bit grayscale PNG
        mask_qimg = self.canvas.get_mask_image()
        success = mask_qimg.save(str(out_path), "PNG")
        if not success:
            QMessageBox.critical(self, "Save Error", f"Could not save mask file to:\n{out_path}")
            return

        self.saved_mask_path = str(out_path)
        self.mask_applied.emit(str(out_path))
        self.accept()
