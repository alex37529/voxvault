from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6 import QtCore, QtWidgets

from dictophone import models
from dictophone.qt_workers import ModelDownloadTask


class ModelDownloadDialog(QtWidgets.QDialog):
    def __init__(self, tr: Callable[..., str], lang: str, size: Optional[str],
                 model_dir: Path, parent=None):
        super().__init__(parent)
        self._t = tr
        self._model_dir = model_dir
        self._stop: Optional[threading.Event] = None
        self._task: Optional[ModelDownloadTask] = None
        self.setWindowTitle(self._t("models.required_title"))
        self.setMinimumWidth(520)

        root = QtWidgets.QVBoxLayout(self)
        self.message = QtWidgets.QLabel(self._t("models.select_model_text"))
        self.message.setWordWrap(True)
        root.addWidget(self.message)

        form = QtWidgets.QFormLayout()
        self.lang_box = QtWidgets.QComboBox()
        for code in models.known_langs():
            label = self._t(f"lang.{code}")
            if label == f"lang.{code}":
                label = code
            self.lang_box.addItem(label, code)
        lang_index = self.lang_box.findData(lang)
        self.lang_box.setCurrentIndex(lang_index if lang_index >= 0 else 0)
        form.addRow(self._t("label.lang"), self.lang_box)

        self.size_box = QtWidgets.QComboBox()
        form.addRow(self._t("label.model_size"), self.size_box)
        root.addLayout(form)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)

        buttons = QtWidgets.QHBoxLayout()
        self.download_btn = QtWidgets.QPushButton(self._t("models.download_selected"))
        self.download_btn.clicked.connect(self._start_download)
        self.later_btn = QtWidgets.QPushButton(self._t("models.later"))
        self.later_btn.clicked.connect(self.reject)
        self.cancel_btn = QtWidgets.QPushButton(self._t("models.cancel"))
        self.cancel_btn.clicked.connect(self._cancel_download)
        self.cancel_btn.hide()
        buttons.addWidget(self.download_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.later_btn)
        root.addLayout(buttons)

        self.lang_box.currentIndexChanged.connect(self._fill_sizes)
        self.size_box.currentIndexChanged.connect(self._update_selection)
        self._fill_sizes(size)
        self._update_selection()

    def _fill_sizes(self, preferred: Optional[str] = None) -> None:
        self.size_box.blockSignals(True)
        self.size_box.clear()
        lang = self.lang_box.currentData()
        available = [s for s in ("small", "large")
                     if models.MODELS.get(lang, {}).get(s)]
        for value in available:
            self.size_box.addItem(self._t(f"size.{value}"), value)
        index = self.size_box.findData(preferred)
        self.size_box.setCurrentIndex(index if index >= 0 else 0)
        self.size_box.blockSignals(False)
        self._update_selection()

    def _update_selection(self, *_args) -> None:
        self._lang = self.lang_box.currentData()
        self._size = self.size_box.currentData()
        if self._lang and self._size:
            self.download_btn.setEnabled(True)
        else:
            self.download_btn.setEnabled(False)

    @property
    def selected_language(self) -> Optional[str]:
        return self._lang

    @property
    def selected_size(self) -> Optional[str]:
        return self._size

    def _start_download(self) -> None:
        if not self._lang or not self._size or self._task is not None:
            return
        self._stop = threading.Event()
        self._set_downloading(True)
        task = ModelDownloadTask(
            self._model_dir, self._lang, self._size, self._stop
        )
        task.signals.progress.connect(self._on_progress)
        task.signals.done.connect(self._on_done)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self._task = task
        QtCore.QThreadPool.globalInstance().start(task)

    def _set_downloading(self, active: bool) -> None:
        self.lang_box.setEnabled(not active)
        self.size_box.setEnabled(not active)
        self.download_btn.setEnabled(not active and bool(self._lang and self._size))
        self.later_btn.setEnabled(not active)
        self.cancel_btn.setVisible(active)
        self.progress.setVisible(active)
        if active:
            self.progress.setValue(0)
            self.status.setText(self._t("models.required_starting"))

    def _cancel_download(self) -> None:
        if self._stop is not None:
            self._stop.set()

    def _on_progress(self, done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        self.progress.setValue(percent)
        self.status.setText(self._t(
            "models.downloading", lang=self._lang, size=self._size or "-", pct=percent
        ))

    def _on_done(self, lang: str) -> None:
        self._task = None
        self._stop = None
        self._set_downloading(False)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self._task = None
        self._stop = None
        self._set_downloading(False)
        self.status.setText(self._t("models.required_failed", error=message))
        print(f"Не удалось скачать модель: {message}", flush=True)

    def _on_cancelled(self) -> None:
        self._task = None
        self._stop = None
        self._set_downloading(False)
        self.reject()

    def closeEvent(self, event) -> None:
        if self._task is not None:
            self.status.setText(self._t("models.close_while_downloading"))
            event.ignore()
            return
        super().closeEvent(event)
