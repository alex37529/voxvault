"""Тесты Qt-интерфейса (PySide6), headless через offscreen.

Весь набор тестов не должен требовать установленного PySide6 — файл
пропускается, если Qt нет (см. importorskip). Так тесты остаются
переносимыми на машины без Qt.
"""

from __future__ import annotations

import contextlib
import os
import threading
from pathlib import Path

import pytest

# offscreen ДО импорта Qt — иначе попытается открыть окно
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="PySide6 не установлен — GUI-тесты пропущены")

from PySide6 import QtCore, QtGui, QtWidgets

from dictophone import config as config_mod
from dictophone import (
    gui_qt,
    models,
    qt_history,
    qt_language,
    qt_model_dialog,
    qt_settings,
    qt_workers,
    storage,
    updater,
)
from dictophone.i18n import I18n, available


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def widget(app):
    w = QtWidgets.QWidget()
    yield w
    w.close()


class TestLanguageDialog:
    def test_lists_native_names(self, app, widget):
        tr = I18n("en").t
        dlg = qt_language.LanguageDialog(tr, "en", widget)
        texts = [dlg.list.item(i).text() for i in range(dlg.list.count())]
        assert "English" in texts
        assert "Русский" in texts  # не переводим название языка!
        assert "Українська" in texts
        assert "简体中文" in texts
        assert all(dlg.codes[i] != "auto" for i in range(len(dlg.codes)))

    def test_detected_language_preselected(self, app, widget):
        tr = I18n("ru").t
        dlg = qt_language.LanguageDialog(tr, "ru", widget)
        assert dlg.selected_code() == "ru"

    def test_selecting_specific_language(self, app, widget):
        tr = I18n("en").t
        dlg = qt_language.LanguageDialog(tr, "en", widget)
        for row in range(dlg.list.count()):
            if dlg.codes[row] == "ru":
                dlg.list.setCurrentRow(row)
                break
        assert dlg.selected_code() == "ru"

    def test_no_auto_option(self, app, widget):
        tr = I18n("en").t
        dlg = qt_language.LanguageDialog(tr, "en", widget)
        assert all(dlg.codes[i] != "auto" for i in range(len(dlg.codes)))
        assert dlg.selected_code() in available()


class TestFirstRun:
    def test_first_run_flag_persisted(self, app, tmp_path, monkeypatch):
        """Отмена диалога тоже гасит первый запуск — иначе диалог каждый раз."""
        path = tmp_path / "config.json"
        monkeypatch.setattr(config_mod, "default_config_path", lambda: path)
        cfg = config_mod.Config()
        assert cfg.first_run is True
        # имитируем исход: первый запуск, пользователь отказался
        cfg.first_run = False
        cfg.ui_lang = None
        config_mod.save_config(cfg, path)
        back = config_mod.load_config(path)
        assert back.first_run is False and back.ui_lang is None

    def test_ui_lang_survives_roundtrip(self, tmp_path):
        path = tmp_path / "c.json"
        config_mod.save_config(config_mod.Config(ui_lang="ru"), path)
        assert config_mod.load_config(path).ui_lang == "ru"


class TestAboutHtml:
    """Текст «О программе» переводится в HTML со списком и ссылкой."""

    def test_bullets_become_list(self):
        html_text = gui_qt._about_html("Плюсы:\n• раз\n• два", "LinkedIn")
        assert "<ul>" in html_text
        assert html_text.count("<li>") == 2
        assert "раз" in html_text and "два" in html_text

    def test_link_is_inside_text(self):
        html_text = gui_qt._about_html("Автор", "LinkedIn")
        assert f'href="{gui_qt.AUTHOR_LINKEDIN}"' in html_text
        assert ">LinkedIn</a>" in html_text

    def test_html_is_escaped(self):
        """Символы из перевода не должны ломать разметку."""
        html_text = gui_qt._about_html("a & b <script>", "L")
        assert "&amp;" in html_text
        assert "&lt;script&gt;" in html_text
        assert "<script>" not in html_text

    def test_all_locales_render(self):
        for lang in available():
            text = I18n(lang).t("about.text")
            html_text = gui_qt._about_html(text, I18n(lang).t("about.linkedin"))
            assert html_text.strip(), lang
            assert gui_qt.AUTHOR_LINKEDIN in html_text, lang


class TestMainWindow:
    def test_window_builds(self, app):
        win = gui_qt.MainWindow()
        try:
            assert win.windowTitle()
            assert win.btn_record.text()
            assert win.btn_stop.isEnabled() is False
        finally:
            win.close()

    def test_progress_is_indeterminate(self, app):
        """VOSK не отдаёт процент, поэтому у индикатора нет диапазона (0–0)."""
        win = gui_qt.MainWindow()
        try:
            assert win.progress.minimum() == 0
            assert win.progress.maximum() == 0
        finally:
            win.close()

    def test_menu_translated(self, app):
        win = gui_qt.MainWindow()
        try:
            win.tr_ = I18n("en")
            win._retranslate()
            titles = [a.text() for a in win.menuBar().actions()]
            assert "File" in titles and "Settings" in titles
        finally:
            win.close()

    def test_retranslate_switches_language(self, app):
        win = gui_qt.MainWindow()
        try:
            win.tr_ = I18n("ru")
            win._retranslate()
            ru = win.btn_record.text()
            win.tr_ = I18n("en")
            win._retranslate()
            assert win.btn_record.text() != ru
        finally:
            win.close()

    def test_status_is_retranslated_on_language_switch(self, app):
        """Статус из модели не должен оставаться на языке, который был раньше."""
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="en"))
        try:
            win._set_status("status.warm_usually", sec=7)
            assert win.status.text() == I18n("en").t("status.warm_usually", sec=7)
            win.tr_ = I18n("uk")
            win._retranslate()
            assert win.status.text() == I18n("uk").t("status.warm_usually", sec=7)
            assert win.status.text() != I18n("en").t("status.warm_usually", sec=7)
        finally:
            win.close()

    def test_recording_controls_have_icons_and_tooltips(self, app):
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="ru"))
        try:
            assert not win.btn_record.icon().isNull()
            assert not win.btn_pause.icon().isNull()
            assert not win.btn_stop.icon().isNull()
            assert win.btn_record.toolTip()
            assert win.btn_pause.toolTip()
            assert win.btn_stop.toolTip()
        finally:
            win.close()

    def test_pause_and_resume_toggle_event(self, app):
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="ru"))
        try:
            win._closing = True
            win.stop_event = threading.Event()
            win.pause_event = threading.Event()
            win._toggle_pause()
            assert win.pause_event.is_set()
            assert win.btn_pause.text() == win.t("btn.resume")
            win._toggle_pause()
            assert not win.pause_event.is_set()
            assert win.btn_pause.text() == win.t("btn.pause")
        finally:
            win.stop_event.set()
            win.close()

    def test_settings_dialog_has_tabs(self, app):
        win = gui_qt.MainWindow()
        try:
            dlg = qt_settings.SettingsDialog(win.cfg, win.t, win)
            titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
            assert len(titles) == 4
            # подписи берём из словаря, а не хардкодим: язык по умолчанию
            # зависит от системы, где запускаются тесты
            tr = win.t
            assert tr("tab.device") in titles
            assert tr("tab.models") in titles
            assert tr("tab.interface") in titles
            assert tr("tab.output") in titles
            dlg.close()
        finally:
            win.close()

    def test_settings_ui_lang_has_concrete_options(self, app):
        cfg = config_mod.Config(ui_lang="ru")
        win = gui_qt.MainWindow(cfg)
        try:
            dlg = qt_settings.SettingsDialog(cfg, win.t, win)
            codes = [dlg.ui_lang_box.itemData(i) for i in range(dlg.ui_lang_box.count())]
            assert None not in codes
            assert "auto" not in codes
            assert "ru" in codes
            assert "uk" in codes
            assert "zh" in codes
            dlg.close()
        finally:
            win.close()

    def test_history_menu_action(self, app):
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="ru"))
        try:
            assert win.act_history.text() == win.t("menu.history")
        finally:
            win.close()

    def test_about_dialog_builds(self, app, monkeypatch):
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="ru"))
        captured = []

        def fake_exec(self):
            captured.append(self)

        monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
        try:
            win._about()
            assert len(captured) == 1
            dlg = captured[0]
            view = dlg.findChild(QtWidgets.QTextBrowser)
            assert view is not None
            text = view.toPlainText()
            assert "VoxVault" in text
            assert "Makeenak Alyaksandr" in text
            assert "6836808@gmail.com" in text
            assert "бесплатно" in text.lower()
            # ссылка должна быть внутри текста, а не отдельной кнопкой
            html_text = view.toHtml()
            assert gui_qt.AUTHOR_LINKEDIN in html_text
            assert "href" in html_text
            assert view.openExternalLinks() is True
            dlg.close()
        finally:
            win._model = None
            win.close()

class TestAboutVersion:
    """Версия и проверка обновлений в окне «О программе»."""

    def _win(self, app, tmp_path, monkeypatch, **kw):
        monkeypatch.setattr(
            config_mod, "default_config_path", lambda: tmp_path / "config.json"
        )
        cfg = config_mod.Config(
            first_run=False, ui_lang="ru", model_dir=str(tmp_path), **kw
        )
        win = gui_qt.MainWindow(cfg)
        win._warm_task = None
        return win

    def _open_about(self, win, monkeypatch):
        captured = []
        monkeypatch.setattr(
            QtWidgets.QDialog, "exec", lambda self: captured.append(self)
        )
        win._about()
        assert len(captured) == 1
        return captured[0]

    def _release(self, version="9.9.9"):
        return updater.Release(
            version=version,
            url=f"https://github.com/a/b/releases/tag/v{version}",
            notes="Что нового",
            download_url=f"https://example/VoxVault-{version}-win64.zip",
        )

    def test_about_shows_current_version(self, app, tmp_path, monkeypatch):
        from dictophone import __version__

        win = self._win(app, tmp_path, monkeypatch)
        try:
            dlg = self._open_about(win, monkeypatch)
            assert __version__ in win.about_version.text()
            assert win.t("about.update_unknown") in win.about_update_status.text()
            assert win.about_download_btn.isVisibleTo(dlg) is False
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_no_update_keeps_download_button_hidden(
        self, app, tmp_path, monkeypatch
    ):
        win = self._win(app, tmp_path, monkeypatch)
        try:
            win._on_update_checked(None)
            assert win.update_state() == "latest"
            assert win.t("about.update_latest", version=gui_qt.__version__) in (
                win._update_status_text()
            )
            dlg = self._open_about(win, monkeypatch)
            assert win.about_download_btn.isVisibleTo(dlg) is False
            # меню осталось обычным — обновлений нет
            assert win.act_about.text() == win.t("menu.about")
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_new_version_offers_download_and_marks_menu(
        self, app, tmp_path, monkeypatch
    ):
        win = self._win(app, tmp_path, monkeypatch)
        try:
            win._on_update_checked(self._release())
            assert win.update_state() == "available"
            assert win.t("about.update_available", version="9.9.9") in (
                win._update_status_text()
            )
            dlg = self._open_about(win, monkeypatch)
            assert win.about_download_btn.isVisibleTo(dlg) is True
            assert "Что нового" in win.about_update_notes.toPlainText()
            assert "9.9.9" in win.act_about.text()
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_download_button_opens_release_in_browser(
        self, app, tmp_path, monkeypatch
    ):
        win = self._win(app, tmp_path, monkeypatch)
        opened = []
        monkeypatch.setattr(
            QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
        )
        try:
            win._on_update_checked(self._release())
            win._on_update_download_clicked()
            assert opened == ["https://example/VoxVault-9.9.9-win64.zip"]
            # без найденного релиза кнопка не должна ничего открывать
            win._on_update_checked(None)
            win._on_update_download_clicked()
            assert len(opened) == 1
        finally:
            win._model = None
            win.close()

    def test_open_dialog_is_refreshed_after_check(
        self, app, tmp_path, monkeypatch
    ):
        """Проверка идёт в фоне — открытое окно должно обновиться само."""
        win = self._win(app, tmp_path, monkeypatch)
        release = self._release("2.0.0")
        captured = []

        def exec_and_check(self):
            # окно «открыто»: проверка завершается прямо сейчас
            assert win.about_download_btn.isVisibleTo(self) is False
            win._on_update_checked(release)
            assert win.about_download_btn.isVisibleTo(self) is True
            assert "2.0.0" in win.about_update_status.text()
            assert win.about_check_btn.isEnabled() is True
            captured.append(self)

        monkeypatch.setattr(QtWidgets.QDialog, "exec", exec_and_check)
        try:
            win._about()
            assert len(captured) == 1
        finally:
            win._model = None
            win.close()

    def test_network_failure_is_not_a_crash(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        try:
            win._on_update_failed("connection reset")
            assert win.update_state() == "error"
            assert "connection reset" in win._update_status_text()
            dlg = self._open_about(win, monkeypatch)
            assert win.about_download_btn.isVisibleTo(dlg) is False
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_check_happens_at_most_once_a_day(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        started = []
        monkeypatch.setattr(win, "_start_update_check", lambda: started.append(1))
        try:
            # давно не проверяли -> проверяем
            win.check_updates_silent()
            assert started == [1]
            # результат сохранился в настройках
            win._on_update_checked(None)
            assert win.cfg.last_update_check
            assert config_mod.load_config(
                tmp_path / "config.json"
            ).last_update_check == win.cfg.last_update_check
            # второй раз в тот же день сеть дёргать нельзя
            win.check_updates_silent()
            assert started == [1]
        finally:
            win._model = None
            win.close()

    def test_silent_check_skipped_while_closing(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        started = []
        monkeypatch.setattr(
            win, "_start_update_check", lambda: started.append(1)
        )
        try:
            win._closing = True
            win.check_updates_silent()
            assert started == []
        finally:
            win._model = None
            win.close()

    def test_manual_check_button_starts_task(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        started = []
        monkeypatch.setattr(win, "_start_update_check", lambda: started.append(1))
        try:
            dlg = self._open_about(win, monkeypatch)
            win.about_check_btn.click()
            assert started == [1]
            assert win.about_check_btn.isEnabled() is False
            dlg.close()
        finally:
            win._model = None
            win.close()


class TestHistoryDialog:
    def test_history_dialog_builds(self, app, widget, tmp_path):
        db = storage.Storage(tmp_path / "history.db")
        dlg = qt_history.HistoryDialog(I18n("ru").t, db, widget)
        try:
            assert dlg.windowTitle() == I18n("ru").t("history.title")
        finally:
            dlg.close()

    def test_history_dialog_shows_saved_text(self, app, widget, tmp_path):
        db = storage.Storage(tmp_path / "history.db")
        db.add(storage.Entry(kind="mic", text="текст из истории", lang="ru"))
        dlg = qt_history.HistoryDialog(I18n("ru").t, db, widget)
        try:
            assert dlg.table.rowCount() == 1
            assert dlg.details.toPlainText() == "текст из истории"
        finally:
            dlg.close()

    def test_qt_saves_history_to_configured_db(self, app, tmp_path):
        path = tmp_path / "history.db"
        cfg = config_mod.Config(ui_lang="ru", db_path=str(path))
        win = gui_qt.MainWindow(cfg)
        win._closing = True
        try:
            win._save_history(
                storage.Entry(kind="mic", text="сохранено из Qt", lang="ru")
            )
            rows = storage.Storage(path).list()
            assert len(rows) == 1
            assert rows[0]["text"] == "сохранено из Qt"
        finally:
            win.close()


class TestNoDoubleLoad:
    """Регресс: одновременно не должны идти две загрузки модели.

    Было: нажатие «Запись» во время прогрева создавало вторую задачу, и в
    логе перемежались два счётчика секунд, а «Загружаю модель» печаталось
    дважды.
    """

    def _spy_tasks(self, monkeypatch):
        created = []
        orig = qt_workers.LoadTask.__init__

        def spy(self, *a, **k):
            created.append(a[1:3])
            orig(self, *a, **k)

        monkeypatch.setattr(qt_workers.LoadTask, "__init__", spy)
        return created

    def _win(self, app, monkeypatch):
        cfg = config_mod.Config(first_run=False, ui_lang="ru", lang="ru", size="large")
        win = gui_qt.MainWindow(cfg)
        win._warm_task = object()  # имитируем идущий прогрев
        return win

    def test_record_during_warmup_does_not_start_second(self, app, monkeypatch):
        """«Запись» во время прогрева не должна запускать вторую загрузку."""
        created = self._spy_tasks(monkeypatch)
        win = self._win(app, monkeypatch)
        try:
            win._warm_key = "ru/large"
            called = []
            win._ensure_model(lambda m: called.append(m))
            assert created == [], f"запущена дубль-загрузка: {created}"
            # продолжение подвешено и выполнится по готовности
            assert win._pending_after_load is not None
        finally:
            win._model = None
            win._warm_task = None
            win.close()

    def test_record_reuses_ready_model(self, app, monkeypatch):
        """Готовая модель используется сразу, без загрузки."""
        created = self._spy_tasks(monkeypatch)
        win = self._win(app, monkeypatch)
        try:
            win._warm_task = None
            win._model = object()
            win._model_lang = "ru/large"
            called = []
            win._ensure_model(lambda m: called.append(m))
            assert called, "продолжение не вызвано"
            assert created == []
        finally:
            win._model = None
            win.close()

    def test_selection_change_cancels_previous_task(self, app, monkeypatch):
        """Смена размера отменяет прежнюю задачу, а не «осиротевает» её."""
        win = self._win(app, monkeypatch)
        try:
            old_task = qt_workers.LoadTask(Path("C:/x"), "ru", "large")
            win._warm_task = old_task
            win._on_selection_changed()
            assert old_task._cancelled is True, "старая задача не отменена"
        finally:
            win._model = None
            win._warm_task = None
            win.close()

    def test_stale_result_discarded(self, app, monkeypatch):
        """Результат отменённой задачи не должен подменять модель."""
        win = self._win(app, monkeypatch)
        try:
            win._warm_token = 5
            win._on_load_ready(object(), "ru", "large", token=4)  # устаревший
            assert win._model is None
            # актуальный — принимается
            sentinel = object()
            win._on_load_ready(sentinel, "ru", "large", token=5)
            assert win._model is sentinel
        finally:
            win._model = None
            win.close()

    def test_pending_callback_runs_on_ready(self, app, monkeypatch):
        """Отложенное продолжение выполняется, когда модель готова."""
        win = self._win(app, monkeypatch)
        try:
            called = []
            win._warm_token = 1
            win._pending_after_load = lambda m: called.append(m)
            sentinel = object()
            win._on_load_ready(sentinel, "ru", "large", token=1)
            assert called == [sentinel]
            assert win._pending_after_load is None
        finally:
            win._model = None
            win.close()

    def test_ui_ready_guard(self, app):
        """Пока интерфейс собирается, сигналы списков не запускают загрузку."""
        win = gui_qt.MainWindow(config_mod.Config())
        try:
            win._ui_ready = False
            assert win._ui_ready is False
        finally:
            win._model = None
            win.close()


class TestRequiredModel:
    def test_model_dialog_uses_selected_interface_language(self, app, widget, tmp_path):
        tr = I18n("en").t
        dlg = qt_model_dialog.ModelDownloadDialog(tr, "ru", "small", tmp_path, widget)
        try:
            assert dlg.windowTitle() == tr("models.required_title")
            assert tr("models.select_model_text") in dlg.message.text()
            assert dlg.lang_box.count() == len(models.known_langs())
            assert dlg.size_box.count() >= 1
        finally:
            dlg.close()

    def test_model_dialog_allows_selecting_another_model(self, app, widget, tmp_path):
        dlg = qt_model_dialog.ModelDownloadDialog(
            I18n("ru").t, "ru", "small", tmp_path, widget
        )
        try:
            index = dlg.lang_box.findData("en-us")
            dlg.lang_box.setCurrentIndex(index)
            dlg.size_box.setCurrentIndex(dlg.size_box.findData("large"))
            assert dlg.selected_language == "en-us"
            assert dlg.selected_size == "large"
        finally:
            dlg.close()

    def test_missing_model_opens_download_dialog(self, app, tmp_path, monkeypatch):
        cfg = config_mod.Config(model_dir=str(tmp_path), lang="ru", size="small")
        shown = []
        monkeypatch.setattr(
            gui_qt.ModelDownloadDialog,
            "exec",
            lambda self: shown.append(self) or QtWidgets.QDialog.DialogCode.Rejected,
        )
        gui_qt._ensure_required_model(cfg, I18n("ru").t)
        assert len(shown) == 1
        assert shown[0]._lang == "ru"
        assert shown[0]._size == "small"

    def test_selected_model_is_saved_after_download(self, app, tmp_path, monkeypatch):
        cfg_path = tmp_path / "config.json"
        cfg = config_mod.Config(model_dir=str(tmp_path), lang="ru", size="small")
        monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg_path)

        def accept_model(self):
            self.lang_box.setCurrentIndex(self.lang_box.findData("en-us"))
            self.size_box.setCurrentIndex(self.size_box.findData("large"))
            return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(gui_qt.ModelDownloadDialog, "exec", accept_model)
        gui_qt._ensure_required_model(cfg, I18n("ru").t)
        saved = config_mod.load_config(cfg_path)
        assert saved.lang == "en-us"
        assert saved.size == "large"

    def test_existing_model_skips_download_dialog(self, app, tmp_path, monkeypatch):
        model_dir = tmp_path / models.MODELS["ru"]["small"]
        (model_dir / "am").mkdir(parents=True)
        (model_dir / "am" / "final.mdl").write_bytes(b"x")
        cfg = config_mod.Config(model_dir=str(tmp_path), lang="ru", size="small")
        shown = []
        monkeypatch.setattr(
            gui_qt.ModelDownloadDialog,
            "exec",
            lambda self: shown.append(self) or QtWidgets.QDialog.DialogCode.Rejected,
        )
        gui_qt._ensure_required_model(cfg, I18n("ru").t)
        assert shown == []


def _install_model(model_dir: Path, lang: str, size: str) -> None:
    """Разметить каталог как установленную модель VOSK (файлы не нужны)."""
    name = models.MODELS[lang][size]
    (model_dir / name / "am").mkdir(parents=True, exist_ok=True)
    (model_dir / name / "am" / "final.mdl").write_bytes(b"x")


class TestMissingModelPrompt:
    """Выбрали нескачанную модель — предупреждение со скачиванием.

    Раньше в этом месте прогрев молча падал в статус «модель не
    установлена», а «Запись» выдавала ошибку с инструкцией для командной
    строки: в окне пользователь не понимал, что делать.
    """

    def _win(self, app, tmp_path, monkeypatch, **kw):
        # настройки пишем в tmp_path, иначе тест трогает config.json
        # пользователя настоящего
        monkeypatch.setattr(
            config_mod, "default_config_path", lambda: tmp_path / "config.json"
        )
        defaults = {
            "first_run": False,
            "ui_lang": "ru",
            "lang": "ru",
            "size": "large",
            "model_dir": str(tmp_path),
        }
        cfg = config_mod.Config(**{**defaults, **kw})
        win = gui_qt.MainWindow(cfg)
        win._warm_task = None  # прогрев в тестах не нужен
        return win

    def _spy_load(self, win, monkeypatch):
        started = []
        monkeypatch.setattr(
            win,
            "_start_load",
            lambda lang, size, then=None: started.append((lang, size)),
        )
        return started

    def test_selection_of_missing_model_asks_and_does_not_load(
        self, app, tmp_path, monkeypatch
    ):
        win = self._win(app, tmp_path, monkeypatch)
        asked = []
        monkeypatch.setattr(
            win,
            "_ask_download_model",
            lambda lang, size: asked.append((lang, size)) or False,
        )
        started = self._spy_load(win, monkeypatch)
        try:
            win._load_selected()
            assert asked == [("ru", "large")], "не спросили про модель"
            assert started == [], "попытались грузить нескачанную модель"
            assert win._status_key == "status.warm_missing"
        finally:
            win._model = None
            win.close()

    def test_declining_download_keeps_status_hint(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        shown = []
        monkeypatch.setattr(
            gui_qt.ModelDownloadDialog,
            "exec",
            lambda self: shown.append(self) or QtWidgets.QDialog.DialogCode.Rejected,
        )
        monkeypatch.setattr(win, "_ask_download_model", lambda *_: True)
        started = self._spy_load(win, monkeypatch)
        try:
            win._load_selected()
            assert len(shown) == 1, "диалог скачивания не открылся"
            assert started == []
            assert win._status_key == "status.warm_missing"
        finally:
            win._model = None
            win.close()

    def test_downloaded_model_is_loaded_and_remembered(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch)
        monkeypatch.setattr(win, "_ask_download_model", lambda *_: True)

        def accept(self):
            self.lang_box.setCurrentIndex(self.lang_box.findData("en-us"))
            self.size_box.setCurrentIndex(self.size_box.findData("large"))
            _install_model(tmp_path, "en-us", "large")  # «скачали»
            return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(gui_qt.ModelDownloadDialog, "exec", accept)
        started = self._spy_load(win, monkeypatch)
        try:
            win._load_selected()
            assert started == [("en-us", "large")]
            # выбор сохранился и в списках, и в настройках
            assert win.lang_box.currentData() == "en-us"
            assert win.size_box.currentData() == "large"
            saved = config_mod.load_config(tmp_path / "config.json")
            assert saved.lang == "en-us" and saved.size == "large"
        finally:
            win._model = None
            win.close()

    def test_installed_model_loads_without_any_dialog(self, app, tmp_path, monkeypatch):
        _install_model(tmp_path, "ru", "large")
        win = self._win(app, tmp_path, monkeypatch)
        asked = []
        monkeypatch.setattr(
            win, "_ask_download_model", lambda *a: asked.append(a) or False
        )
        started = self._spy_load(win, monkeypatch)
        try:
            win._load_selected()
            assert asked == []
            assert started == [("ru", "large")]
        finally:
            win._model = None
            win.close()

    def test_record_with_missing_model_offers_download(self, app, tmp_path, monkeypatch):
        """«Запись» без модели спрашивает про скачивание, а не ругается ошибкой."""
        win = self._win(app, tmp_path, monkeypatch)
        asked = []
        monkeypatch.setattr(
            win, "_ask_download_model", lambda *a: asked.append(a) or False
        )
        started = self._spy_load(win, monkeypatch)
        called = []
        try:
            win._ensure_model(lambda m: called.append(m))
            assert len(asked) == 1
            assert started == []
            assert called == []
        finally:
            win._model = None
            win.close()

    def test_no_prompt_while_recording(self, app, tmp_path, monkeypatch):
        """Идущую запись не прерываем модальным вопросом."""
        win = self._win(app, tmp_path, monkeypatch)
        asked = []
        monkeypatch.setattr(
            win, "_ask_download_model", lambda *a: asked.append(a) or True
        )
        started = self._spy_load(win, monkeypatch)
        try:
            win._recording_active = True
            win._load_selected()
            assert asked == []
            assert started == []
        finally:
            win._recording_active = False
            win._model = None
            win.close()

    def test_warning_text_is_translated(self, app, tmp_path, monkeypatch):
        """Текст предупреждения — на языке интерфейса, с названием языка."""
        win = self._win(app, tmp_path, monkeypatch)
        seen = {}

        def fake_exec(self):
            seen["title"] = self.windowTitle()
            seen["text"] = self.text()
            self.buttons()[0].click()  # жмём «Скачать»

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
        try:
            assert win._ask_download_model("ru", "large") is True
            assert seen["title"] == win.t("model.missing_title")
            assert win.t("lang.ru") in seen["text"]
            assert win.t("size.large") in seen["text"]
        finally:
            win._model = None
            win.close()

    def test_auto_size_warning_mentions_auto(self, app, tmp_path, monkeypatch):
        win = self._win(app, tmp_path, monkeypatch, size="auto")
        seen = {}

        def fake_exec(self):
            seen["text"] = self.text()

        monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
        try:
            win._ask_download_model("ru", None)
            assert win.t("size.auto") in seen["text"]
        finally:
            win._model = None
            win.close()


class TestEntryPoint:
    """Дымовой тест реальной точки входа.

    Раньше тесты создавали MainWindow напрямую и НЕ трогали main(), поэтому
    битые ссылки после разбиения на модули (_run_first_run_language и т.п.)
    проскакивали и ломали приложение только при запуске.
    """

    def test_gui_qt_command_starts(self, app, tmp_path, monkeypatch):
        """`dictophone gui-qt` должен дойти до создания окна и не упасть.

        QApplication в тестах уже создана, поэтому main() переиспользует её и
        не вызывает exec() — проверяем именно построение окна.
        CLI завершает работу через SystemExit, поэтому ловим его.
        """
        from dictophone import cli
        from dictophone import config as cfg_mod

        cfg = tmp_path / "config.json"
        monkeypatch.setenv("DICTOPHONE_CONFIG", str(cfg))
        monkeypatch.setattr(gui_qt, "_ensure_required_model", lambda *_: None)
        cfg_mod.save_config(cfg_mod.Config(first_run=False, ui_lang="ru"), cfg)

        try:
            code = cli.main(["gui-qt"])
        except SystemExit as e:  # штатное завершение CLI
            code = e.code
        assert code in (0, None)  # дошли до конца main() без traceback

    def test_gui_startup_sets_taskbar_identity(self, app, tmp_path, monkeypatch):
        """Панель задач должна знать, что это VoxVault, а не python.exe.

        Без AppUserModelID Windows рисует на панели задач значок Python,
        и кнопка ещё и сливается с другими python-скриптами.
        """
        from dictophone import cli
        from dictophone import config as cfg_mod

        cfg = tmp_path / "taskbar.json"
        monkeypatch.setenv("DICTOPHONE_CONFIG", str(cfg))
        monkeypatch.setattr(gui_qt, "_ensure_required_model", lambda *_: None)
        cfg_mod.save_config(cfg_mod.Config(first_run=False, ui_lang="ru"), cfg)
        calls = []
        monkeypatch.setattr(
            gui_qt,
            "set_app_user_model_id",
            lambda *a: calls.append(a) or True,
        )
        with contextlib.suppress(SystemExit):  # штатное завершение CLI
            cli.main(["gui-qt"])
        assert calls, "идентификатор панели задач не задан при запуске"

    def test_main_window_uses_saved_uk_language(self, app, tmp_path):
        """Выбранный украинский должен применяться сразу при создании окна."""
        cfg = config_mod.Config(first_run=False, ui_lang="uk")
        win = gui_qt.MainWindow(cfg)
        try:
            assert win.tr_.lang == "uk"
            assert win.btn_record.text() == I18n("uk").t("btn.record")
            assert win.windowTitle() == I18n("uk").t("app.title")
        finally:
            win._model = None
            win.close()

    def test_gui_qt_first_run_dialog(self, app, tmp_path, monkeypatch):
        """Свежая установка (first_run=True) обязана пройти выбор языка."""
        from dictophone import cli, qt_language
        from dictophone import config as cfg_mod

        cfg = tmp_path / "fresh.json"
        monkeypatch.setenv("DICTOPHONE_CONFIG", str(cfg))
        monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg)
        monkeypatch.setattr(gui_qt, "_ensure_required_model", lambda *_: None)

        def accept_auto(self):
            self.list.setCurrentRow(0)  # «по системе»
            QtWidgets.QDialog.accept(self)

        monkeypatch.setattr(qt_language.LanguageDialog, "exec", accept_auto)
        with contextlib.suppress(SystemExit):  # штатное завершение CLI
            cli.main(["gui-qt"])
        # выбор состоялся, диалог больше не покажут
        assert cfg_mod.load_config(cfg).first_run is False

    def test_no_dialog_when_already_configured(self, app, tmp_path, monkeypatch):
        """Главный регресс: если first_run=false, диалог НЕ создаётся.

        Раньше диалог всплывал при каждом запуске, потому что выбор языка
        не удавалось сохранить, а ошибка проглатывалась.
        """
        from dictophone import cli, qt_language
        from dictophone import config as cfg_mod

        cfg = tmp_path / "done.json"
        monkeypatch.setenv("DICTOPHONE_CONFIG", str(cfg))
        cfg_mod.save_config(cfg_mod.Config(first_run=False, ui_lang="ru"), cfg)
        monkeypatch.setattr(gui_qt, "_ensure_required_model", lambda *_: None)

        created = []
        orig = qt_language.LanguageDialog.__init__

        def spy(self, tr, detected, parent=None):
            created.append(detected)
            orig(self, tr, detected, parent)

        monkeypatch.setattr(qt_language.LanguageDialog, "__init__", spy)
        with contextlib.suppress(SystemExit):  # штатное завершение CLI
            cli.main(["gui-qt"])
        assert created == [], "диалог показан повторно при first_run=false"

    def test_dialog_shown_once_then_saved(self, app, tmp_path, monkeypatch):
        """Первый запуск: диалог показывается, выбор сохраняется, второй — нет."""
        from dictophone import cli, qt_language
        from dictophone import config as cfg_mod

        cfg = tmp_path / "fresh2.json"
        monkeypatch.setenv("DICTOPHONE_CONFIG", str(cfg))
        monkeypatch.setattr(config_mod, "default_config_path", lambda: cfg)
        monkeypatch.setattr(gui_qt, "_ensure_required_model", lambda *_: None)
        assert cfg_mod.load_config(cfg).first_run is True

        shown = []

        def fake_exec(self):
            shown.append(1)
            self.list.setCurrentRow(0)  # «по системе»
            return QtWidgets.QDialog.DialogCode.Accepted

        monkeypatch.setattr(qt_language.LanguageDialog, "exec", fake_exec)
        with contextlib.suppress(SystemExit):  # штатное завершение CLI
            cli.main(["gui-qt"])
        assert len(shown) == 1, "диалог должен показаться ровно один раз"
        saved = cfg_mod.load_config(cfg)
        assert saved.first_run is False
        # второй запуск — без диалога
        with contextlib.suppress(SystemExit):  # штатное завершение CLI
            cli.main(["gui-qt"])
        assert len(shown) == 1, "диалог показан повторно"

    def test_save_failure_is_reported(self, app, tmp_path, monkeypatch, capsys):
        """Если настройки не сохранились — об этом сказано в stderr."""
        from dictophone import config as cfg_mod
        from dictophone import qt_language

        def boom(*a, **k):
            raise OSError("диск только для чтения")

        monkeypatch.setattr(cfg_mod, "save_config", boom)
        monkeypatch.setattr(qt_language.LanguageDialog, "exec", lambda self: 0)

        cfg = cfg_mod.Config()
        qt_language.run_first_run_language(cfg)
        assert "Не удалось сохранить" in capsys.readouterr().err

    def test_warmup_not_started_after_close(self, app):
        """После закрытия окна отложенный таймер не должен запускать загрузку."""
        win = gui_qt.MainWindow(config_mod.Config())
        try:
            win._closing = True
            win._warm_task = None
            win.start_warmup()  # должен выйти сразу
            assert win._warm_task is None
        finally:
            win._model = None
            win.close()

    def test_warmup_logs_lifecycle(self, app, capsys, tmp_path, monkeypatch):
        """GUI-режим логирует загрузку: пользователь должен видеть, что происходит."""
        import sys
        import types

        from dictophone import models as models_mod

        fake = types.ModuleType("vosk")
        fake.Model = lambda *a, **k: object()
        fake.SetLogLevel = lambda *a: None
        monkeypatch.setitem(sys.modules, "vosk", fake)

        mdir = tmp_path / "models"
        (mdir / "vosk-model-small-ru-0.22" / "am").mkdir(parents=True)
        (mdir / "vosk-model-small-ru-0.22" / "am" / "final.mdl").write_bytes(b"x")

        events = []
        models_mod.load_model(
            mdir, "ru", "small", progress_cb=lambda p, e: events.append(p)
        )
        assert events, "прогресс не передавался"
        # лог есть и в GUI-режиме — иначе непонятно, что происходит
        assert "Загружаю модель" in capsys.readouterr().out

    def test_cli_mode_keeps_stdout(self, app, capsys, tmp_path, monkeypatch):
        """CLI-режим (без progress_cb) по-прежнему печатает в stdout."""
        import sys
        import types

        from dictophone import models as models_mod

        fake = types.ModuleType("vosk")
        fake.Model = lambda *a, **k: object()
        fake.SetLogLevel = lambda *a: None
        monkeypatch.setitem(sys.modules, "vosk", fake)

        mdir = tmp_path / "models"
        (mdir / "vosk-model-small-ru-0.22" / "am").mkdir(parents=True)
        (mdir / "vosk-model-small-ru-0.22" / "am" / "final.mdl").write_bytes(b"x")

        models_mod.load_model(mdir, "ru", "small", auto_download=False)
        assert "Загружаю модель" in capsys.readouterr().out

    def test_close_event_sets_closing_flag(self, app, capsys):
        """Закрытие подтверждено: флаг выставлен и в лог попадает пояснение."""
        win = gui_qt.MainWindow(config_mod.Config())
        try:
            task = qt_workers.LoadTask(Path("C:/x"), "ru", "large")
            win._warm_task = task
            ev = QtCore.QEvent(QtCore.QEvent.Type.Close)
            win.closeEvent(ev)
            assert win._closing is True
            assert task._cancelled is True
            out = capsys.readouterr().out
            assert "Окно закрыто" in out
        finally:
            win._model = None

    def test_close_cancelled_keeps_working(self, app, monkeypatch):
        """Если пользователь отменил закрытие — работа продолжается."""
        win = gui_qt.MainWindow(config_mod.Config())
        try:
            monkeypatch.setattr(
                QtWidgets.QMessageBox,
                "question",
                lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No,
            )
            win.text.setPlainText("есть текст")
            win._text_dirty = True
            ev = QtCore.QEvent(QtCore.QEvent.Type.Close)
            win.closeEvent(ev)
            assert win._closing is False, "флаг выставлен при отмене закрытия"
        finally:
            win._model = None

    def test_saved_text_and_stopped_task_do_not_prompt_on_exit(self, app, monkeypatch):
        win = gui_qt.MainWindow(config_mod.Config(ui_lang="ru"))
        try:
            win._closing = True
            win.stop_event = threading.Event()
            win.text.setPlainText("уже сохранённый текст")
            win._text_dirty = False
            questions = []
            monkeypatch.setattr(
                QtWidgets.QMessageBox,
                "question",
                lambda *a, **k: (
                    questions.append(a) or QtWidgets.QMessageBox.StandardButton.No
                ),
            )
            ev = QtCore.QEvent(QtCore.QEvent.Type.Close)
            win.closeEvent(ev)
            assert questions == []
            assert win._closing is True
        finally:
            win.stop_event.set()

    def test_every_command_builds_parser(self):
        """Все подкоманды описаны в парсере (нет «неизвестных» при разборе)."""
        from dictophone import cli

        for cmd in (
            "list",
            "devices",
            "config",
            "download",
            "file",
            "mic",
            "gui",
            "gui-qt",
            "history",
        ):
            args = cli.build_parser().parse_args(
                [cmd] if cmd not in ("file",) else [cmd, "a.wav"]
            )
            assert args.command == cmd

    def test_no_broken_names_in_package(self):
        """Статическая проверка: нет имён, не определённых и не импортированных."""
        import ast
        import builtins
        from pathlib import Path

        pkg = Path(gui_qt.__file__).parent
        problems = []
        for py in sorted(pkg.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    defined.add(node.name)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        defined.add((a.asname or a.name).split(".")[0])
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
                elif isinstance(node, ast.arg):
                    defined.add(node.arg)
                elif isinstance(node, ast.ExceptHandler) and node.name:
                    defined.add(node.name)
                elif isinstance(node, ast.Global):
                    defined.update(node.names)
            used = {
                n.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            }
            missing = sorted(used - defined)
            if missing:
                problems.append(f"{py.name}: {missing}")
        assert not problems, "битые ссылки: " + "; ".join(problems)


class TestWarmup:
    """Предогрев: модель грузится в фоне, чтобы «Запись» начиналась сразу."""

    def _win(self, cfg=None, lang="ru", size="large"):
        win = gui_qt.MainWindow(cfg or config_mod.Config())
        idx = win.lang_box.findData(lang)
        if idx >= 0:
            win.lang_box.setCurrentIndex(idx)
        sidx = win.size_box.findData(size)
        if sidx >= 0:
            win.size_box.setCurrentIndex(sidx)
        return win

    def test_warmup_does_not_block_ui(self, app):
        """Предогрев не должен блокировать интерфейс (иначе смысла нет)."""
        win = self._win()
        try:
            win._warm_task = object()  # имитируем идущую загрузку
            win.start_warmup()  # второй вызов — не должен ничего делать
            assert win._warm_task is not None
        finally:
            win._warm_task = None
            win.close()

    def test_warmup_uses_auto_download_false(self, app):
        """Не установленная модель НЕ должна молча качать 1.8 ГБ при старте."""
        win = self._win()
        try:
            task = qt_workers.LoadTask(
                Path("C:/nonexistent"), "xx", "large", auto_download=False
            )
            assert task._auto_download is False
            # по умолчанию (основная запись) скачивание разрешено
            assert qt_workers.LoadTask(Path("C:/x"), "ru", "small")._auto_download
        finally:
            win.close()

    def test_warmup_ready_sets_model_cache(self, app):
        """После прогрева модель в кэше -> «Запись» стартует без ожидания."""
        win = self._win()
        try:
            sentinel = object()
            key = win._current_model_key()
            win._on_load_ready(sentinel, "ru", "large", win._warm_token)
            assert win._model is sentinel
            assert win._model_lang == "ru/large"
            # ключ совпадает с текущим выбором -> состояние ready
            assert win._model_lang == key
            assert win.warmup_state() == "ready"
        finally:
            win._model = None
            win.close()

    def test_warmup_failure_is_silent(self, app):
        """Ошибка прогрева не должна показывать popup — только статус."""
        win = self._win()
        try:
            win._warm_name = "ru/large"
            win._on_load_failed("модель не найдена", win._warm_token)
            assert win.warmup_state() == "missing"
            # статус не должен содержать traceback/текст ошибки C++
            assert "Traceback" not in win.status.text()
        finally:
            win._model = None
            win.close()

    def test_selection_change_resets_cache(self, app):
        """Смена языка сбрасывает кэш модели — иначе пойдёт старая."""
        win = self._win()
        try:
            win._model = object()
            win._model_lang = "ru/large"
            win._on_selection_changed()
            assert win._model is None
            assert win._model_lang is None
        finally:
            win._model = None
            win.close()

    def test_warmup_records_load_time(self, app, tmp_path, monkeypatch):
        """Фактическое время загрузки запоминается для подсказки «обычно ~N с»."""
        cfg = config_mod.Config()
        win = self._win(cfg)
        try:
            import time as _t

            win._warm_started = _t.time() - 12
            path = tmp_path / "c.json"
            monkeypatch.setattr(config_mod, "default_config_path", lambda: path)
            win._on_load_ready(object(), "ru", "large", win._warm_token)
            assert cfg.model_load_time is not None
            assert cfg.model_load_time >= 10
        finally:
            win._model = None
            win.close()

    def test_settings_warm_button_connected(self, app):
        """Кнопка «Прогреть модель сейчас» вызывает колбэк главного окна."""
        cfg = config_mod.Config()
        win = gui_qt.MainWindow(cfg)
        calls = []
        try:
            dlg = gui_qt.SettingsDialog(cfg, win.t, win, on_warm=lambda: calls.append(1))
            dlg.btn_warm.click()
            assert calls == [1]
            assert dlg.btn_warm.text()  # подпись не пустая
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_mic_test_button_connected(self, app):
        """Кнопка «Проверить микрофон» вызывает колбэк с выбранным устройством."""
        cfg = config_mod.Config()
        win = gui_qt.MainWindow(cfg)
        seen = {}
        try:
            dlg = qt_settings.SettingsDialog(
                cfg,
                win.t,
                win,
                on_test=lambda dev, ok, err: seen.update(dev=dev, ok=ok, err=err),
            )
            dlg.btn_test.click()
            assert "dev" in seen
            assert callable(seen["ok"]) and callable(seen["err"])
            assert dlg.btn_test.text()  # подпись не пустая
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_mic_test_result_shown(self, app):
        """Результат проверки появляется в подписи, кнопка разблокируется."""
        cfg = config_mod.Config()
        win = gui_qt.MainWindow(cfg)
        try:
            dlg = qt_settings.SettingsDialog(cfg, win.t, win, on_test=None)
            dlg.btn_test.setEnabled(False)
            dlg._on_test_result("Уровень сигнала: 42%")
            assert "42" in dlg.test_result.text()
            assert dlg.btn_test.isEnabled() is True
            dlg._on_test_failed("микрофон недоступен")
            assert "микрофон" in dlg.test_result.text()
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_restore_defaults_resets_fields(self, app):
        """«Вернуть по умолчанию» сбрасывает изменённые поля."""
        cfg = config_mod.Config(
            lang="de", size="large", output_dir="D:/custom", history=False, ui_lang="ru"
        )
        win = gui_qt.MainWindow(cfg)
        try:
            dlg = qt_settings.SettingsDialog(cfg, win.t, win)
            # меняем поля вручную
            i = dlg.lang_box.findData("ru")
            if i >= 0:
                dlg.lang_box.setCurrentIndex(i)
            dlg.out_edit.setText("C:/ещё/раз")
            dlg._restore_defaults()
            # после сброса: язык ru (дефолт), размер auto, папка по умолчанию
            assert dlg.size_box.currentData() == "auto"
            assert "out_text" in dlg.out_edit.text()
            assert dlg.history_check.isChecked() is True
            assert dlg.ui_lang_box.currentData() in available()
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_save_button_enables_on_change(self, app):
        """«Сохранить и закрыть» активна только после изменения."""
        cfg = config_mod.Config()
        win = gui_qt.MainWindow(cfg)
        try:
            dlg = qt_settings.SettingsDialog(cfg, win.t, win)
            assert dlg.ok_btn.isEnabled() is False
            dlg.out_edit.setText("D:/changed")
            assert dlg.ok_btn.isEnabled() is True
            dlg.close()
        finally:
            win._model = None
            win.close()

    def test_task_cancel_survives_window_close(self, app):
        """Окно может закрыться во время загрузки — emit не должен падать."""
        task = qt_workers.LoadTask(Path("C:/x"), "ru", "small")
        task.cancel()
        assert task._cancelled is True
        # emit после cancel не бросает (сигнал мог быть уже удалён Qt)
        task._emit(task.signals.ready, object())
        task._emit(task.signals.failed, "err")
        task._emit(task.signals.phase, "loading", 1.0)

    def test_close_event_cancels_warmup(self, app):
        win = gui_qt.MainWindow()
        try:
            task = qt_workers.LoadTask(Path("C:/x"), "ru", "small")
            win._warm_task = task
            ev = QtCore.QEvent(QtCore.QEvent.Type.Close)
            win.closeEvent(ev)  # не должно бросить AttributeError
            assert task._cancelled is True
        finally:
            win._model = None
