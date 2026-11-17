"""
picker.py — Channel picker overlay (Sonic Riders hex carousel ref)

v0.3.7 changes (per user feedback):
  - REMOVED E/B button prompts (were cut off + not useful)
  - Thumbs now show the CURRENTLY-AIRING video's preview image (if user
    dropped a <video-stem>.png alongside the .mp4). Falls back to channel
    thumb, then to a colored rect with channel number.
  - Info panel shows the channel description + currently-playing video's
    description (if user dropped a <video-stem>.txt alongside the .mp4).
  - "Next break" countdown removed (was hardcoded to 12:40).

Behavior: ←/→ moves selection (wraps), Enter tunes, Backspace cancels.
MUST overlay without stopping Live video — this widget paints over the live
video widget but doesn't touch VlcPlayer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QFontMetrics, QPen, QLinearGradient, QPixmap, QPainterPath,
)
from PySide6.QtWidgets import QWidget

from .base import (
    BaseScreen, paint_texture, draw_text, ellipse_rect, paint_glow, load_texture,
    PICKER_THUMB_BORDER_DIM, PICKER_THUMB_BORDER_BRIGHT,
    PICKER_NAME_FILL, PICKER_INFO_FILL, PICKER_DESC_TOP, PICKER_DESC_BOT,
    PICKER_DESC_BORDER,
    GOLD, TEXT_PRIMARY, TEXT_DIM, INK, NAVY, UI_FONT,
)


class PickerScreen(BaseScreen):
    """Channel picker overlay ( overlays on Live screen)."""

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.selected_idx = 0
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)  # transparent over video

    def on_show(self):
        # Start on current channel
        if self.main.current_channel:
            self.selected_idx = next(
                (i for i, ch in enumerate(self.main.catalog.channels)
                 if ch.id == self.main.current_channel.id), 0
            )
        else:
            self.selected_idx = 0
        self.update()

    def _currently_playing_video(self, ch):
        """The video airing on this channel right now (v0.7.0: from the
        broadcast timeline, so it agrees with the guide and the player)."""
        try:
            air = self.main.timeline_for(ch).airing_at(self.main.clock.now())
            return air.video if air is not None else None
        except Exception:
            return None

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()

            # ── Background texture (picker_bg.png) ──────────────────────────
            picker_tex = load_texture("picker_bg.png")
            if picker_tex is not None and not picker_tex.isNull():
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                painter.drawPixmap(0, 0, picker_tex)
            else:
                # Fallback: gradient
                grad = QLinearGradient(0, 0, 0, h)
                grad.setColorAt(0.0, QColor("#6AA9E8"))
                grad.setColorAt(0.6, QColor("#2F6FC0"))
                grad.setColorAt(1.0, QColor("#245AA0"))
                painter.fillRect(self.rect(), grad)

            channels = self.main.catalog.channels
            if not channels:
                empty_font = QFont(UI_FONT)
                empty_font.setPixelSize(28)
                painter.setFont(empty_font)
                painter.setPen(QColor(0, 0, 0, 200))
                painter.drawText(QRectF(0, h // 2 - 20, w, 40),
                                  Qt.AlignCenter,
                                  "No channels in catalog — drop folders in catalog\\")
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(0, h // 2 - 22, w, 40),
                                  Qt.AlignCenter,
                                  "No channels in catalog — drop folders in catalog\\")
                hint_font = QFont(UI_FONT)
                hint_font.setPixelSize(20)
                painter.setFont(hint_font)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRectF(0, 412, w, 24),
                                  Qt.AlignCenter,
                                  "Press BACKSPACE to return")
                return

            # ── Title "Channel Select" 44px at 40,22 ─────────────────────────
            # (Removed E/B button prompts per user request — they were cut off
            #  and not useful since the user has the controls memorized.)
            title_font = QFont(UI_FONT)
            title_font.setPixelSize(44)
            draw_text(painter, x=40, y=22 + 36,  # +36 for baseline
                      text="Channel Select",
                      pixel_size=44, color=TEXT_PRIMARY,
                      shadow=True, bold=True, font=title_font)

            # ── Thumb tray ────────────────────────────────────────────────────
            tray_x, tray_y = 40, 92
            tray_w, tray_h = 640, 124
            tray_rect = QRectF(tray_x, tray_y, tray_w, tray_h)

            painter.setBrush(QColor(20, 50, 110, 140))   # ~0.55 alpha
            painter.setPen(QPen(QColor(PICKER_DESC_BORDER), 4))
            painter.drawRoundedRect(tray_rect, 12, 12)

            # Lay out thumbs centered in tray
            n = len(channels)
            thumb_w_normal, thumb_h_normal = 100, 78
            thumb_w_sel, thumb_h_sel = 120, 96
            gap = 14

            # Compute total width
            total_w = sum(thumb_w_sel if i == self.selected_idx else thumb_w_normal
                          for i in range(n)) + gap * (n - 1)
            tx = tray_x + (tray_w - total_w) // 2
            ty_normal = tray_y + (tray_h - thumb_h_normal) // 2
            ty_sel = tray_y + (tray_h - thumb_h_sel) // 2

            for i, ch in enumerate(channels):
                is_sel = (i == self.selected_idx)
                tw = thumb_w_sel if is_sel else thumb_w_normal
                th = thumb_h_sel if is_sel else thumb_h_normal
                ty = ty_sel if is_sel else ty_normal
                trect = QRectF(tx, ty, tw, th)

                # Glow for selected
                if is_sel:
                    paint_glow(painter,
                               x=int(tx - 9), y=int(ty - 9),
                               w=tw + 18, h=th + 18,
                               color=QColor(255, 255, 255, 180),
                               radius=12, shape="round")

                # Determine what to show in the thumb:
                # 1. Currently-playing video's preview image (if user dropped one)
                # 2. Else channel thumb (if set)
                # 3. Else colored rect with channel number
                painter.setOpacity(1.0 if is_sel else 0.75)
                painter.setPen(QPen(QColor(PICKER_THUMB_BORDER_BRIGHT if is_sel
                                            else PICKER_THUMB_BORDER_DIM),
                                    4 if is_sel else 3))
                painter.setBrush(QColor(ch.color))
                painter.drawRoundedRect(trect, 8, 8)

                # Try to find the currently-playing video for this channel
                current_video = self._currently_playing_video(ch) if is_sel else None
                thumb_image_path = None
                if current_video and current_video.preview:
                    thumb_image_path = current_video.preview
                elif ch.thumb:
                    thumb_image_path = ch.thumb

                if thumb_image_path:
                    project_root = Path(__file__).resolve().parent.parent.parent
                    full_path = Path(thumb_image_path)
                    if not full_path.is_absolute():
                        full_path = project_root / thumb_image_path
                    if full_path.exists():
                        pm = QPixmap(str(full_path))
                        if not pm.isNull():
                            painter.setPen(Qt.NoPen)
                            painter.setBrush(Qt.NoBrush)
                            painter.save()
                            clip_path = QPainterPath()
                            clip_path.addRoundedRect(trect, 8, 8)
                            painter.setClipPath(clip_path)
                            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                            # Cover-fit
                            pm_w = pm.width()
                            pm_h = pm.height()
                            scale = max(tw / pm_w, th / pm_h)
                            scaled_w = int(pm_w * scale)
                            scaled_h = int(pm_h * scale)
                            sx = int(tx - (scaled_w - tw) / 2)
                            sy = int(ty - (scaled_h - th) / 2)
                            painter.drawPixmap(sx, sy, scaled_w, scaled_h, pm)
                            painter.restore()
                            # Re-draw border on top
                            painter.setPen(QPen(QColor(PICKER_THUMB_BORDER_BRIGHT if is_sel
                                                        else PICKER_THUMB_BORDER_DIM),
                                                4 if is_sel else 3))
                            painter.setBrush(Qt.NoBrush)
                            painter.drawRoundedRect(trect, 8, 8)

                # Channel number overlay (30px white)
                ch_num_font = QFont(UI_FONT)
                ch_num_font.setPixelSize(30)
                painter.setFont(ch_num_font)
                painter.setPen(QColor(0, 0, 0, 140))
                painter.drawText(trect.adjusted(2, 2, 0, 0),
                                  Qt.AlignCenter, f"{ch.number:02d}")
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(trect, Qt.AlignCenter, f"{ch.number:02d}")

                tx += tw + gap

            painter.setOpacity(1.0)

            # ── Name tab (left, bottom-right rounded) ────────────────────────
            sel_ch = channels[self.selected_idx]
            name_x, name_y = 0, 244
            name_w, name_h = 380, 56
            name_rect = QRectF(name_x, name_y, name_w, name_h)
            name_path = QPainterPath()
            name_path.moveTo(name_x, name_y)
            name_path.lineTo(name_x + name_w - 28, name_y)
            name_path.arcTo(QRectF(name_x + name_w - 56, name_y, 56, 56), 90, -90)
            name_path.lineTo(name_x, name_y + name_h)
            name_path.closeSubpath()

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(PICKER_NAME_FILL))
            painter.drawPath(name_path)

            name_font = QFont(UI_FONT)
            name_font.setPixelSize(36)
            painter.setFont(name_font)
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(name_x + 24 + 2, name_y + 2,
                                     name_w - 28 - 24, name_h),
                              Qt.AlignVCenter | Qt.AlignLeft, sel_ch.name)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(name_x + 24, name_y,
                                     name_w - 28 - 24, name_h),
                              Qt.AlignVCenter | Qt.AlignLeft, sel_ch.name)

            # ── Info panel (right) — now shows channel desc + currently- ─────
            # playing video's description (if user dropped .txt files). ─────
            info_x, info_y = 430, 236
            info_w, info_h = 250, 132
            info_rect = QRectF(info_x, info_y, info_w, info_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(PICKER_INFO_FILL))
            painter.drawRoundedRect(info_rect, 10, 10)

            # Header strip
            header_rect = QRectF(info_x, info_y, info_w, 30)
            painter.setBrush(QColor(PICKER_NAME_FILL))
            painter.drawRoundedRect(header_rect, 10, 10)
            painter.setBrush(QColor(PICKER_NAME_FILL))
            painter.drawRect(QRectF(info_x, info_y + 20, info_w, 10))

            hdr_font = QFont(UI_FONT)
            hdr_font.setPixelSize(22)
            painter.setFont(hdr_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(info_x + 14, info_y, info_w - 28, 30),
                              Qt.AlignVCenter | Qt.AlignLeft, "Now Airing")

            # Body: show the currently-playing video's title + description
            current_video = self._currently_playing_video(sel_ch)
            body_font = QFont(UI_FONT)
            body_font.setPixelSize(18)
            painter.setFont(body_font)
            painter.setPen(QColor(PICKER_NAME_FILL))

            if current_video:
                # Video title
                title_text = current_video.title
                # Truncate to fit
                fm = QFontMetrics(body_font)
                if fm.horizontalAdvance(title_text) > info_w - 28:
                    while title_text and fm.horizontalAdvance(title_text + "...") > info_w - 28:
                        title_text = title_text[:-1]
                    title_text = title_text + "..."
                painter.drawText(QRectF(info_x + 14, info_y + 36, info_w - 28, 22),
                                  Qt.AlignVCenter | Qt.AlignLeft, title_text)
                # Description (if user dropped a .txt file)
                if current_video.description:
                    desc_text = current_video.description
                    # Take first 3 lines or so to fit
                    lines = desc_text.split("\n")[:3]
                    for li, line in enumerate(lines):
                        line_disp = line
                        if fm.horizontalAdvance(line_disp) > info_w - 28:
                            while line_disp and fm.horizontalAdvance(line_disp + "...") > info_w - 28:
                                line_disp = line_disp[:-1]
                            line_disp = line_disp + "..."
                        painter.drawText(QRectF(info_x + 14, info_y + 60 + li * 18,
                                                 info_w - 28, 18),
                                          Qt.AlignVCenter | Qt.AlignLeft, line_disp)
            else:
                painter.drawText(QRectF(info_x + 14, info_y + 36, info_w - 28, 22),
                                  Qt.AlignVCenter | Qt.AlignLeft, "(no schedule info)")

            # ── Description bar (bottom, full width) ─────────────────────────
            desc_x, desc_y = 0, h - 28 - 62
            desc_w, desc_h = w, 62
            desc_rect = QRectF(desc_x, desc_y, desc_w, desc_h)
            desc_grad = QLinearGradient(0, desc_y, 0, desc_y + desc_h)
            desc_grad.setColorAt(0.0, QColor(PICKER_DESC_TOP))
            desc_grad.setColorAt(1.0, QColor(PICKER_DESC_BOT))
            painter.setPen(Qt.NoPen)
            painter.setBrush(desc_grad)
            painter.drawRect(desc_rect)

            # 4px top + bottom borders
            painter.setPen(QPen(QColor(PICKER_DESC_BORDER), 4))
            painter.drawLine(int(desc_x), int(desc_y), int(desc_x + desc_w), int(desc_y))
            painter.drawLine(int(desc_x), int(desc_y + desc_h),
                              int(desc_x + desc_w), int(desc_y + desc_h))

            # Channel description text (26px, centered)
            desc_font = QFont(UI_FONT)
            desc_font.setPixelSize(26)
            painter.setFont(desc_font)
            desc_text = sel_ch.desc if sel_ch.desc else f"{sel_ch.name} — drop a <video>.txt alongside your videos to show a description here."
            painter.setPen(QColor(0, 0, 0, 140))
            painter.drawText(QRectF(desc_x + 2, desc_y + 12 + 2, desc_w, 30),
                              Qt.AlignCenter, desc_text)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QRectF(desc_x, desc_y + 12, desc_w, 30),
                              Qt.AlignCenter, desc_text)
        finally:
            painter.end()

    # ── Input ─────────────────────────────────────────────────────────────

    def handle_input(self, action: str):
        channels = self.main.catalog.channels
        if not channels:
            if action in ("back", "enter"):
                self.main.show_live()
            return

        if action == "left":
            self.selected_idx = (self.selected_idx - 1) % len(channels)
            self.update()
        elif action == "right":
            self.selected_idx = (self.selected_idx + 1) % len(channels)
            self.update()
        elif action == "enter":
            ch = channels[self.selected_idx]
            self.main.tune_to_channel(ch.number)
            self.main.show_live()
        elif action == "back":
            self.main.show_live()
