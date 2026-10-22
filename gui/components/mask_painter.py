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
    QPixmap,
    QPainter,
    QPen,
    QColor,
    QBrush,
    QFont,
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
    QToolTip,
    QMessageBox,
)
from qfluentwidgets import FluentIcon as FI, Theme

from gui.styles.theme import (
    BG_DARK,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    ACCENT_BLUE,
    CORRIDOR_GREEN,
    CORRIDOR_YELLOW,
)


class PaintCanvas(QWidget):
    """Zero-lag hardware-accelerated painting canvas with pan, zoom, and undo."""

    def __init__(self, bg_image: QImage, initial_mask: Optional[QImage] = None, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.bg_image = bg_image
        self.img_w = bg_image.width()
        self.img_h = bg_image.height()

        # Grayscale mask (255 = foreground subject, 0 = background)
        self.mask_image = QImage(self.img_w, self.img_h, QImage.Format.Format_Grayscale8)
        if initial_mask is not None and not initial_mask.isNull():
            # Resize initial mask if dimensions mismatch
            if initial_mask.size() != self.bg_image.size():
                scaled_init = initial_mask.scaled(
                    self.img_w,
                    self.img_h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.mask_image = scaled_init.convertToFormat(QImage.Format.Format_Grayscale8)
            else:
                self.mask_image = initial_mask.convertToFormat(QImage.Format.Format_Grayscale8)
        else:
            self.mask_image.fill(0)

        # Undo stack (stores up to 12 snapshot copies of mask)
        self.undo_stack: List[QImage] = []
        self._push_undo()

        # Tool parameters
        self.tool_mode = "brush"  # "brush" | "eraser"
        self.brush_size = 45  # In image pixels
        self.overlay_opacity = 0.55  # 0.20 to 0.90
        self.mask_color = QColor(0, 225, 255)  # High-visibility neon cyan

        # Pan and Zoom transform
        self.zoom_factor = 1.0
        self.pan_offset = QPoint(0, 0)
        self._is_panning = False
        self._is_drawing = False
        self._last_mouse_pos = QPoint()
        self._last_img_pt: Optional[QPointF] = None
        self._cursor_widget_pos = QPoint(-100, -100)

        # Initial fit
        self._first_show = True

    def _push_undo(self):
        if len(self.undo_stack) >= 12:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.mask_image.copy())

    def undo(self):
        if len(self.undo_stack) > 1:
            self.undo_stack.pop()  # Remove current state
            self.mask_image = self.undo_stack[-1].copy()
            self.update()

    def clear_mask(self):
        self._push_undo()
        self.mask_image.fill(0)
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
        self.brush_size = max(4, min(size, 300))
        self.update()

    def set_overlay_opacity(self, opacity: float):
        self.overlay_opacity = max(0.1, min(opacity, 0.95))
        self.update()

    def set_tool(self, tool: str):
        self.tool_mode = tool
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

    def _draw_stroke_segment(self, p1: QPointF, p2: QPointF):
        """Draws smooth anti-aliased line stroke with round caps directly on the grayscale mask."""
        painter = QPainter(self.mask_image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(255, 255, 255) if self.tool_mode == "brush" else QColor(0, 0, 0)
        pen = QPen(
            color,
            self.brush_size,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and (event.modifiers() & Qt.KeyboardModifier.ControlModifier or event.modifiers() & Qt.KeyboardModifier.AltModifier)
        ):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self._push_undo()
            self._is_drawing = True
            img_pt = self.widget_to_image(event.pos())
            self._last_img_pt = img_pt
            # Draw initial dot
            self._draw_stroke_segment(img_pt, img_pt)
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
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing:
            self._is_drawing = False
            self._last_img_pt = None
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

        # Anchor zoom around mouse position
        mouse_pos = event.position().toPoint()
        img_pt = self.widget_to_image(mouse_pos)

        self.zoom_factor = new_zoom
        new_wx = int(img_pt.x() * self.zoom_factor + self.pan_offset.x())
        new_wy = int(img_pt.y() * self.zoom_factor + self.pan_offset.y())
        self.pan_offset += (mouse_pos - QPoint(new_wx, new_wy))

        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_B:
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Canvas background
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

        # 3. Draw semi-transparent colored mask overlay
        painter.save()
        # Create translucent tinted mask representation
        painter.setOpacity(self.overlay_opacity)
        # Using composition mode to render mask as vibrant cyan highlight
        # Fast conversion: create RGBA overlay from mask_image
        w_sub = self.mask_image.width()
        h_sub = self.mask_image.height()

        # Direct blit of colored mask:
        # Convert mask Grayscale8 to tinted color on the fly
        # To make it zero-lag, we use QPainter CompositionMode_Screen or draw cyan with mask
        mask_rgba = QImage(w_sub, h_sub, QImage.Format.Format_ARGB32_Premultiplied)
        mask_rgba.fill(QColor(0, 0, 0, 0))

        # Paint cyan into mask_rgba masked by self.mask_image
        p_mask = QPainter(mask_rgba)
        p_mask.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p_mask.drawImage(0, 0, self.mask_image)
        p_mask.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p_mask.fillRect(0, 0, w_sub, h_sub, self.mask_color)
        p_mask.end()

        painter.drawImage(dest_rect, mask_rgba)
        painter.restore()

        # 4. Draw image border
        painter.setPen(QPen(QColor("#383842"), 1))
        painter.drawRect(dest_rect)

        # 5. Draw Brush circle cursor preview
        if not self._is_panning and self.rect().contains(self._cursor_widget_pos):
            screen_brush_radius = (self.brush_size * self.zoom_factor) / 2.0
            painter.save()
            cursor_color = QColor(0, 225, 255) if self.tool_mode == "brush" else QColor(255, 75, 75)
            pen = QPen(cursor_color, 1.5, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(cursor_color.red(), cursor_color.green(), cursor_color.blue(), 30)))
            painter.drawEllipse(
                QPointF(self._cursor_widget_pos),
                screen_brush_radius,
                screen_brush_radius,
            )
            # Tiny center crosshair
            painter.drawLine(
                self._cursor_widget_pos.x() - 3,
                self._cursor_widget_pos.y(),
                self._cursor_widget_pos.x() + 3,
                self._cursor_widget_pos.y(),
            )
            painter.drawLine(
                self._cursor_widget_pos.x(),
                self._cursor_widget_pos.y() - 3,
                self._cursor_widget_pos.x(),
                self._cursor_widget_pos.y() + 3,
            )
            painter.restore()


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
        lbl_head.setStyleSheet("color: #FFFFFF; font-weight: 700; font-size: 11px; letter-spacing: 0.5px;")
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
            "Paints subject silhouette with semi-transparent cyan overlay.<br>"
            "<i>Tip: Paint the body with broad strokes; fine hair and edges are extracted automatically.</i>"
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

        # 2. Main Interactive Canvas
        self.canvas = PaintCanvas(self.bg_qimage, initial_mask=initial_mask_img, parent=self)
        main_layout.addWidget(self.canvas, stretch=1)

        # 3. Bottom Guidance Strip
        tip_banner = QFrame()
        tip_banner.setFixedHeight(28)
        tip_banner.setStyleSheet("background-color: #16161A; border: 1px solid #222228; border-radius: 4px;")
        tb_in_layout = QHBoxLayout(tip_banner)
        tb_in_layout.setContentsMargins(10, 0, 10, 0)
        lbl_info = QLabel(
            "Quick Tips:  [B] Brush  |  [E] Eraser  |  [ [ / ] ] Size  |  [Ctrl+Z] Undo  |  [Middle Mouse / Ctrl+Drag] Pan  |  [Wheel] Zoom"
        )
        lbl_info.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        tb_in_layout.addWidget(lbl_info)
        tb_in_layout.addStretch()

        lbl_hint_advice = QLabel("Paint body silhouette with broad strokes. Fine hair and transparent edges are extracted automatically by AI.")
        lbl_hint_advice.setStyleSheet(f"color: {CORRIDOR_YELLOW}; font-size: 11px; font-weight: 600;")
        tb_in_layout.addWidget(lbl_hint_advice)

        main_layout.addWidget(tip_banner)

    def _set_tool(self, tool: str):
        self.btn_brush.setChecked(tool == "brush")
        self.btn_eraser.setChecked(tool == "eraser")
        self.canvas.set_tool(tool)

    def _on_size_changed(self, val: int):
        self.lbl_size_val.setText(f"{val} px")
        self.canvas.set_brush_size(val)

    def _on_opacity_changed(self, val: int):
        self.lbl_op_val.setText(f"{val}%")
        self.canvas.set_overlay_opacity(val / 100.0)

    def _on_save_mask(self):
        """Saves mask to disk as <clip_stem>FrameHint.png and closes dialog."""
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
        success = self.canvas.mask_image.save(str(out_path), "PNG")
        if not success:
            QMessageBox.critical(self, "Save Error", f"Could not save mask file to:\n{out_path}")
            return

        self.saved_mask_path = str(out_path)
        self.mask_applied.emit(str(out_path))
        self.accept()
