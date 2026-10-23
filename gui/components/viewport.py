from __future__ import annotations

from typing import Optional
import cv2
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
        self.display_mode = "Wipe"  # "Wipe" (default), "Single", "Side by side"
        self.channel_mode = "Composite"  # "Composite", "Alpha", "Foreground", "Original"
        self.wipe_split = 0.5  # 0.0 to 1.0
        self.despill_strength = 0.5  # 0.0 to 1.0
        self.despill_color = "auto"  # "auto", "green", "blue"

        self._raw_rgb: Optional[np.ndarray] = None
        self._raw_alpha: Optional[np.ndarray] = None

        self.setToolTip(
            "<b>Viewport</b><br>"
            "&bull; Pan: Middle Mouse Button (MMB) or Ctrl + Left Click<br>"
            "&bull; Zoom: Mouse Wheel<br>"
            "&bull; Reset to Fit: Double Click (Left Button)<br>"
            "&bull; Wipe Split: Drag the vertical divider line"
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
        composite_override: Optional[np.ndarray] = None,
        rgba_composite: Optional[np.ndarray] = None,
    ):
        """Update active frames from numpy arrays with ultra-fast zero-copy and SIMD operations."""
        if rgb_frame is None and rgba_composite is None:
            self._raw_rgb = None
            self._raw_alpha = None
            self._raw_composite_override = None
            self._raw_rgba_composite = None
            self._current_frame = None
            self._original_frame = None
            self._alpha_frame = None
            self._composite_frame = None
            self._fg_frame = None
            self.update()
            return

        if rgba_composite is not None:
            self._raw_rgba_composite = np.ascontiguousarray(rgba_composite)
            h, w = self._raw_rgba_composite.shape[:2]
        else:
            self._raw_rgba_composite = None
            h, w = rgb_frame.shape[:2]

        self._raw_rgb = np.ascontiguousarray(rgb_frame) if rgb_frame is not None else None
        self._raw_composite_override = np.ascontiguousarray(composite_override) if composite_override is not None else None

        if self._raw_rgb is not None:
            c = self._raw_rgb.shape[2] if self._raw_rgb.ndim == 3 else 1
            self._current_frame = QImage(
                self._raw_rgb.data, w, h, w * c, QImage.Format.Format_RGB888
            ).copy()
        elif self._raw_rgba_composite is not None:
            # Fallback current frame representation
            self._current_frame = None

        if original_rgb is not None:
            original_rgb = np.ascontiguousarray(original_rgb)
            oh, ow, oc = original_rgb.shape
            self._original_frame = QImage(
                original_rgb.data, ow, oh, ow * oc, QImage.Format.Format_RGB888
            ).copy()
        else:
            self._original_frame = self._current_frame

        if alpha_matte is not None:
            a = alpha_matte[:, :, 0] if alpha_matte.ndim == 3 else alpha_matte
            if a.dtype != np.uint8:
                a = (np.clip(a, 0.0, 1.0) * 255).astype(np.uint8)
            if a.shape[:2] == (h, w):
                self._raw_alpha = np.ascontiguousarray(a)
            else:
                self._raw_alpha = None
        else:
            self._raw_alpha = None

        self._recompute_derived_frames()
        self.update()

    def _recompute_derived_frames(self):
        """Recompute Composite, Cutout FG, and Alpha using ultra-fast SIMD operations."""
        need_wipe_or_sbs = self.display_mode in ("Wipe", "Side by side")

        # FAST PATH 1: Pre-rendered RGBA Composite (e.g. from ProRes 4444 MOV, zero redundant work)
        if getattr(self, "_raw_rgba_composite", None) is not None:
            rgba = self._raw_rgba_composite
            h, w = rgba.shape[:2]
            if self.channel_mode == "Composite" or need_wipe_or_sbs:
                self._composite_frame = QImage(
                    rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888
                ).copy()
            else:
                self._composite_frame = self._current_frame

            if self.channel_mode == "Alpha":
                a = np.ascontiguousarray(rgba[:, :, 3])
                self._alpha_frame = QImage(
                    a.data, w, h, w, QImage.Format.Format_Grayscale8
                ).copy()
            else:
                self._alpha_frame = None

            if self.channel_mode == "Foreground":
                fg = np.ascontiguousarray(rgba[:, :, :3])
                self._fg_frame = QImage(
                    fg.data, w, h, w * 3, QImage.Format.Format_RGB888
                ).copy()
            else:
                self._fg_frame = self._current_frame
            return

        # FAST PATH 2: Baked checker composite override (e.g. from _checker_comp.mp4)
        if getattr(self, "_raw_composite_override", None) is not None:
            comp_rgb = self._raw_composite_override
            ch, cw, cc = comp_rgb.shape
            self._composite_frame = QImage(
                comp_rgb.data, cw, ch, cw * cc, QImage.Format.Format_RGB888
            ).copy()
            if self._raw_alpha is not None and self.channel_mode == "Alpha":
                a = self._raw_alpha
                self._alpha_frame = QImage(
                    a.data, a.shape[1], a.shape[0], a.shape[1], QImage.Format.Format_Grayscale8
                ).copy()
            else:
                self._alpha_frame = None

            if self._raw_rgb is not None and self.channel_mode == "Foreground":
                fg = self._raw_rgb
                self._fg_frame = QImage(
                    fg.data, fg.shape[1], fg.shape[0], fg.shape[1] * fg.shape[2], QImage.Format.Format_RGB888
                ).copy()
            else:
                self._fg_frame = self._composite_frame
            return

        # PATH 3: Dynamic Alpha Matte + RGB with SIMD despill
        if self._raw_rgb is None:
            return

        rgb_frame = self._raw_rgb
        h, w, c = rgb_frame.shape
        a = self._raw_alpha

        if a is not None and a.shape[:2] == (h, w):
            if self.channel_mode == "Alpha":
                self._alpha_frame = QImage(
                    a.data, w, h, w, QImage.Format.Format_Grayscale8
                ).copy()
            else:
                self._alpha_frame = None

            despilled_rgb = self._apply_despill_fast(
                rgb_frame, self.despill_strength, self.despill_color
            )

            if self.channel_mode == "Composite" or need_wipe_or_sbs:
                rgba = cv2.cvtColor(despilled_rgb, cv2.COLOR_RGB2RGBA)
                rgba[:, :, 3] = a
                self._composite_frame = QImage(
                    rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888
                ).copy()
            else:
                self._composite_frame = self._current_frame

            if self.channel_mode == "Foreground":
                fg = cv2.bitwise_and(despilled_rgb, despilled_rgb, mask=a)
                self._fg_frame = QImage(
                    fg.data, w, h, w * 3, QImage.Format.Format_RGB888
                ).copy()
            else:
                self._fg_frame = self._current_frame
        else:
            self._alpha_frame = None
            self._composite_frame = self._current_frame
            self._fg_frame = self._current_frame

    def reset_view(self):
        """Reset zoom and pan to fit viewport."""
        self.zoom_factor = 1.0
        self.pan_offset = QPoint(0, 0)
        self.update()

    def set_playing(self, is_playing: bool):
        """Toggle smooth transform off during playback for 60+ FPS, on when paused for pristine inspection."""
        self._is_playing = bool(is_playing)
        self.update()

    def set_channel_mode(self, mode: str):
        self.channel_mode = mode
        self._recompute_derived_frames()
        self.update()

    def set_display_mode(self, mode: str):
        self.display_mode = mode
        self._recompute_derived_frames()
        self.update()

    def set_despill_strength(self, strength: float):
        self.despill_strength = max(0.0, min(1.0, float(strength)))

    def set_despill_color(self, color: str):
        self.despill_color = str(color).strip().lower()

    @staticmethod
    def _apply_despill_fast(
        rgb: np.ndarray, strength: float = 0.5, color: str = "auto"
    ) -> np.ndarray:
        if strength <= 0.0 or rgb is None:
            return rgb
        r, g, b = cv2.split(rgb)
        mode = (color or "auto").strip().lower()
        if mode == "auto":
            h, w = rgb.shape[:2]
            border = max(2, min(h, w) // 30)
            edge_g = float(g[:border, :].mean() + g[-border:, :].mean())
            edge_b = float(b[:border, :].mean() + b[-border:, :].mean())
            mode = "blue" if edge_b > edge_g else "green"

        if mode == "blue":
            rg_avg = cv2.addWeighted(r, 0.5, g, 0.5, 0)
            spill = cv2.subtract(b, rg_avg)
            if strength < 1.0:
                spill = cv2.multiply(spill, float(strength))
            clean_b = cv2.subtract(b, spill)
            return cv2.merge([r, g, clean_b])
        else:
            rb_avg = cv2.addWeighted(r, 0.5, b, 0.5, 0)
            spill = cv2.subtract(g, rb_avg)
            if strength < 1.0:
                spill = cv2.multiply(spill, float(strength))
            clean_g = cv2.subtract(g, spill)
            return cv2.merge([r, clean_g, b])

    def _get_active_image(self) -> Optional[QImage]:
        if self.channel_mode == "Original":
            # In Wipe or Side by side mode, compare Original against rendered Composite
            if (
                self.display_mode in ("Wipe", "Side by side")
                and self._composite_frame is not None
                and self._composite_frame is not self._original_frame
            ):
                return self._composite_frame
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
        if getattr(self, "_is_playing", False):
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        else:
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
                "Drag & drop video clip or click 'File' to begin",
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
