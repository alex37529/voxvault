"""CLI: сборка ArgumentParser и роутинг команд.

Держит только «внешний» слой: аргументы, подстановку настроек и диспетчеризацию.
Бизнес-логика — в models.py (модели), transcribe.py (распознавание),
config.py (настройки), devices.py (аудиоустройства).

Приоритет значений: встроенные дефолты < файл настроек < аргументы CLI.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from dictophone import config as config_mod
from dictophone import devices as devices_mod
from dictophone import models, storage, transcribe
from dictophone import __version__
from dictophone.console import setup_console

SIZE_HELP = (
    "размер модели: small (~50 МБ) | large (~1,8 ГБ); "
    "по умолчанию — из настроек, иначе авто (приоритет large)"
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _add_model_dir(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="каталог моделей (по умолчанию из настроек, "
        f"иначе {models.DEFAULT_MODEL_DIR})",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dictophone",
        description="Распознавание речи в текст (VOSK, офлайн, много языков)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"VoxVault {__version__}",
        help="показать версию программы и выйти",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="список доступных языков и моделей")
    sub.add_parser("devices", help="список микрофонов (входных устройств)")
    sub.add_parser("gui", help="графическое приложение (tkinter)")
    sub.add_parser("gui-qt", help="графическое приложение (PySide6, пилот)")

    # --- история -----------------------------------------------------------
    p_hist = sub.add_parser("history", help="история распознаваний (SQLite)")
    p_hist.add_argument(
        "--limit", type=int, default=20, help="сколько записей (по умолчанию 20)"
    )
    p_hist.add_argument("--search", default=None, help="поиск подстроки в тексте")
    p_hist.add_argument("--lang", default=None, help="только этот язык")
    p_hist.add_argument(
        "--kind",
        choices=["mic", "file"],
        default=None,
        help="только микрофон или только файлы",
    )
    p_hist.add_argument("--db", type=Path, default=None, help="путь к базе")
    h_sub = p_hist.add_subparsers(dest="history_cmd")
    p_show = h_sub.add_parser("show", help="показать запись по id")
    p_show.add_argument("id", type=int)
    p_show.add_argument("--db", type=Path, default=None)
    p_del = h_sub.add_parser("delete", help="удалить запись по id")
    p_del.add_argument("id", type=int)
    p_del.add_argument("--db", type=Path, default=None)
    p_clear = h_sub.add_parser("clear", help="очистить историю")
    p_clear.add_argument("--yes", action="store_true", help="без подтверждения")
    p_clear.add_argument("--db", type=Path, default=None)

    # --- настройки ---------------------------------------------------------
    p_cfg = sub.add_parser("config", help="показать/изменить настройки")
    p_cfg.add_argument(
        "--path", type=Path, default=None, help="где лежит/куда писать файл настроек"
    )
    p_cfg.add_argument(
        "assignments",
        nargs="*",
        metavar="КЛЮЧ=ЗНАЧЕНИЕ",
        help="например: config lang=uk size=small (пустое значение сбрасывает: device=)",
    )
    p_cfg.add_argument(
        "--reset",
        action="store_true",
        help="сбросить настройки к значениям по умолчанию "
        "(язык интерфейса и first_run не трогаются)",
    )
    p_cfg.add_argument(
        "--ask-language",
        action="store_true",
        help="показать выбор языка при следующем запуске",
    )

    # --- загрузка моделей --------------------------------------------------
    p_dl = sub.add_parser("download", help="скачать модель VOSK")
    p_dl.add_argument("--lang", default=None, help="язык (по умолчанию ru); список: list")
    p_dl.add_argument(
        "--size",
        choices=["small", "large"],
        default=None,
        help="small: ~50 МБ (быстрее), large: точнее",
    )
    _add_model_dir(p_dl)

    # --- файл --------------------------------------------------------------
    p_file = sub.add_parser("file", help="распознать аудиофайл (wav, mp3, m4a, ogg...)")
    p_file.add_argument("audio", type=Path)
    p_file.add_argument("--lang", default=None, help="язык распознавания")
    p_file.add_argument(
        "--size", choices=["small", "large"], default=None, help=SIZE_HELP
    )
    p_file.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="файл результата (по умолчанию <output_dir>/<имя>.txt)",
    )
    p_file.add_argument(
        "--output-dir", type=Path, default=None, help="каталог для результатов"
    )
    p_file.add_argument(
        "--words",
        action="store_true",
        help="разметка по словам (медленнее, для субтитров)",
    )
    p_file.add_argument(
        "--no-punct",
        action="store_true",
        help="не расставлять знаки препинания и регистр",
    )
    p_file.add_argument(
        "--no-history", action="store_true", help="не сохранять в историю (SQLite)"
    )
    _add_model_dir(p_file)

    # --- микрофон ----------------------------------------------------------
    p_mic = sub.add_parser("mic", help="распознавание с микрофона в реальном времени")
    p_mic.add_argument("--lang", default=None, help="язык распознавания")
    p_mic.add_argument("--size", choices=["small", "large"], default=None, help=SIZE_HELP)
    p_mic.add_argument(
        "--device", default=None, help="микрофон: индекс или часть имени (см. devices)"
    )
    p_mic.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="файл результата (по умолчанию <output_dir>/mic_<ts>.txt)",
    )
    p_mic.add_argument(
        "--output-dir", type=Path, default=None, help="каталог для результатов"
    )
    p_mic.add_argument(
        "--words", action="store_true", help="разметка по словам (медленнее)"
    )
    p_mic.add_argument(
        "--no-punct",
        action="store_true",
        help="не расставлять знаки препинания и регистр",
    )
    p_mic.add_argument(
        "--no-history", action="store_true", help="не сохранять в историю (SQLite)"
    )
    _add_model_dir(p_mic)

    return parser


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------


def _resolve(
    args: argparse.Namespace,
    cfg: config_mod.Config,
    key: str,
) -> Any:
    """Значение параметра: явный аргумент CLI > настройка > None."""
    cli_value = getattr(args, key, None)
    if cli_value not in (None, ""):
        return cli_value
    return getattr(cfg, key)


def _output_path(args: argparse.Namespace, cfg: config_mod.Config, stem: str) -> Path:
    if getattr(args, "output", None):
        return Path(args.output)
    out_dir = _resolve(args, cfg, "output_dir")
    base = Path(out_dir) if out_dir else models.DEFAULT_OUTPUT_DIR
    return base / f"{stem}.txt"


# ---------------------------------------------------------------------------
# Роутинг
# ---------------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    print(models.format_models_table())


def _cmd_devices(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    try:
        print(devices_mod.format_devices_table())
    except devices_mod.DeviceError as e:
        raise SystemExit(str(e)) from None


def _cmd_config(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    path = Path(args.path) if args.path else config_mod.default_config_path()
    try:
        if args.reset:
            current = config_mod.Config()
            # Сброс настроек НЕ должен снова спрашивать язык при запуске —
            # это отдельное решение пользователя (см. --ask-language).
            current.first_run = cfg.first_run
            current.ui_lang = cfg.ui_lang
            saved = config_mod.save_config(current, path)
            print(f"Настройки сброшены. Файл: {saved}")
            return

        if args.ask_language:
            # Намеренно переспросить язык при следующем запуске.
            current = config_mod.load_config(path)
            current.first_run = True
            saved = config_mod.save_config(current, path)
            print(f"При следующем запуске будет показан выбор языка. Файл: {saved}")
            return

        if not args.assignments:
            current = config_mod.load_config(path)
            print(f"Файл настроек: {path}")
            for key, value in current.to_dict().items():
                print(f"  {key:<12} = {value if value is not None else '(по умолчанию)'}")
            return

        updates: dict[str, Any] = {}
        for item in args.assignments:
            if "=" not in item:
                raise SystemExit(f"Ожидался формат КЛЮЧ=ЗНАЧЕНИЕ, получено: {item!r}")
            key, _, value = item.partition("=")
            updates[key.strip()] = value.strip()

        lang = updates.get("lang")
        if lang and lang.lower() not in models.MODELS:
            raise SystemExit(
                f"Неизвестный язык {lang!r}. Доступны: {', '.join(models.known_langs())}"
            )

        current, saved = config_mod.set_values(
            config_mod.load_config(path), updates, path
        )
        print(f"Сохранено в {saved}")
        for key in updates:
            value = getattr(current, key)
            print(f"  {key:<12} = {value if value is not None else '(по умолчанию)'}")

    except config_mod.ConfigError as e:
        raise SystemExit(str(e)) from None


def _cmd_gui(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    from dictophone import gui

    code = gui.main()
    if code:
        raise SystemExit(code)


def _cmd_gui_qt(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    try:
        from dictophone import gui_qt
    except ImportError:
        raise SystemExit(
            "Не установлен PySide6-Essentials.\n"
            "Установите: py -m pip install PySide6-Essentials"
        ) from None
    raise SystemExit(gui_qt.main() or 0)


def _db(args: argparse.Namespace, cfg: config_mod.Config) -> storage.Storage:
    raw = getattr(args, "db", None) or cfg.db_path
    return storage.Storage(Path(raw) if raw else None)


def _cmd_history(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    with _db(args, cfg) as db:
        sub = getattr(args, "history_cmd", None)

        if sub == "show":
            row = db.get(args.id)
            if row is None:
                raise SystemExit(f"Запись #{args.id} не найдена")
            print(
                f"#{row['id']}  {row['created_at']}  {row['kind']}  "
                f"язык={row['lang'] or '?'}  {row['audio_s'] or 0:.1f} c"
            )
            if row["source"]:
                print(f"источник: {row['source']}")
            if row["output_path"]:
                print(f"файл:     {row['output_path']}")
            print("-" * 60)
            print(row["text"])
            return

        if sub == "delete":
            if db.delete(args.id):
                print(f"Запись #{args.id} удалена")
            else:
                raise SystemExit(f"Запись #{args.id} не найдена")
            return

        if sub == "clear":
            if not args.yes:
                total = db.count()
                raise SystemExit(f"В истории {total} записей. Для очистки добавьте --yes")
            removed = db.clear()
            print(f"Удалено записей: {removed}")
            return

        if args.search:
            rows = db.search(args.search, limit=args.limit)
        else:
            rows = db.list(limit=args.limit, lang=args.lang, kind=args.kind)

        if not rows:
            print("История пуста.")
            return
        total = db.count()
        print(f"Показано {len(rows)} из {total}. База: {db.path}\n")
        for row in rows:
            print(storage.format_entry(row))


def _postprocess_mode(args: argparse.Namespace, cfg: config_mod.Config) -> str:
    if getattr(args, "no_punct", False):
        return "off"
    return cfg.postprocess or "heuristic"


def _save_history(
    args: argparse.Namespace,
    cfg: config_mod.Config,
    *,
    kind: str,
    result: transcribe.Result,
    output: Optional[Path],
    source: Optional[Path] = None,
    size: Optional[str] = None,
    device: Optional[int] = None,
    model_name: Optional[str] = None,
) -> None:
    """Записать распознавание в SQLite, если это не отключено настройками."""
    if getattr(args, "no_history", False) or not cfg.history:
        return
    try:
        with _db(args, cfg) as db:
            db.add(
                storage.Entry(
                    kind=kind,
                    text=result.text,
                    lang=result.lang,
                    source=str(source) if source else None,
                    model_size=size or "auto",
                    model_name=model_name,
                    device=str(device) if device is not None else None,
                    audio_s=result.audio_s,
                    output_path=str(output) if output else None,
                )
            )
    except Exception as e:  # noqa: BLE001 - история не должна ломать распознавание
        print(f"(!) не удалось сохранить в историю: {e}")


def _cmd_download(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    lang = args.lang or cfg.lang
    size = args.size or cfg.size
    model_dir = Path(_resolve(args, cfg, "model_dir") or models.DEFAULT_MODEL_DIR)
    _validate_lang(lang)
    models.download_model(lang, size, model_dir)


def _cmd_file(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    lang = args.lang or cfg.lang
    if lang != "auto":
        _validate_lang(lang)
    size = _resolve(args, cfg, "size")
    model_dir = Path(_resolve(args, cfg, "model_dir") or models.DEFAULT_MODEL_DIR)
    output = _output_path(args, cfg, Path(args.audio).stem)

    result = transcribe.transcribe(
        Path(args.audio),
        lang=lang,
        size=size,
        model_dir=model_dir,
        output=output,
        words=args.words,
        postprocess=_postprocess_mode(args, cfg),
    )
    _save_history(
        args,
        cfg,
        kind="file",
        result=result,
        output=output,
        source=Path(args.audio),
        size=size,
    )


def _cmd_mic(args: argparse.Namespace, cfg: config_mod.Config) -> None:
    lang = args.lang or cfg.lang
    _validate_lang(lang)
    size = _resolve(args, cfg, "size")
    model_dir = Path(_resolve(args, cfg, "model_dir") or models.DEFAULT_MODEL_DIR)

    try:
        device = devices_mod.resolve_device(_resolve(args, cfg, "device"))
    except devices_mod.DeviceError as e:
        raise SystemExit(str(e)) from None

    output = _output_path(args, cfg, f"mic_{datetime.now():%Y%m%d_%H%M%S}")
    result = transcribe.transcribe(
        None,  # source=None → микрофон
        lang=lang,
        size=size,
        model_dir=model_dir,
        device=device,
        output=output,
        words=args.words,
        postprocess=_postprocess_mode(args, cfg),
    )
    _save_history(
        args, cfg, kind="mic", result=result, output=output, size=size, device=device
    )


_COMMANDS = {
    "list": _cmd_list,
    "devices": _cmd_devices,
    "config": _cmd_config,
    "download": _cmd_download,
    "file": _cmd_file,
    "mic": _cmd_mic,
    "history": _cmd_history,
    "gui": _cmd_gui,
    "gui-qt": _cmd_gui_qt,
}


def _validate_lang(lang: str) -> None:
    """Проверить, что язык есть в реестре (хотя бы один размер)."""
    if lang.lower() not in models.MODELS:
        raise SystemExit(
            f"Неизвестный язык {lang!r}. Доступны: {', '.join(models.known_langs())}"
        )


def main(argv: Optional[Sequence[str]] = None) -> None:
    setup_console()  # UTF-8 в консоли — вызывается всеми точками входа
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    cfg_path = getattr(args, "path", None)
    cfg_path = Path(cfg_path) if (cfg_path and args.command == "config") else None
    try:
        cfg = config_mod.load_config(cfg_path)
    except config_mod.ConfigError as e:
        raise SystemExit(str(e)) from None

    _COMMANDS[args.command](args, cfg)
