"""Иконка приложения: окно, диалоги, exe.

Иконка рисуется кодом, а не грузится из файла. Причины:

  - в собранном exe `__file__` указывает внутрь `_internal`, и картинка рядом
    с модулем искалась бы по разным путям (см. тот же приём в `i18n.py`);
  - файл пришлось бы дублировать в spec, в dev-режим и в zip-архив;
  - `QIcon` из набора размеров выглядит чётче в заголовке окна, чем один
    растянутый PNG.

Тот же код собирает `packaging/assets/VoxVault.ico` — ресурс exe, который
Windows показывает в проводнике и на панели задач.
"""
from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

from PySide6 import QtCore, QtGui

#: Размеры, которые нужны Qt: от мелких в списках до крупных в проводнике.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

_BRAND_TOP = "#3d7fd6"
_BRAND_BOTTOM = "#1d4f8f"
_GLYPH = "#ffffff"


def _paint(size: int) -> QtGui.QImage:
    """Картинка: скруглённый квадрат с микрофоном.

    Именно `QImage`, а не `QPixmap`: создание `QPixmap` требует живого
    `QGuiApplication` и без окна (генерация .ico из консоли) приводит к
    аварийному завершению процесса.
    """
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    gradient = QtGui.QLinearGradient(
        QtCore.QPointF(0, 0), QtCore.QPointF(0, size)
    )
    gradient.setColorAt(0.0, QtGui.QColor(_BRAND_TOP))
    gradient.setColorAt(1.0, QtGui.QColor(_BRAND_BOTTOM))
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(
        QtCore.QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92),
        size * 0.22, size * 0.22,
    )

    pen = QtGui.QPen(QtGui.QColor(_GLYPH))
    pen.setWidthF(max(size * 0.055, 1.4))
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    cx, cy = size / 2, size / 2
    body_w, body_h = size * 0.26, size * 0.42
    painter.drawRoundedRect(
        QtCore.QRectF(cx - body_w / 2, cy - body_h / 2, body_w, body_h),
        body_w / 2, body_w / 2,
    )
    painter.drawArc(
        QtCore.QRectF(cx - size * 0.30, cy - size * 0.10,
                      size * 0.60, size * 0.60),
        0, 180 * 16,
    )
    painter.drawLine(
        QtCore.QPointF(cx, cy + size * 0.22), QtCore.QPointF(cx, cy + size * 0.32)
    )
    painter.drawLine(
        QtCore.QPointF(cx - size * 0.13, cy + size * 0.32),
        QtCore.QPointF(cx + size * 0.13, cy + size * 0.32),
    )
    painter.end()
    return image


def _render(size: int) -> QtGui.QPixmap:
    """`QPixmap` для окна. Вызывается только при живом QGuiApplication."""
    return QtGui.QPixmap.fromImage(_paint(size))


def _png(size: int) -> bytes:
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    _paint(size).save(buffer, "PNG")
    return bytes(buffer.data())


@lru_cache(maxsize=1)
def qicon() -> QtGui.QIcon:
    """Иконка приложения со всеми размерами (создаётся один раз)."""
    icon = QtGui.QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_render(size))
    return icon


def ico_bytes(sizes: tuple[int, ...] = ICON_SIZES) -> bytes:
    """Собрать ICO из PNG-картинок.

    Qt не умеет писать ICO, а ICO — это просто заголовок, записи на каждое
    изображение и сами данные. Формат с PNG внутри понимают Windows Vista+.
    """
    pngs = {size: _png(size) for size in sizes}
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries, blobs = b"", b""
    for size, data in sorted(pngs.items()):
        # 0 в полях width/height означает 256.
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        blobs += data
        offset += len(data)
    return header + entries + blobs


def write_ico(path: Path, sizes: tuple[int, ...] = ICON_SIZES) -> Path:
    """Записать .ico (используется `packaging/make_icon.py`)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico_bytes(sizes))
    return path
