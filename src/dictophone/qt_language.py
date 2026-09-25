"""Выбор языка интерфейса при первом запуске (config.first_run).

Показывается один раз. Названия языков в списке — на своём языке, поэтому
выбор понятен независимо от языка, на котором открылся диалог.
"""
from __future__ import annotations

import sys
from typing import Optional

from PySide6 import QtWidgets

from dictophone import config as config_mod
from dictophone.i18n import I18n, available, detect_system_lang


class LanguageDialog(QtWidgets.QDialog):
    """Список конкретных языков. Названия — на собственном языке."""

    def __init__(self, tr, detected: str, parent=None):
        super().__init__(parent)
        self._t = tr
        self.setWindowTitle(tr("dialog.lang_title"))
        self.setMinimumWidth(360)

        lay = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel(tr("dialog.lang_title"))
        font = head.font()
        font.setBold(True)
        font.setPointSize(12)
        head.setFont(font)
        lay.addWidget(head)

        self.list = QtWidgets.QListWidget()
        self.codes: list[str] = []
        for code in available():
            self.list.addItem(tr(f"lang.{code}"))
            self.codes.append(code)
        idx = self.codes.index(detected) if detected in self.codes else 0
        self.list.setCurrentRow(idx)
        lay.addWidget(self.list)

        hint = QtWidgets.QLabel(tr("dialog.lang_hint"))
        hint.setStyleSheet("color: palette(mid);")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText(tr("btn.apply"))
        box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText(
            tr("btn.cancel")
        )
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def selected_code(self) -> Optional[str]:
        """Выбранный код языка."""
        row = self.list.currentRow()
        if row < 0 or row >= len(self.codes):
            return None
        return self.codes[row]


def run_first_run_language(cfg: config_mod.Config) -> None:
    """Показать выбор языка один раз и записать результат в конфиг.

    Отмена диалога сохраняет язык, определённый системой, и тоже гасит
    `first_run`, поэтому диалог не появляется повторно.
    """
    probe = I18n()                       # язык системы — на нём и покажем диалог
    probe.preload()
    probe.set_lang(detect_system_lang())
    dlg = LanguageDialog(probe.t, probe.lang)
    if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        cfg.ui_lang = dlg.selected_code() or probe.lang
    else:
        cfg.ui_lang = probe.lang
    cfg.first_run = False
    try:
        config_mod.save_config(cfg)
    except Exception as e:  # noqa: BLE001
        # Молча проглатывать нельзя: если выбор не сохранился, диалог
        # будет всплывать при каждом запуске, и пользователь не поймёт почему.
        print(
            f"Не удалось сохранить выбор языка ({config_mod.default_config_path()}): {e}",
            file=sys.stderr,
        )
