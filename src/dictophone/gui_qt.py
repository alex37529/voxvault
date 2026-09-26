"""Главное окно приложения на PySide6 (Qt).

Точка входа GUI: main(). Остальное вынесено:
  - qt_workers.py  — фоновые задачи (модель, микрофон, сеть)
  - qt_settings.py — диалог настроек
  - qt_language.py — выбор языка при первом запуске
  - transcript.py  — живая расшифровка (общая с tkinter)"""
from __future__ import annotations

import html
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QTimer

from dictophone import config as config_mod
from dictophone import devices as devices_mod
from dictophone import models, storage, transcribe
from dictophone import qt_workers
from dictophone.app_icon import qicon, set_app_user_model_id
from dictophone.console import setup_console
from dictophone.i18n import I18n, detect_system_lang, lang_name
from dictophone.qt_history import HistoryDialog
from dictophone.qt_language import run_first_run_language
from dictophone.qt_model_dialog import ModelDownloadDialog
from dictophone.qt_settings import SettingsDialog
from dictophone.single_instance import SingleInstance
from dictophone.transcript import TranscriptBuffer

LoadTask = qt_workers.LoadTask
MicTask = qt_workers.MicTask
ModelDownloadTask = qt_workers.ModelDownloadTask

AUTHOR_LINKEDIN = "https://www.linkedin.com/in/alyaksandr-makeenak-49339396/"


def _about_html(text: str, link_label: str) -> str:
    """Перевести текст «О программе» в HTML и вписать ссылку LinkedIn.

    Переводы в `locales/*.json` остаются обычным текстом (их правят
    переводчики, а не программисты), поэтому разметку собираем здесь:
    `•` превращается в настоящий список, переводы строк — в `<br>`.
    Ссылка на автора — часть текста, а не отдельная кнопка под ним.
    """
    out: list[str] = []
    in_list = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("•"):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line.lstrip('•').strip())}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"{html.escape(line)}<br>" if line else "<br>")
    if in_list:
        out.append("</ul>")
    label = html.escape(link_label)
    out.append(f'<a href="{AUTHOR_LINKEDIN}">{label}</a>')
    return "".join(out)


# ---------------------------------------------------------------------------

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, cfg: Optional[config_mod.Config] = None):
        super().__init__()
        self.cfg = cfg if cfg is not None else config_mod.load_config()
        self.tr_ = I18n(self.cfg.ui_lang_or_none() or detect_system_lang())
        self.transcript = TranscriptBuffer()
        self.stop_event: Optional[threading.Event] = None
        self.pause_event: Optional[threading.Event] = None
        self._recording_paused = False
        self._recording_active = False
        self._text_dirty = False
        self._status_key: Optional[str] = None
        self._status_kw: dict = {}
        self._model = None
        self._model_lang: Optional[str] = None
        self._warm_task: Optional[LoadTask] = None
        self._warm_name = ""
        self._warm_key = ""
        self._warm_token = 0            # отсекает результаты отменённых задач
        self._pending_after_load = None  # что сделать, когда модель готова
        self._warm_failed = False
        self._closing = False          # окно закрывается — фоновые задачи стоп
        self._ui_ready = False         # интерфейс ещё собирается
        self._mic_task: Optional[MicTask] = None
        self._history_dialog: Optional[HistoryDialog] = None

        self.setMinimumSize(660, 520)
        self.setWindowIcon(qicon())
        self._build_ui()
        self._ui_ready = True
        self._retranslate()
        self._set_status("app.ready")
        self._show_hint()
        # Предогрев: модель грузится в фоне, чтобы «Запись» начиналась сразу
        self._warm_started = time.time()
        QTimer.singleShot(300, self.start_warmup)

    # -- построение --------------------------------------------------------
    def t(self, key: str, /, **kw) -> str:
        return self.tr_.t(key, **kw)

    def _build_ui(self) -> None:
        # меню
        m_file = self.menuBar().addMenu("")
        self.act_open = m_file.addAction("")
        self.act_open.triggered.connect(self._pick_file)
        self.act_history = m_file.addAction("")
        self.act_history.triggered.connect(self._open_history)
        self.act_copy = m_file.addAction("")
        self.act_copy.triggered.connect(self._copy)
        self.act_exit = m_file.addAction("")
        self.act_exit.triggered.connect(self.close)

        m_set = self.menuBar().addMenu("")
        self.act_prefs = m_set.addAction("")
        self.act_prefs.setShortcut("Ctrl+,")
        self.act_prefs.triggered.connect(self._open_settings)
        self.act_out_dir = m_set.addAction("")
        self.act_out_dir.triggered.connect(self._open_out_dir)

        m_help = self.menuBar().addMenu("")
        self.act_about = m_help.addAction("")
        self.act_about.triggered.connect(self._about)
        self.act_copy.setShortcut("Ctrl+C")

        # центральная часть
        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)

        # панель параметров
        top = QtWidgets.QGridLayout()
        self.lbl_lang = QtWidgets.QLabel()
        self.lang_box = QtWidgets.QComboBox()
        self.lang_box.setMinimumWidth(140)
        model_dir = (
            Path(self.cfg.model_dir) if self.cfg.model_dir else models.DEFAULT_MODEL_DIR
        )
        installed = models.installed_langs(model_dir)
        for code in (installed or models.known_langs()):
            self.lang_box.addItem(code, code)
        i = self.lang_box.findData(self.cfg.lang)
        if i >= 0:
            self.lang_box.setCurrentIndex(i)

        self.lbl_size = QtWidgets.QLabel()
        self.size_box = QtWidgets.QComboBox()
        for key in ("auto", "small", "large"):
            self.size_box.addItem("", key)
        self.size_box.setCurrentIndex(self.size_box.findData(self.cfg.size))

        self.lbl_device = QtWidgets.QLabel()
        self.device_box = QtWidgets.QComboBox()
        self.device_box.setMinimumWidth(240)
        self._fill_devices()

        top.addWidget(self.lbl_lang, 0, 0)
        top.addWidget(self.lang_box, 0, 1)
        top.addWidget(self.lbl_size, 0, 2)
        top.addWidget(self.size_box, 0, 3)
        top.addWidget(self.lbl_device, 1, 0)
        top.addWidget(self.device_box, 1, 1, 1, 3)
        lay.addLayout(top)

        # смена языка/размера перепрогревает нужную модель
        self.lang_box.currentIndexChanged.connect(self._on_selection_changed)
        self.size_box.currentIndexChanged.connect(self._on_selection_changed)

        # индикатор загрузки
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)      # неопределённый: VOSK не отдаёт процент
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.hide()
        lay.addWidget(self.progress)

        # кнопки
        row = QtWidgets.QHBoxLayout()
        self.btn_record = QtWidgets.QToolButton()
        self.btn_record.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.btn_record.setIconSize(QtCore.QSize(22, 22))
        self.btn_record.clicked.connect(self._start_mic)
        self.btn_pause = QtWidgets.QToolButton()
        self.btn_pause.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.btn_pause.setIconSize(QtCore.QSize(22, 22))
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop = QtWidgets.QToolButton()
        self.btn_stop.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.btn_stop.setIconSize(QtCore.QSize(22, 22))
        self.btn_stop.clicked.connect(self._stop)
        self.btn_stop.setEnabled(False)
        self.btn_file = QtWidgets.QPushButton()
        self.btn_file.clicked.connect(self._pick_file)
        self.btn_copy = QtWidgets.QPushButton()
        self.btn_copy.clicked.connect(self._copy)
        for b in (self.btn_record, self.btn_pause, self.btn_stop,
                  self.btn_file, self.btn_copy):
            row.addWidget(b)
        row.addStretch(1)
        self.elapsed = QtWidgets.QLabel()
        self.elapsed.setStyleSheet("color: palette(mid);")
        row.addWidget(self.elapsed)
        lay.addLayout(row)

        # текст
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText(self.t("app.empty_hint"))
        f = self.text.font()
        f.setPointSize(11)
        self.text.setFont(f)
        lay.addWidget(self.text, 1)

        self.status = QtWidgets.QLabel()
        lay.addWidget(self.status)

        self.setCentralWidget(central)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: palette(window); }
            QPushButton { padding: 6px 14px; }
            QPushButton:disabled { color: palette(disabled-text); }
            QPlainTextEdit {
                border: 1px solid palette(mid);
                border-radius: 4px;
                padding: 6px;
                background: palette(base);
            }
            QProgressBar {
                border: none; background: palette(mid); border-radius: 3px;
            }
            QProgressBar::chunk { background: #2f6fb5; border-radius: 3px; }
            """
        )

    def _fill_devices(self) -> None:
        self.device_box.clear()
        self._device_specs = [None]
        self.device_box.addItem("", None)
        try:
            for d in devices_mod.list_input_devices():
                mark = " ★" if d["is_default"] else ""
                self.device_box.addItem(
                    f"{d['index']}: {d['name']}{mark}", str(d["index"])
                )
                self._device_specs.append(str(d["index"]))
        except devices_mod.DeviceError:
            pass
        if self.cfg.device:
            idx = self.device_box.findData(str(self.cfg.device))
            if idx >= 0:
                self.device_box.setCurrentIndex(idx)

    def _record_icon(self) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(28, 28)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor("#c62828"))
        pen.setWidthF(2.0)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawRoundedRect(9, 3, 10, 15, 4, 4)
        painter.drawArc(4, 10, 20, 16, 0, -180 * 16)
        painter.drawLine(14, 25, 14, 27)
        painter.drawLine(9, 27, 19, 27)
        painter.end()
        return QtGui.QIcon(pixmap)

    @staticmethod
    def _pause_icon(style: QtWidgets.QStyle, paused: bool) -> QtGui.QIcon:
        pixmap = style.standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_MediaPlay if paused
            else QtWidgets.QStyle.StandardPixmap.SP_MediaPause
        )
        return pixmap

    def _update_pause_button(self) -> None:
        key = "btn.resume" if self._recording_paused else "btn.pause"
        tooltip = "btn.resume_tooltip" if self._recording_paused else "btn.pause_tooltip"
        self.btn_pause.setText(self.t(key))
        self.btn_pause.setToolTip(self.t(tooltip))
        self.btn_pause.setAccessibleName(self.t(tooltip))
        self.btn_pause.setIcon(self._pause_icon(self.style(), self._recording_paused))

    # -- локализация -------------------------------------------------------
    def _retranslate(self) -> None:
        self.setWindowTitle(self.t("app.title"))
        menus = self.menuBar().actions()
        self.menuBar().setNativeMenuBar(False)
        for action, key in zip(menus, ("menu.file", "menu.settings", "menu.help")):
            action.setText(self.t(key))
        self.act_open.setText(self.t("menu.open_file"))
        self.act_history.setText(self.t("menu.history"))
        self.act_copy.setText(self.t("menu.copy"))
        self.act_exit.setText(self.t("menu.exit"))
        self.act_prefs.setText(self.t("menu.preferences"))
        self.act_out_dir.setText(self.t("menu.open_output"))
        self.act_about.setText(self.t("menu.about"))

        self.lbl_lang.setText(self.t("label.lang"))
        self.lbl_size.setText(self.t("label.model_size"))
        self.lbl_device.setText(self.t("label.microphone"))
        for idx, key in enumerate(("size.auto", "size.small", "size.large")):
            self.size_box.setItemText(idx, self.t(key))
        self.device_box.setItemText(0, self.t("label.default_device"))

        self.btn_record.setText(self.t("btn.record"))
        self.btn_record.setToolTip(self.t("btn.record_tooltip"))
        self.btn_record.setAccessibleName(self.t("btn.record_tooltip"))
        self.btn_record.setIcon(self._record_icon())
        self.btn_file.setText(self.t("btn.file"))
        self._update_pause_button()
        self.btn_stop.setText(self.t("btn.stop"))
        self.btn_stop.setToolTip(self.t("btn.stop_tooltip"))
        self.btn_stop.setAccessibleName(self.t("btn.stop_tooltip"))
        self.btn_stop.setIcon(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_MediaStop
        ))
        self.btn_copy.setText(self.t("btn.copy"))
        self.text.setPlaceholderText(self.t("app.empty_hint"))
        self.elapsed.setText(self.t("status.model_tip"))
        if self._status_key is not None:
            self.status.setText(self.t(self._status_key, **self._status_kw))

    # -- статус и текст ----------------------------------------------------
    def _set_status(self, key: str, **kw) -> None:
        self._status_key = key
        self._status_kw = dict(kw)
        self.status.setText(self.t(key, **kw))

    def _show_hint(self) -> None:
        self._text_dirty = False
        self.text.setPlainText("")

    def _render(self) -> None:
        """Показать текст по состоянию буфера; незакрытый сегмент — серым."""
        body, tail_is_partial = self.transcript.render()
        self.text.setPlainText(body)
        if tail_is_partial and body:
            tail = body.split("\n")[-1]
            cursor = self.text.textCursor()
            for _ in range(len(tail)):
                cursor.movePosition(QtGui.QTextCursor.MoveOperation.PreviousCharacter)
            cursor.select(QtGui.QTextCursor.SelectionType.WordUnderCursor)
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(QtGui.QColor("#888888"))
            cursor.mergeCharFormat(fmt)
            self.text.setTextCursor(cursor)
        self.text.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    # -- загрузка модели ---------------------------------------------------
    def _selected_size(self) -> Optional[str]:
        s = self.size_box.currentData()
        return None if s == "auto" else s

    def _selected_device(self) -> Optional[int]:
        spec = self.device_box.currentData()
        if spec is None:
            return None
        try:
            return devices_mod.resolve_device(str(spec))
        except devices_mod.DeviceError:
            return None

    def _ensure_model(self, then) -> None:
        """Загрузить модель (с индикатором) и вызвать then(model).

        Идём через _start_load: если эта модель уже грузится прогревом —
        просто ждём её, а не запускаем вторую копию.
        """
        lang = self.lang_box.currentData() or self.cfg.lang
        size = self._selected_size()
        key = f"{lang}/{size or 'auto'}"
        if self._model is not None and self._model_lang == key:
            then(self._model)
            return
        if self._warm_task is not None and self._warm_key == key:
            # Прогрев уже идёт — показываем прогресс и продолжим по готовности.
            self._pending_after_load = then
            self._set_busy(True)
            self.progress.show()
            self.elapsed.setText(self.t("status.checking"))
            return
        if not self._model_installed(lang, size):
            # Модель не скачана: сначала предложение её скачать, и только
            # потом загрузка. Раньше пользователь получал ошибку
            # «Запустите: py main.py download ...» — в окне это ничего
            # не объясняло и оставляло без модели.
            self._offer_model_download(lang, size, lambda: self._ensure_model(then))
            return
        self._set_busy(True)
        self.progress.show()
        self.elapsed.setText(self.t("status.checking"))
        self._start_load(lang, size, then=then)

    # -- нескачанная модель ------------------------------------------------
    def _model_installed(self, lang: str, size: Optional[str]) -> bool:
        """Есть ли в каталоге моделей то, что выбрано в списках."""
        return models.find_model(self._model_dir(), lang, size) is not None

    def _ask_download_model(self, lang: str, size: Optional[str]) -> bool:
        """Диалог «модель не скачана, скачать сейчас?». True — скачивать."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle(self.t("model.missing_title"))
        box.setText(self.t(
            "models.required_text",
            lang=lang_name(self.t, lang),
            size=self.t(f"size.{size}") if size else self.t("size.auto"),
        ))
        download = box.addButton(
            self.t("models.download"),
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(
            self.t("models.later"), QtWidgets.QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(download)
        box.exec()
        return box.clickedButton() is download

    def _offer_model_download(
        self, lang: str, size: Optional[str], on_ready
    ) -> bool:
        """Спросить про выбранную модель и, если её скачали, продолжить.

        on_ready() вызывается после успешной установки — вызывающий перезапускает
        свой путь (загрузка модели / запись). True — работа продолжена.
        """
        if self._closing or self._recording_active or self._ui_ready is False:
            return False
        if not self._ask_download_model(lang, size):
            self._set_warm_status("status.warm_missing", name=self._model_display_name())
            return False
        dlg = ModelDownloadDialog(
            self.t, lang, size or "small", self._model_dir(), self
        )
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            self._set_warm_status("status.warm_missing", name=self._model_display_name())
            return False
        self._apply_model_choice(dlg.selected_language, dlg.selected_size)
        on_ready()
        return True

    def _apply_model_choice(self, lang: Optional[str], size: Optional[str]) -> None:
        """Запомнить скачанную модель: списки и настройки без лишнего перезапуска.

        Сигналы списков глушим: иначе смена языка в диалоге запустила бы вторую
        проверку и повторный вопрос про ту же модель.
        """
        if lang:
            index = self.lang_box.findData(lang)
            if index >= 0:
                self.lang_box.blockSignals(True)
                self.lang_box.setCurrentIndex(index)
                self.lang_box.blockSignals(False)
            self.cfg.lang = lang
        if size:
            index = self.size_box.findData(size)
            if index >= 0:
                self.size_box.blockSignals(True)
                self.size_box.setCurrentIndex(index)
                self.size_box.blockSignals(False)
            self.cfg.size = size
        self._save_cfg_quietly()

    def _model_display_name(self) -> str:
        lang = self.lang_box.currentData() or self.cfg.lang
        size = self._selected_size() or "large"
        return f"{lang}/{size}"

    def _set_busy(self, busy: bool) -> None:
        for b in (self.btn_record, self.btn_file, self.btn_copy):
            b.setEnabled(not busy)

    # -- предогрев модели --------------------------------------------------
    def _model_dir(self) -> Path:
        return Path(self.cfg.model_dir) if self.cfg.model_dir else models.DEFAULT_MODEL_DIR

    def _current_model_key(self) -> str:
        lang = self.lang_box.currentData() or self.cfg.lang
        return f"{lang}/{self._selected_size() or 'auto'}"

    def start_warmup(self) -> None:
        """Прогреть модель в фоне: к моменту «Запись» она уже в памяти.

        Не блокирует интерфейс. Ошибки не показываем popup'ом — пишем
        в статус и в консоль.
        """
        if self._closing or self._ui_ready is False:
            return
        lang = self.lang_box.currentData() or self.cfg.lang
        self._start_load(lang, self._selected_size())

    def _start_load(self, lang: str, size: Optional[str], then=None) -> None:
        """Единая точка загрузки модели. Дубликаты невозможны.

        - уже грузим эту же модель — просто цепляем продолжение;
        - грузим другую — отменяем прежнюю и стартуем новую;
        - токен отсекает запоздалые результаты отменённых задач.
        """
        key = f"{lang}/{size or 'auto'}"
        if self._model is not None and self._model_lang == key:
            if then is not None:
                then(self._model)
            return
        if self._warm_task is not None and self._warm_key == key:
            # ровно эта модель уже грузится — дождёмся её, не дублируя
            self._pending_after_load = then
            return
        if self._warm_task is not None:
            # cancel() есть не у всякой задачи — проверяем наличие.
            cancel = getattr(self._warm_task, "cancel", None)
            if callable(cancel):
                cancel()
            self._warm_task = None
            self._pending_after_load = None

        self._warm_token += 1
        token = self._warm_token
        self._warm_key = key
        self._warm_name = key
        self._pending_after_load = then
        self._warm_failed = False
        print(f"Загружаю модель в фоне: {key} — приложением можно пользоваться.",
              flush=True)
        self._set_warm_status("status.warming_short", name=key)

        task = LoadTask(self._model_dir(), lang, size, auto_download=False)
        task.signals.phase.connect(self._on_warm_phase)
        task.signals.phase.connect(self._on_progress_bar)
        task.signals.ready.connect(
            lambda m, lang=lang, size=size, token=token: self._on_load_ready(
                m, lang, size, token)
        )
        task.signals.failed.connect(
            lambda msg, token=token: self._on_load_failed(msg, token)
        )
        self._warm_task = task
        QtCore.QThreadPool.globalInstance().start(task)

    def _on_warm_phase(self, phase: str, elapsed: float) -> None:
        """Фаза загрузки: обновляем статус и подпись с секундами."""
        if phase == models.PHASE_CHECKING:
            self.elapsed.setText(self.t("status.checking"))
        elif phase == models.PHASE_LOADING:
            name = self._warm_key or self._model_display_name()
            if elapsed < 1:
                self.elapsed.setText(self.t("status.loading_model", name=name))
            else:
                self.elapsed.setText(
                    self.t("status.loading_wait", name=name, sec=int(elapsed))
                )

    def _on_progress_bar(self, phase: str, elapsed: float) -> None:
        """Прогрессбар нужен, когда загрузка инициирована из «Запись»/файла."""
        if phase == models.PHASE_LOADING:
            self.progress.show()
            self._set_busy(True)
        elif phase == models.PHASE_READY:
            self.progress.hide()
            self._set_busy(False)
            self.elapsed.setText("")

    def _on_load_ready(self, model, lang: str, size, token: int) -> None:
        """Модель готова. token защищает от запоздалых результатов отменённых."""
        if token != self._warm_token:
            return                       # устаревшая задача — игнор
        self._model = model
        self._model_lang = f"{lang}/{size or 'auto'}"
        self._warm_task = None
        took = getattr(self, "_warm_started", None)
        if took:
            elapsed = time.time() - took
            self.cfg.model_load_time = round(elapsed, 1)
            self._save_cfg_quietly()
            self._set_warm_status("status.warm_usually", sec=int(elapsed))
            print(f"Модель {self._warm_key} готова за {elapsed:.0f} с — "
                  "запись начнётся сразу.", flush=True)
        else:
            self._set_warm_status("status.warm_ready", name=self._warm_key)
            print(f"Модель {self._warm_key} готова.", flush=True)
        then, self._pending_after_load = self._pending_after_load, None
        if then is not None:
            then(model)

    def _on_load_failed(self, message: str, token: int) -> None:
        """Модель не установлена или не читается — пишем и в статус, и в консоль."""
        if token != self._warm_token:
            return
        self._warm_task = None
        self._warm_failed = True
        self._set_warm_status("status.warm_missing", name=self._warm_key)
        print(f"Модель {self._warm_key} не загрузилась: {message}\n"
              "Скачайте её в Настройки → Модели.", flush=True)
        then, self._pending_after_load = self._pending_after_load, None
        if then is not None:
            # Продолжать не с чем: сообщаем вызывающему об ошибке.
            self._on_error(message)

    def _set_warm_status(self, key: str, **kw) -> None:
        # не затираем статус, если идёт активная запись
        if self.stop_event is not None and not self.stop_event.is_set():
            return
        self._set_status(key, **kw)

    def _save_cfg_quietly(self) -> None:
        try:
            config_mod.save_config(self.cfg)
        except OSError:
            pass

    def _history_db(self) -> storage.Storage:
        path = Path(self.cfg.db_path) if self.cfg.db_path else None
        return storage.Storage(path)

    def _save_history(self, entry: storage.Entry) -> None:
        if not self.cfg.history:
            return
        try:
            with self._history_db() as db:
                db.add(entry)
        except Exception as e:  # noqa: BLE001
            print(f"Не удалось сохранить в историю ({self._history_db_path()}): {e}")

    def _history_db_path(self) -> Path:
        return Path(self.cfg.db_path) if self.cfg.db_path else storage.default_db_path()

    def _open_history(self) -> None:
        try:
            db = self._history_db()
            self._history_dialog = HistoryDialog(self.t, db, self)
            self._history_dialog.show()
            self._history_dialog.raise_()
            self._history_dialog.activateWindow()
        except Exception as e:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, self.t("error.title"), self.t("history.open_error", error=str(e))
            )

    def _on_selection_changed(self, *_a) -> None:
        """Смена языка или размера -> перепрогреть нужную модель.

        Старую задачу отменяем СРАЗУ, иначе она догружает модель, которая
        уже не нужна (две загрузки в логе). Новую запускаем с задержкой:
        за это время догрузятся списки и успокоятся повторные сигналы.
        """
        if self._ui_ready is False:
            return                     # интерфейс ещё собирается
        self._model = None
        self._model_lang = None
        self._warm_failed = False
        if self._warm_task is not None:
            cancel = getattr(self._warm_task, "cancel", None)
            if callable(cancel):
                cancel()
            self._warm_task = None
        self._pending_after_load = None
        QTimer.singleShot(400, self._load_selected)

    def _load_selected(self) -> None:
        """Прогреть выбранную модель; если её нет — предложить скачать.

        Модель, которой нет, грузить бессмысленно: load_model вернёт ошибку
        с инструкцией для командной строки. Поэтому сначала проверяем
        каталог моделей и, если модель не установлена, спрашиваем в диалоге.
        """
        lang = self.lang_box.currentData() or self.cfg.lang
        size = self._selected_size()
        if not self._model_installed(lang, size):
            self._offer_model_download(lang, size, self._load_selected)
            return
        self._start_load(lang, size)


    def warmup_state(self) -> str:
        """Состояние загрузки для тестов/статуса: ready|loading|missing|"" """
        if self._model is not None and self._model_lang == self._current_model_key():
            return "ready"
        if self._warm_task is not None:
            return "loading"
        if self._warm_failed:
            return "missing"
        return ""

    # -- микрофон ----------------------------------------------------------
    def _start_mic(self) -> None:
        self.transcript.reset()
        self._text_dirty = False
        self._render()
        self._ensure_model(self._mic_started)

    def _mic_started(self, model) -> None:
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._recording_active = True
        self._recording_paused = False
        self.btn_record.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self._update_pause_button()
        self._set_status("status.listening")
        task = MicTask(model, self._selected_device(), self.stop_event,
                       self.pause_event)
        task.signals.event.connect(self._on_mic_event)
        task.signals.finished.connect(self._on_mic_done)
        task.signals.failed.connect(self._on_error)
        self._mic_task = task
        QtCore.QThreadPool.globalInstance().start(task)

    def _on_mic_event(self, kind: str, text: str) -> None:
        self._text_dirty = True
        if kind == transcribe.FINAL:
            self.transcript.add_final(text)
        else:
            self.transcript.add_partial(text)
        self._render()

    def _on_mic_done(self, capture) -> None:
        from dictophone import postprocess as pp

        raw = " ".join(capture.segments)
        text = pp.apply(raw, capture.segments)
        out_dir = Path(self.cfg.output_dir or models.DEFAULT_OUTPUT_DIR)
        from datetime import datetime
        out = out_dir / f"mic_{datetime.now():%Y%m%d_%H%M%S}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        device = self._selected_device()
        self._save_history(storage.Entry(
            kind="mic", text=text,
            lang=self.lang_box.currentData() or self.cfg.lang,
            model_size=self._selected_size() or "auto",
            device=str(device) if device is not None else None,
            audio_s=capture.audio_s,
            output_path=str(out),
        ))
        self._recording_active = False
        self._text_dirty = False
        self.transcript.set_authoritative(text)
        self._render()
        self.btn_record.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.pause_event = None
        self._recording_paused = False
        self._update_pause_button()
        # статус один: путь сохраняем, итог — в подписи окна
        self.statusBar().showMessage(self.t("status.saved", path=out))
        self._set_status("status.done", chars=len(text))

    def _toggle_pause(self) -> None:
        if self.pause_event is None:
            return
        self._recording_paused = not self._recording_paused
        if self._recording_paused:
            self.pause_event.set()
            self._set_status("status.paused")
        else:
            self.pause_event.clear()
            self._set_status("status.listening")
        self._update_pause_button()

    def _stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
            self._recording_active = False
            self._set_status("status.processing")

    # -- файл, буфер, настройки -------------------------------------------
    def _pick_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, self.t("menu.open_file"), "",
            "Audio (*.wav *.mp3 *.m4a *.ogg *.flac);;All (*)",
        )
        if path:
            self.transcript.reset()
            self._text_dirty = False
            self._render()
            self._ensure_model(lambda m: self._transcribe_file(m, Path(path)))

    def _transcribe_file(self, model, path: Path) -> None:
        self._set_status("status.processing")
        try:
            result = transcribe.transcribe(
                path, lang=self.lang_box.currentData() or self.cfg.lang,
                size=self._selected_size(), output=None,
            )
        except SystemExit as e:
            self._on_error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            self._on_error(f"{type(e).__name__}: {e}")
            return
        out_dir = Path(self.cfg.output_dir or models.DEFAULT_OUTPUT_DIR)
        out = out_dir / f"{path.stem}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.text + "\n", encoding="utf-8")
        self._save_history(storage.Entry(
            kind="file", text=result.text,
            lang=result.lang or self.lang_box.currentData() or self.cfg.lang,
            model_size=self._selected_size() or "auto",
            source=str(path), audio_s=result.audio_s,
            output_path=str(out),
        ))
        self._text_dirty = False
        self.transcript.set_authoritative(result.text)
        self._render()
        self.statusBar().showMessage(self.t("status.saved", path=out))
        self._set_status("status.done", chars=result.chars)

    def _copy(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            self._set_status("status.nothing_to_copy")
            return
        QtWidgets.QApplication.clipboard().setText(text)
        self._set_status("status.copied")

    def _warm_from_settings(self) -> None:
        """Кнопка «Прогреть модель сейчас»: перезагружаем выбранную модель."""
        self._model = None
        self._model_lang = None
        self._warm_failed = False
        self._warm_started = time.time()
        lang = self.lang_box.currentData() or self.cfg.lang
        self._start_load(lang, self._selected_size())

    def _test_microphone(self, device_spec, on_result, on_failed) -> None:
        """Проверить выбранный микрофон: 3 с записи + распознавание (если есть модель)."""
        try:
            device = devices_mod.resolve_device(str(device_spec) if device_spec else None)
        except devices_mod.DeviceError as e:
            on_failed(str(e))
            return
        task = qt_workers.MicTestTask(device, seconds=3.0, model=self._model)
        task.signals.result.connect(on_result)
        task.signals.failed.connect(on_failed)
        QtCore.QThreadPool.globalInstance().start(task)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self.t, self,
                             on_warm=self._warm_from_settings,
                             on_test=self._test_microphone)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        try:
            config_mod.save_config(self.cfg)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, self.t("error.title"), str(e))
        # язык интерфейса мог смениться — переводим окно на лету
        self.tr_ = I18n(self.cfg.ui_lang_or_none() or detect_system_lang())
        self.tr_.preload()
        self._retranslate()
        self._fill_devices()
        self.statusBar().showMessage(self.t("settings.saved"), 4000)

    def _open_out_dir(self) -> None:
        path = Path(self.cfg.output_dir or models.DEFAULT_OUTPUT_DIR)
        path.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path)))

    def _about(self) -> None:
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(self.t("about.title"))
        dlg.setMinimumSize(560, 460)
        lay = QtWidgets.QVBoxLayout(dlg)
        view = QtWidgets.QTextBrowser(dlg)
        view.setOpenExternalLinks(True)
        view.setHtml(_about_html(self.t("about.text"), self.t("about.linkedin")))
        view.setStyleSheet(
            "QTextBrowser { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        lay.addWidget(view)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close, parent=dlg
        )
        close_btn = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close_btn.setText(self.t("btn.close"))
        close_btn.clicked.connect(dlg.accept)
        lay.addWidget(buttons)
        dlg.exec()

    def _on_error(self, message: str) -> None:
        self.progress.hide()
        self._set_busy(False)
        self.btn_record.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._recording_active = False
        self.pause_event = None
        self._recording_paused = False
        self._update_pause_button()
        QtWidgets.QMessageBox.critical(self, self.t("error.title"), message)

    # -- закрытие ----------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._recording_active or self._text_dirty:
            ans = QtWidgets.QMessageBox.question(
                self, self.t("confirm.exit_title"), self.t("confirm.exit_text"),
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if ans != QtWidgets.QMessageBox.StandardButton.Yes:
                event.ignore()
                return          # пользователь остался — флаги не трогаем
        # Закрытие подтверждено: гасим фоновые задачи.
        self._closing = True
        self._recording_active = False
        if self.stop_event is not None:
            self.stop_event.set()
        if self._warm_task is not None:
            cancel = getattr(self._warm_task, "cancel", None)
            if callable(cancel):
                cancel()
            print("Окно закрыто. Фоновая загрузка модели будет прервана "
                  "при выходе из программы.", flush=True)
        event.accept()


def _ensure_required_model(cfg: config_mod.Config, tr) -> None:
    lang = cfg.lang if cfg.lang in models.MODELS else (
        models.known_langs()[0] if models.known_langs() else ""
    )
    if not lang:
        return
    model_dir = Path(cfg.model_dir) if cfg.model_dir else models.DEFAULT_MODEL_DIR
    size = None if cfg.size == "auto" else cfg.size
    if models.find_model(model_dir, lang, size) is not None:
        return
    dialog = ModelDownloadDialog(tr, lang, size, model_dir)
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        if dialog.selected_language:
            cfg.lang = dialog.selected_language
        if dialog.selected_size:
            cfg.size = dialog.selected_size
        try:
            config_mod.save_config(cfg)
        except OSError as e:
            print(f"Не удалось сохранить выбранную модель: {e}", flush=True)


def main(argv: Optional[list[str]] = None) -> int:
    """Запуск окна на PySide6."""
    setup_console()
    # Одна копия приложения: вторая откажется запускаться, чтобы не делить
    # config.json, history.db и каталог моделей с первой.
    guard = SingleInstance()
    if not guard.acquire():
        _show_already_running()
        return 0
    try:
        return _run_gui(argv)
    finally:
        guard.release()


def _show_already_running() -> None:
    tr = I18n(detect_system_lang()).t
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Icon.Information)
    box.setWindowTitle(tr("single.title"))
    box.setText(tr("single.text"))
    box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
    box.exec()


def _run_gui(argv: Optional[list[str]] = None) -> int:
    # Идентификатор приложения для Windows — ДО QApplication и окон: иначе
    # панель задач покажет значок Python (см. app_icon.set_app_user_model_id).
    set_app_user_model_id()
    # QApplication — синглтон: если уже создан (например, тестами), переиспользуем
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QtWidgets.QApplication(argv if argv is not None else sys.argv)
    # Иконка на уровне приложения: её наследуют все окна и диалоги
    # (настройки, история, сообщения об ошибке), а не только главное окно.
    app.setApplicationName("VoxVault")
    app.setApplicationDisplayName("VoxVault")   # подпись в панели задач и Alt-Tab
    app.setOrganizationName("dictophone")
    app.setWindowIcon(qicon())

    # DPI в Qt 6 включён по умолчанию (AA_UseHighDpiPixmaps объявлен
    # устаревшим) — явно ничего задавать не нужно.
    cfg = config_mod.load_config()

    # Первый запуск: один раз показать выбор языка. Иначе приложение откроется
    # на языке Windows, а русскоязычный пользователь об этом не узнает.
    if cfg.first_run:
        run_first_run_language(cfg)

    # Прогреваем все словари заранее — переключение языка будет мгновенным
    warm = I18n(cfg.ui_lang_or_none() or detect_system_lang())
    warm.preload()
    _ensure_required_model(cfg, warm.t)

    win = MainWindow()
    win.resize(760, 620)
    win.show()
    if not owns_app:
        # QApplication уже создана вызывающим (тесты/встраивание):
        # запускать exec() повторно нельзя, просто показываем окно.
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
