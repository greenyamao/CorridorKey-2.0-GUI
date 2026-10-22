from __future__ import annotations

from typing import Optional
import numpy as np

from PySide6.QtCore import Qt, QRect, QPoint, QRectF, Signal
from PySide6.QtGui import (
    QPainter,
    QPixmap,
    QImage,
    QColor,
    QPen,
    QBrush,
    QMouseEvent,
    QWheelEvent,
    QFont,
)
from PySide6.QtWidgets import QWidget

from gui.styles.theme import CORRIDOR_GREEN, CORRIDOR_YELLOW, BG_DARK, ACCENT_BLUE


class ViewportWidget(QWidget):
    """High-fidelity video viewport with checkerboard transparency, pan/zoom, and wipe modes."""

    wipe_pos_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Image buffers (QImage)
        self._current_frame: Optional[QImage] = None
        self._original_frame: Optional[QImage] = None
        self._alpha_frame: Optional[QImage] = None
        self._composite_frame: Optional[QImage] = None
        self._fg_frame: Optional[QImage] = None

        # Display settings
        self.display_mode = "Single"  # "Single", "Wipe", "Side by side"
        self.channel_mode = "Composite"  # "Composite", "Alpha", "Foreground", "Original"
        self.wipe_split = 0.5  # 0.0 to 1.0

        self.setToolTip(
            "<b>Окно просмотра (Viewport)</b><br>"
            "• Панорамирование: средняя кнопка мыши (СКМ) или Ctrl + ЛКМ<br>"
            "• Масштаб (Zoom): колесико мыши<br>"
            "• Сброс масштаба (Fit): двойной клик ЛКМ<br>"
            "• Шторка сравнения (Wipe): потяните желтую линию разделителя"
        )

        # Pan and Zoom
        self.zoom_factor = 1.0
        self.pan_offset = QPoint(0, 0)
        self._drag_start = QPoint()
        self._is_panning = False
        self._is_dragging_wipe = False

        # Checkerboard tile brush (16x16 alternating squares)
        self._checker_brush = self._create_checker_brush(16)

    def _create_checker_brush(self, tile_size: int = 16) -> QBrush:
        pix = QPixmap(tile_size * 2, tile_size * 2)
        p = QPainter(pix)
        c1 = QColor(22, 22, 26)
        c2 = QColor(34, 34, 38)
        p.fillRect(0, 0, tile_size, tile_size, c1)
        p.fillRect(tile_size, 0, tile_size, tile_size, c2)
        p.fillRect(0, tile_size, tile_size, tile_size, c2)
        p.fillRect(tile_size, tile_size, tile_size, tile_size, c1)
        p.end()
        return QBrush(pix)

    def set_frames(
        self,
        rgb_frame: Optional[np.ndarray],
        alpha_matte: Optional[np.ndarray] = None,
        original_rgb: Optional[np.ndarray] = None,
    ):
        """Update active frames from numpy arrays with clean memory buffers and proper alpha blending."""
        if rgb_frame is not None:
            rgb_frame = np.ascontiguousarray(rgb_frame)
            if rgb_frame.dtype != np.uint8:
                rgb_frame = np.clip(rgb_frame, 0, 255).astype(np.uint8)

            h, w, c = rgb_frame.shape
            self._current_frame = QImage(
                rgb_frame.data, w, h, w * c, QImage.Format.Format_RGB888
            ).copy()
        else:
            self._current_frame = None

        if original_rgb is not None:
            original_rgb = np.ascontiguousarray(original_rgb)
            if original_rgb.dtype != np.uint8:
                original_rgb = np.clip(original_rgb, 0, 255).astype(np.uint8)
            h, w, c = original_rgb.shape
            self._original_frame = QImage(
                original_rgb.data, w, h, w * c, QImage.Format.Format_RGB888
            ).copy()
        elif rgb_frame is not None and self._original_frame is None:
            self._original_frame = self._current_frame

        if alpha_matte is not None and rgb_frame is not None:
            h, w = rgb_frame.shape[:2]
            # Ensure alpha is 2D uint8
            if alpha_matte.ndim == 3:
                a = alpha_matte[:, :, 0]
            else:
                a = alpha_matte
            if a.dtype != np.uint8:
                a = (np.clip(a, 0.0, 1.0) * 255).astype(np.uint8)

            # Ensure shapes match
            if a.shape[:2] == (h, w):
                a = np.ascontiguousarray(a)
                # 1. Grayscale mask image
                self._alpha_frame = QImage(
                    a.data, w, h, w, QImage.Format.Format_Grayscale8
                ).copy()

                # 2. RGBA Composite image (alpha transparency)
                rgba = np.dstack((rgb_frame[:, :, :3], a))
                rgba = np.ascontiguousarray(rgba)
                self._composite_frame = QImage(
                    rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888
                ).copy()

                # 3. Cutout Foreground over black
                fg = (rgb_frame.astype(np.float32) * (a[:, :, None].astype(np.float32) / 255.0)).astype(np.uint8)
                fg = np.ascontiguousarray(fg)
                self._fg_frame = QImage(
                    fg.data, w, h, w * 3, QImage.Format.Format_RGB888
                ).copy()
            else:
                self._alpha_frame = None
                self._composite_frame = self._current_frame
                self._fg_frame = self._current_frame
        else:
            self._alpha_frame = None
            self._composite_frame = self._current_frame
            self._fg_frame = self._current_frame

        self.update()

    def reset_view(self):
        """Reset zoom and pan to fit viewport."""
        self.zoom_factor = 1.0
        self.pan_offset = QPoint(0, 0)
        self.update()

    def set_channel_mode(self, mode: str):
        self.channel_mode = mode
        self.update()

    def set_display_mode(self, mode: str):
        self.display_mode = mode
        self.update()

    def _get_active_image(self) -> Optional[QImage]:
        if self.channel_mode == "Original":
            return self._original_frame or self._current_frame
        elif self.channel_mode == "Alpha":
            return self._alpha_frame
        elif self.channel_mode == "Foreground":
            return self._fg_frame or self._current_frame
        else:  # "Composite"
            return self._composite_frame or self._current_frame

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 1. Solid canvas background
        painter.fillRect(self.rect(), QColor(BG_DARK))

        active_img = self._get_active_image()
        orig_img = self._original_frame or self._current_frame

        if (active_img is None or active_img.isNull()) and (orig_img is None or orig_img.isNull()):
            # Draw placeholder message
            painter.setPen(QColor("#777777"))
            painter.setFont(QFont("Segoe UI", 13))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Drag & drop video clip or click '+ File' to begin",
            )
            return

        ref_img = orig_img if orig_img is not None and not orig_img.isNull() else active_img
        if ref_img is None or ref_img.isNull():
            return

        iw = ref_img.width()
        ih = ref_img.height()
        vw = self.width()
        vh = self.height()

        # Handle "Alpha" channel when no alpha mask is available yet
        if self.channel_mode == "Alpha" and (active_img is None or active_img.isNull()):
            scale = min(vw / iw, vh / ih) * self.zoom_factor
            dest_w = int(iw * scale)
            dest_h = int(ih * scale)
            dest_x = (vw - dest_w) // 2 + self.pan_offset.x()
            dest_y = (vh - dest_h) // 2 + self.pan_offset.y()
            dest_rect = QRect(dest_x, dest_y, dest_w, dest_h)

            painter.fillRect(dest_rect, QColor("#000000"))
            painter.setPen(QColor(CORRIDOR_YELLOW))
            painter.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            painter.drawText(dest_rect, Qt.AlignmentFlag.AlignCenter, "No Alpha Mask Yet\n(Attach an Alpha Hint or click 'Render')")
            return

        # =====================================================================
        # DISPLAY MODE: Side by Side (Undistorted, both images preserve aspect ratio)
        # =====================================================================
        if self.display_mode == "Side by side" and orig_img is not None and active_img is not None:
            gap = 14
            avail_w = max(50, (vw - gap - 20) // 2)
            avail_h = max(50, vh - 20)

            scale = min(avail_w / iw, avail_h / ih) * self.zoom_factor
            dw = int(iw * scale)
            dh = int(ih * scale)
            cy = (vh - dh) // 2 + self.pan_offset.y()

            left_x = (vw // 2) - dw - (gap // 2) + self.pan_offset.x()
            right_x = (vw // 2) + (gap // 2) + self.pan_offset.x()

            left_rect = QRect(left_x, cy, dw, dh)
            right_rect = QRect(right_x, cy, dw, dh)

            # Left: Original
            painter.drawImage(left_rect, orig_img)
            painter.setPen(QPen(QColor("#383840"), 1))
            painter.drawRect(left_rect)

            # Left Label
            painter.setPen(QColor("#AAAAAA"))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(left_rect.adjusted(6, 6, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, "ORIGINAL")

            # Right: Active Channel
            painter.fillRect(right_rect, self._checker_brush)
            painter.drawImage(right_rect, active_img)
            painter.setPen(QPen(QColor(ACCENT_BLUE), 1))
            painter.drawRect(right_rect)

            # Right Label
            painter.setPen(QColor(ACCENT_BLUE))
            painter.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            painter.drawText(right_rect.adjusted(6, 6, 0, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, self.channel_mode.upper())
            return

        # =====================================================================
        # DISPLAY MODE: Single or Wipe
        # =====================================================================
        scale = min(vw / iw, vh / ih) * self.zoom_factor
        dest_w = int(iw * scale)
        dest_h = int(ih * scale)
        dest_x = (vw - dest_w) // 2 + self.pan_offset.x()
        dest_y = (vh - dest_h) // 2 + self.pan_offset.y()
        dest_rect = QRect(dest_x, dest_y, dest_w, dest_h)

        if self.display_mode == "Wipe" and orig_img is not None and active_img is not None:
            # Interactive Wipe Split
            split_x = dest_rect.left() + int(dest_rect.width() * self.wipe_split)

            # Checkerboard under entire frame
            painter.fillRect(dest_rect, self._checker_brush)

            # Left Side (Original)
            painter.save()
            painter.setClipRect(QRect(dest_rect.left(), dest_rect.top(), max(0, split_x - dest_rect.left()), dest_rect.height()))
            painter.drawImage(dest_rect, orig_img)
            painter.restore()

            # Right Side (Active Channel)
            painter.save()
            painter.setClipRect(QRect(split_x, dest_rect.top(), max(0, dest_rect.right() - split_x + 1), dest_rect.height()))
            painter.drawImage(dest_rect, active_img)
            painter.restore()

            # Wipe divider line
            painter.setPen(QPen(QColor(CORRIDOR_YELLOW), 2))
            painter.drawLine(split_x, dest_rect.top(), split_x, dest_rect.bottom())

            # Divider handle circle
            handle_y = dest_rect.top() + dest_rect.height() // 2
            painter.setBrush(QBrush(QColor(CORRIDOR_YELLOW)))
            painter.setPen(QPen(QColor("#000000"), 1))
            painter.drawEllipse(QPoint(split_x, handle_y), 5, 5)

        else:
            # Single View
            if self.channel_mode == "Composite":
                painter.fillRect(dest_rect, self._checker_brush)
            elif self.channel_mode == "Foreground" or self.channel_mode == "Alpha":
                painter.fillRect(dest_rect, QColor("#000000"))

            painter.drawImage(dest_rect, active_img)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._is_panning = True
            self._drag_start = event.pos()
        elif event.button() == Qt.MouseButton.LeftButton and self.display_mode == "Wipe":
            self._is_dragging_wipe = True
            self._update_wipe_split(event.pos().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            delta = event.pos() - self._drag_start
            self._drag_start = event.pos()
            self.pan_offset += delta
            self.update()
        elif self._is_dragging_wipe:
            self._update_wipe_split(event.pos().x())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._is_panning = False
        self._is_dragging_wipe = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.reset_view()
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta > 0:
            self.zoom_factor = min(8.0, self.zoom_factor * 1.15)
        else:
            self.zoom_factor = max(0.15, self.zoom_factor / 1.15)
        self.update()

    def _update_wipe_split(self, mouse_x: int):
        vw = self.width()
        active = self._get_active_image()
        if active is not None and not active.isNull():
            iw = active.width()
            ih = active.height()
            scale = min(vw / iw, self.height() / ih) * self.zoom_factor
            dest_w = int(iw * scale)
            dest_x = (vw - dest_w) // 2 + self.pan_offset.x()
            if dest_w > 0:
                self.wipe_split = max(0.0, min(1.0, (mouse_x - dest_x) / dest_w))
        else:
            self.wipe_split = max(0.0, min(1.0, mouse_x / max(1, vw)))

        self.wipe_pos_changed.emit(self.wipe_split)
        self.update()
