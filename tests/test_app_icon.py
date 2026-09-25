"""Иконка приложения: рисуется кодом, собирается в ICO (app_icon.py)."""
from __future__ import annotations

import struct

import pytest

pytest.importorskip("PySide6", reason="PySide6 не установлен — GUI-тесты пропущены")

from dictophone import app_icon  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class TestQIcon:
    def test_icon_is_not_empty(self, qapp):
        assert not app_icon.qicon().isNull()

    def test_every_size_renders(self, qapp):
        """Заголовок окна просит 16×16, проводник — 256×256: нужны все."""
        from PySide6 import QtCore

        icon = app_icon.qicon()
        for size in app_icon.ICON_SIZES:
            pixmap = icon.pixmap(QtCore.QSize(size, size))
            assert not pixmap.isNull(), f"нет размера {size}"
            assert pixmap.width() > 0

    def test_icon_is_cached(self, qapp):
        assert app_icon.qicon() is app_icon.qicon(), "иконка строится один раз"


class TestWindowIcon:
    def test_main_window_has_icon(self, qapp):
        """Заголовок окна должен показывать иконку, а не значок Qt по умолчанию."""
        from dictophone import config as config_mod
        from dictophone import gui_qt

        win = gui_qt.MainWindow(config_mod.Config(first_run=False, ui_lang="ru"))
        try:
            assert not win.windowIcon().isNull()
        finally:
            win._model = None
            win.close()


class TestIco:
    def test_ico_header(self):
        data = app_icon.ico_bytes((16, 32, 256))
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        assert reserved == 0
        assert kind == 1, "ожидается иконка (не курсор)"
        assert count == 3

    def test_ico_entries_are_png(self):
        data = app_icon.ico_bytes((16, 48))
        count = struct.unpack("<H", data[4:6])[0]
        for i in range(count):
            entry = struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])
            offset, size = entry[7], entry[6]
            assert data[offset:offset + 4] == b"\x89PNG", "ожидается PNG внутри ICO"

    def test_ico_256_uses_zero_size_field(self):
        """В ICO размер 256 кодируется нулём в байтовых полях."""
        data = app_icon.ico_bytes((256,))
        entry = struct.unpack("<BBBBHHII", data[6:22])
        assert entry[0] == 0 and entry[1] == 0

    def test_write_ico_creates_file(self, tmp_path):
        path = app_icon.write_ico(tmp_path / "sub" / "app.ico", (16, 32))
        assert path.exists()
        assert path.read_bytes()[:4] == b"\x00\x00\x01\x00"

    def test_ico_generation_needs_no_gui(self, tmp_path):
        """`.ico` собирается без окна (make_icon.py запускают из консоли).

        Регрессия: `_render` возвращал QPixmap, а его создание без
        QGuiApplication валит процесс с 0xC0000409.
        """
        import subprocess
        import sys

        code = (
            "import sys; sys.path.insert(0, 'src')\n"
            "from dictophone import app_icon\n"
            "app_icon.write_ico(r'%s', (16, 32))\n"
            "print('ok')\n" % (tmp_path / "gen.ico")
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "gen.ico").exists()
