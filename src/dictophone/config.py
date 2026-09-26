"""Настройки приложения: значения по умолчанию + JSON-файл пользователя.

Файл настроек: `%APPDATA%\\dictophone\\config.json`
(переопределяется env-переменной `DICTOPHONE_CONFIG`).

Приоритеты значений: встроенные значения < файл настроек < аргументы CLI.
Модуль ничего не печатает и не обращается к сети — только чтение/запись JSON.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

APP_NAME = "dictophone"
CONFIG_ENV = "DICTOPHONE_CONFIG"
SIZES = ("small", "large", "auto")
UI_LANGS = ("auto",)          # плюс коды из i18n.available()


class ConfigError(ValueError):
    """Некорректный файл или значение настроек."""


@dataclass
class Config:
    """Настройки приложения."""

    lang: str = "ru"
    size: str = "small"                 # 'small' | 'large' | 'auto'
    device: Optional[str] = None        # None -> устройство по умолчанию
    output_dir: Optional[str] = None    # None -> <корень проекта>/out_text
    model_dir: Optional[str] = None     # None -> <корень проекта>/models
    postprocess: str = "heuristic"      # 'heuristic' | 'off'
    db_path: Optional[str] = None       # None -> %APPDATA%/dictophone/history.db
    history: bool = True                # писать ли распознавания в историю
    ui_lang: str = "auto"               # 'auto' -> язык интерфейса по системе
    first_run: bool = True              # показать ли выбор языка при запуске
    model_load_time: Optional[float] = None  # факт. время загрузки, с
    last_update_check: Optional[float] = None  # когда проверяли обновления, unixtime

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def field_names(cls) -> tuple[str, ...]:
        return tuple(f.name for f in fields(cls))

    def size_or_none(self) -> Optional[str]:
        """'auto' -> None (взять любую установленную), иначе явный размер."""
        return None if self.size == "auto" else self.size

    def ui_lang_or_none(self) -> Optional[str]:
        """'auto' -> None (язык системы), иначе явный код."""
        return None if self.ui_lang == "auto" else self.ui_lang


def default_config_path() -> Path:
    """Путь к файлу настроек (существует он или нет)."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME / "config.json"


def _coerce(name: str, value: Any) -> Any:
    """Привести значение к типу поля; пустые строки -> None."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None

    if name in ("size",):
        if value not in SIZES:
            raise ConfigError(
                f"Неверное значение {name}={value!r}. Допустимо: {', '.join(SIZES)}"
            )
        return value
    if name == "ui_lang":
        from .i18n import available

        allowed = ("auto", *available())
        if value not in allowed:
            raise ConfigError(
                f"Неверное значение ui_lang={value!r}. "
                f"Допустимо: {', '.join(allowed)}"
            )
        return value
    if name == "postprocess":
        from . import postprocess as _pp

        if value not in _pp.MODES:
            raise ConfigError(
                f"Неверное значение postprocess={value!r}. "
                f"Допустимо: {', '.join(sorted(_pp.MODES))}"
            )
        return value
    if name in ("history", "first_run"):
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("1", "true", "yes", "on"):
            return True
        if str(value).lower() in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"Неверное значение {name}={value!r} (нужно true/false)")
    if name in ("output_dir", "model_dir", "db_path"):
        return str(value)
    if name in ("model_load_time", "last_update_check"):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ConfigError(
                f"Неверное значение {name}={value!r} (нужно число)"
            ) from None
    if name in ("lang", "device"):
        return str(value)
    raise ConfigError(f"Неизвестный параметр: {name}")


def load_config(path: Optional[Path] = None) -> Config:
    """Прочитать настройки. Отсутствующий/битый файл -> дефолты (битый -> ошибка)."""
    cfg_path = Path(path) if path is not None else default_config_path()
    config_exists = cfg_path.is_file()
    data: dict[str, Any] = {}

    if config_exists:
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(f"Не удалось разобрать {cfg_path}: {e}") from None
        if not isinstance(raw, dict):
            raise ConfigError(f"Ожидался JSON-объект в {cfg_path}")
        data = raw

    known = set(Config.field_names())
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        if key not in known:
            raise ConfigError(
                f"Неизвестный параметр {key!r} в {cfg_path}. "
                f"Допустимо: {', '.join(sorted(known))}"
            )
        kwargs[key] = _coerce(key, value)
    if config_exists:
        kwargs["first_run"] = False
    return Config(**kwargs)


#: Ключи, которые пишем в файл ВСЕГДА, даже если значение «пустое».
#: Иначе по файлу нельзя отличить «не задано» от «сброшено в умолчание»,
#: и настройки молча «исчезают» (было: size/ui_lang пропадали из JSON).
ALWAYS_WRITE = ("size", "ui_lang", "history", "first_run", "postprocess", "lang")


def save_config(cfg: Config, path: Optional[Path] = None) -> Path:
    """Записать настройки в JSON (создавая каталоги)."""
    cfg_path = Path(path) if path is not None else default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        k: v for k, v in cfg.to_dict().items()
        if v is not None or k in ALWAYS_WRITE
    }
    cfg_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cfg_path


def set_values(
    cfg: Config,
    updates: dict[str, Any],
    path: Optional[Path] = None,
) -> tuple[Config, Path]:
    """Применить обновления и сохранить. Пустое значение -> сброс в None."""
    for key, value in updates.items():
        if key not in Config.field_names():
            raise ConfigError(f"Неизвестный параметр: {key}")
        coerced = _coerce(key, value)
        if coerced is None:
            # явный сброс: присвоить дефолт поля
            default = Config().__getattribute__(key)
            setattr(cfg, key, default)
        else:
            setattr(cfg, key, coerced)
    return cfg, save_config(cfg, path)
