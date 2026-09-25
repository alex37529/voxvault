"""Диалог настроек: устройство, модели, интерфейс, вывод.

Пишет в общий config.py, поэтому CLI и GUI используют одни и те же настройки.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtWidgets

from dictophone import config as config_mod
from dictophone import models
from dictophone.i18n import available, detect_system_lang
from dictophone.qt_workers import ModelDownloadTask


class SettingsDialog(QtWidgets.QDialog):
    """Настройки приложения. on_warm — колбэк прогрева модели (главное окно)."""

    def __init__(self, cfg: config_mod.Config, tr, parent=None, on_warm=None,
                 on_test=None):
        super().__init__(parent)
        self.cfg = cfg
        self._t = tr
        self._on_warm = on_warm      # колбэк прогрева модели (главное окно)
        self._on_test = on_test      # колбэк проверки микрофона
        self.setWindowTitle(self._t("menu.settings"))
        self.setMinimumSize(560, 460)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self._tab_device(), self._t("tab.device"))
        self.tabs.addTab(self._tab_models(), self._t("tab.models"))
        self.tabs.addTab(self._tab_interface(), self._t("tab.interface"))
        self.tabs.addTab(self._tab_output(), self._t("tab.output"))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self.ok_btn.setText(self._t("btn.apply"))
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText(
            self._t("btn.cancel")
        )
        self.ok_btn.setEnabled(False)      # включается при первом изменении
        buttons.accepted.connect(self._collect_and_accept)
        buttons.rejected.connect(self.reject)

        extra = QtWidgets.QHBoxLayout()
        reset = QtWidgets.QPushButton(self._t("btn.defaults"))
        reset.clicked.connect(self._restore_defaults)
        extra.addWidget(reset)
        extra.addStretch(1)
        extra.addWidget(buttons)
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(self.tabs)
        root.addLayout(extra)

    def _model_dir(self) -> Path:
        return Path(self.cfg.model_dir) if self.cfg.model_dir else models.DEFAULT_MODEL_DIR

    # -- вкладка «Устройство» ---------------------------------------------
    def _tab_device(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)

        self.device_box = QtWidgets.QComboBox()
        self.device_box.setMinimumWidth(340)
        self._device_specs: list[Optional[str]] = [None]
        self._fill_devices()
        form.addRow(self._t("label.microphone"), self.device_box)

        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton(self._t("btn.refresh"))
        refresh.clicked.connect(self._on_refresh_devices)
        self.btn_test = QtWidgets.QPushButton()
        self.btn_test.clicked.connect(self._on_test_clicked)
        row.addWidget(refresh)
        row.addWidget(self.btn_test)
        row.addStretch(1)
        form.addRow("", row)

        self.test_result = QtWidgets.QLabel()
        self.test_result.setWordWrap(True)
        self.test_result.setStyleSheet("color: palette(mid);")
        form.addRow("", self.test_result)

        self.device_box.currentIndexChanged.connect(self._touch)
        self._retranslate_device()
        return page

    def _retranslate_device(self) -> None:
        if hasattr(self, "btn_test"):
            self.btn_test.setText(self._t("btn.test_mic"))

    def _on_test_clicked(self) -> None:
        if self._on_test is not None:
            self._on_test(self.device_box.currentData(), self._on_test_result,
                          self._on_test_failed)

    def _on_test_result(self, text: str) -> None:
        self.btn_test.setEnabled(True)
        self.test_result.setText(text)

    def _on_test_failed(self, message: str) -> None:
        self.btn_test.setEnabled(True)
        self.test_result.setText(self._t("error.title") + ": " + message)

    def _on_refresh_devices(self) -> None:
        self._fill_devices()
        self._touch()

    def _fill_devices(self) -> None:
        from dictophone import devices as devices_mod

        current = self.device_box.currentData()
        self.device_box.blockSignals(True)
        self.device_box.clear()
        self._device_specs = [None]
        self.device_box.addItem(self._t("label.default_device"), None)
        try:
            for d in devices_mod.list_input_devices():
                mark = " ★" if d["is_default"] else ""
                self.device_box.addItem(
                    f"{d['index']}: {d['name']} ({d['channels']} кан.){mark}",
                    str(d["index"]),
                )
                self._device_specs.append(str(d["index"]))
        except devices_mod.DeviceError:
            pass
        self.device_box.blockSignals(False)
        idx = self.device_box.findData(str(self.cfg.device or current))
        if idx >= 0:
            self.device_box.setCurrentIndex(idx)

    # -- вкладка «Модели» --------------------------------------------------
    def _tab_models(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.models_list = QtWidgets.QListWidget()
        self.models_list.setMinimumWidth(210)
        self.models_list.currentRowChanged.connect(self._on_model_picked)
        split.addWidget(self.models_list)

        detail = QtWidgets.QWidget()
        dlay = QtWidgets.QVBoxLayout(detail)
        self.model_info = QtWidgets.QLabel()
        self.model_info.setWordWrap(True)
        dlay.addWidget(self.model_info)
        self.model_warn = QtWidgets.QLabel()
        self.model_warn.setWordWrap(True)
        self.model_warn.setStyleSheet("color: #b26a00;")
        self.model_warn.hide()
        dlay.addWidget(self.model_warn)

        self.btn_dl_small = QtWidgets.QPushButton()
        self.btn_dl_small.clicked.connect(lambda: self._start_download("small"))
        self.btn_dl_large = QtWidgets.QPushButton()
        self.btn_dl_large.clicked.connect(lambda: self._start_download("large"))
        self.btn_dl_cancel = QtWidgets.QPushButton()
        self.btn_dl_cancel.clicked.connect(self._cancel_download)
        self.btn_dl_cancel.hide()
        dlay.addWidget(self.btn_dl_small)
        dlay.addWidget(self.btn_dl_large)
        dlay.addWidget(self.btn_dl_cancel)

        self.btn_del = QtWidgets.QPushButton()
        self.btn_del.clicked.connect(self._delete_model)
        dlay.addWidget(self.btn_del)

        self.btn_warm = QtWidgets.QPushButton()
        self.btn_warm.clicked.connect(self._on_warm_clicked)
        dlay.addWidget(self.btn_warm)
        self.warm_hint_label = QtWidgets.QLabel()
        self.warm_hint_label.setWordWrap(True)
        self.warm_hint_label.setStyleSheet("color: palette(mid);")
        dlay.addWidget(self.warm_hint_label)
        dlay.addStretch(1)

        split.addWidget(detail)
        split.setStretchFactor(1, 1)
        lay.addWidget(split)

        self.dl_progress = QtWidgets.QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.hide()
        lay.addWidget(self.dl_progress)

        self.dl_status = QtWidgets.QLabel()
        self.dl_status.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.dl_status)

        self._download_stop: Optional[threading.Event] = None
        self._download_task: Optional[ModelDownloadTask] = None
        self._fill_models()
        self._retranslate_models()
        return page

    def _retranslate_models(self) -> None:
        """Подписи кнопок вкладки «Модели»."""
        self.btn_dl_small.setText(self._t("models.download") + " (small)")
        self.btn_dl_large.setText(self._t("models.download") + " (large)")
        self.btn_dl_cancel.setText(self._t("models.cancel"))
        self.btn_del.setText(self._t("models.delete"))
        if hasattr(self, "btn_warm"):
            self.btn_warm.setText(self._t("settings.warm_button"))
            self.warm_hint_label.setText(self._t("settings.warm_hint"))

    def _fill_models(self) -> None:
        """Список: сначала установленные, потом доступные к скачиванию."""
        self.models_list.blockSignals(True)
        self.models_list.clear()
        rows = models.list_installed(self._model_dir())
        installed = [r for r in rows if r["path"] is not None]
        missing = [r for r in rows if r["path"] is None]
        for r in installed:
            kinds = [s for s in ("small", "large") if r[s]]
            self.models_list.addItem(
                f"✓ {r['lang']:<7} {'+'.join(kinds):<12} {r['size_mb']:>5} МБ"
            )
        for r in missing:
            avail = [s for s in ("small", "large") if models.MODELS[r["lang"]].get(s)]
            self.models_list.addItem(f"  {r['lang']:<7} {','.join(avail)}")
        self.models_list.blockSignals(False)
        if self.models_list.count():
            self.models_list.setCurrentRow(0)
        self.dl_status.setText(
            self._t("models.free_space", size=models.free_space_mb(self._model_dir()))
        )

    def _current_row_data(self) -> Optional[dict]:
        row = self.models_list.currentRow()
        if row < 0:
            return None
        rows = models.list_installed(self._model_dir())
        ordered = [r for r in rows if r["path"] is not None] + \
                  [r for r in rows if r["path"] is None]
        return ordered[row] if row < len(ordered) else None

    def _on_model_picked(self, *_a) -> None:
        data = self._current_row_data()
        if data is None:
            return
        parts = []
        if data["small"]:
            parts.append(f"{self._t('models.have_small')} "
                         f"({models.dir_size_mb(self._model_dir() / data['small'])} МБ)")
        if data["large"]:
            parts.append(f"{self._t('models.have_large')} ({data['size_mb']} МБ)")
        self.model_info.setText(" · ".join(parts) if parts else self._t("models.have_none"))
        self.btn_dl_small.setEnabled(not data["small"])
        self.btn_dl_large.setEnabled(not data["large"])
        self.btn_del.setEnabled(data["path"] is not None)
        self.model_warn.setText(self._t("models.warn_large"))
        self.model_warn.setVisible(data["large"] is None)

    def _on_warm_clicked(self) -> None:
        if self._on_warm is not None:
            self._on_warm()

    def _set_downloading(self, active: bool) -> None:
        for w in (self.btn_dl_small, self.btn_dl_large, self.btn_del,
                  self.models_list, self.btn_warm):
            w.setEnabled(not active)
        self.btn_dl_cancel.setVisible(active)
        self.dl_progress.setVisible(active)
        if active:
            self.dl_progress.setValue(0)

    def _start_download(self, size: str) -> None:
        data = self._current_row_data()
        if data is None or size not in ("small", "large"):
            return
        lang = data["lang"]
        if models.MODELS[lang].get(size) is None:
            QtWidgets.QMessageBox.information(
                self, self._t("tab.models"),
                f"{lang}: {self._t('models.have_none')} ({size})",
            )
            return
        need_mb = models.archive_size_mb(lang, size) or (1800 if size == "large" else 60)
        free = models.free_space_mb(self._model_dir())
        if free and free < need_mb * 1.2:
            QtWidgets.QMessageBox.warning(
                self, self._t("tab.models"),
                self._t("models.no_space", size=need_mb, free=free),
            )
            return

        self._download_stop = threading.Event()
        self._set_downloading(True)
        task = ModelDownloadTask(self._model_dir(), lang, size, self._download_stop)
        task.signals.progress.connect(self._on_dl_progress)
        task.signals.done.connect(self._on_dl_done)
        task.signals.failed.connect(self._on_dl_failed)
        task.signals.cancelled.connect(self._on_dl_cancelled)
        self._download_task = task
        QtCore.QThreadPool.globalInstance().start(task)

    def _cancel_download(self) -> None:
        if self._download_stop is not None:
            self._download_stop.set()

    def _on_dl_progress(self, done: int, total: int) -> None:
        import time as _time

        pct = int(done * 100 / total) if total else 0
        data = self._current_row_data()
        lang = data["lang"] if data else ""
        size = self._download_task.size if self._download_task else ""
        speed = 0.0
        if total > 0 and self._download_task:
            elapsed = max(_time.time() - self._download_task.started, 0.001)
            speed = done / elapsed / (1024 * 1024)
        self.dl_progress.setValue(pct)
        self.dl_status.setText(
            self._t("models.downloading", lang=lang, size=size, pct=pct)
            + f"  ({done >> 20} / {max(total, 1) >> 20} МБ, {speed:.1f} МБ/с)"
        )

    def _on_dl_done(self, lang: str) -> None:
        self._set_downloading(False)
        self._download_task = None
        self._fill_models()
        self.dl_status.setText(self._t("models.done", lang=lang))

    def _on_dl_failed(self, message: str) -> None:
        self._set_downloading(False)
        self._download_task = None
        self.dl_status.setText("")
        QtWidgets.QMessageBox.warning(self, self._t("tab.models"), message)

    def _on_dl_cancelled(self) -> None:
        self._set_downloading(False)
        self._download_task = None
        self.dl_status.setText(self._t("models.cancelled"))

    def _delete_model(self) -> None:
        data = self._current_row_data()
        if data is None or data["path"] is None:
            return
        ans = QtWidgets.QMessageBox.question(
            self, self._t("tab.models"),
            self._t("models.confirm_delete", lang=data["lang"], size=data["size_mb"]),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if ans != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            freed = models.delete_model(data["path"])
        except (ValueError, OSError) as e:
            QtWidgets.QMessageBox.warning(self, self._t("tab.models"), str(e))
            return
        self._fill_models()
        self.dl_status.setText(self._t("models.deleted", size=freed))

    # -- вкладка «Интерфейс» ----------------------------------------------
    def _tab_interface(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)

        self.ui_lang_box = QtWidgets.QComboBox()
        for code in available():
            self.ui_lang_box.addItem(self._t(f"lang.{code}"), code)
        selected = self.cfg.ui_lang
        if selected == "auto" or selected not in available():
            selected = detect_system_lang()
        idx = self.ui_lang_box.findData(selected)
        self.ui_lang_box.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow(self._t("label.ui_lang"), self.ui_lang_box)
        self.ui_lang_box.currentIndexChanged.connect(self._touch)
        return page

    # -- вкладка «Вывод» ----------------------------------------------------
    def _tab_output(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)

        self.lang_box = QtWidgets.QComboBox()
        self.lang_box.setMinimumWidth(200)
        installed = models.installed_langs(self._model_dir())
        for code in (installed or models.known_langs()):
            self.lang_box.addItem(code, code)
        idx = self.lang_box.findData(self.cfg.lang)
        if idx >= 0:
            self.lang_box.setCurrentIndex(idx)
        lay.addWidget(QtWidgets.QLabel(self._t("label.lang")))
        lay.addWidget(self.lang_box)

        self.size_box = QtWidgets.QComboBox()
        for key in ("auto", "small", "large"):
            self.size_box.addItem(self._t(f"size.{key}"), key)
        self.size_box.setCurrentIndex(self.size_box.findData(self.cfg.size))
        lay.addWidget(QtWidgets.QLabel(self._t("label.model_size")))
        lay.addWidget(self.size_box)

        lay.addWidget(QtWidgets.QLabel(self._t("label.output_dir")))
        out_row = QtWidgets.QHBoxLayout()
        self.out_edit = QtWidgets.QLineEdit(
            self.cfg.output_dir or str(models.DEFAULT_OUTPUT_DIR)
        )
        browse = QtWidgets.QPushButton(self._t("btn.browse"))
        browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(browse)
        lay.addLayout(out_row)

        self.history_check = QtWidgets.QCheckBox(self._t("label.history"))
        self.history_check.setChecked(self.cfg.history)
        lay.addWidget(self.history_check)

        self.out_edit.textChanged.connect(self._touch)
        self.lang_box.currentIndexChanged.connect(self._touch)
        self.size_box.currentIndexChanged.connect(self._touch)
        self.history_check.toggled.connect(self._touch)
        return page

    def _browse_out(self) -> None:
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, self._t("label.output_dir"), self.out_edit.text()
        )
        if chosen:
            self.out_edit.setText(chosen)

    # -- действия ----------------------------------------------------------
    def _touch(self, *_) -> None:
        self.ok_btn.setEnabled(True)

    def _restore_defaults(self) -> None:
        fresh = config_mod.Config()
        self.out_edit.setText(str(models.DEFAULT_OUTPUT_DIR))
        idx = self.lang_box.findData(fresh.lang)
        if idx >= 0:
            self.lang_box.setCurrentIndex(idx)
        self.size_box.setCurrentIndex(self.size_box.findData("auto"))
        self.ui_lang_box.setCurrentIndex(self.ui_lang_box.findData(detect_system_lang()))
        if self.ui_lang_box.currentIndex() < 0:
            self.ui_lang_box.setCurrentIndex(0)
        self.history_check.setChecked(fresh.history)
        self._fill_devices()
        self._fill_models()
        self._touch()

    def _collect_and_accept(self) -> None:
        self.cfg.lang = self.lang_box.currentData() or self.cfg.lang
        size = self.size_box.currentData()
        self.cfg.size = size or "auto"
        self.cfg.output_dir = self.out_edit.text() or None
        self.cfg.device = self.device_box.currentData()
        self.cfg.ui_lang = self.ui_lang_box.currentData() or detect_system_lang()
        self.cfg.history = self.history_check.isChecked()
        self.accept()
