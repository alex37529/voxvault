"""Работа с моделями VOSK: реестр, поиск, скачивание, загрузка.

Отдельный модуль, чтобы «внутряки» не жили в CLI (main.py).
Все функции идемпотентны: повторный вызов не перезаписывает уже установленное.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

#: Каталог проекта: src/dictophone/<этот файл> -> parents[2] = корень проекта.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _data_root() -> Path:
    r"""Куда класть модели и тексты.

    В исходниках это корень проекта. В собранном exe `__file__` указывает
    внутрь `sys._MEIPASS`, и `parents[2]` уезжает в `_internal/..` — модели
    скачивались бы в неправильное место, а в Program Files ещё и без прав
    на запись. Поэтому для заморозки берём каталог рядом с exe (удобно для
    portable-релиза), а если он не для записи — `%LOCALAPPDATA%\VoxVault`.
    """
    if not getattr(sys, "frozen", False):
        return PROJECT_ROOT
    exe_dir = Path(sys.executable).resolve().parent
    probe = exe_dir / ".voxvault-write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "VoxVault"
    return exe_dir


DATA_ROOT = _data_root()
DEFAULT_MODEL_DIR = DATA_ROOT / "models"
DEFAULT_OUTPUT_DIR = DATA_ROOT / "out_text"
MODELS_BASE = "https://alphacephei.com/vosk/models"

# Реестр моделей VOSK: язык -> {размер: имя_архива | None}.
# Имена взяты со страницы https://alphacephei.com/vosk/models.
# Версии у каждого языка свои — фиксированный шаблон под них не уйдёт.
MODELS: dict[str, dict[str, Optional[str]]] = {
    "ru": {"small": "vosk-model-small-ru-0.22", "large": "vosk-model-ru-0.42"},
    "en-us": {"small": "vosk-model-small-en-us-0.15", "large": "vosk-model-en-us-0.22"},
    "en-in": {"small": "vosk-model-small-en-in-0.4", "large": "vosk-model-en-in-0.5"},
    "cn": {"small": "vosk-model-small-cn-0.22", "large": "vosk-model-cn-0.22"},
    "uk": {"small": "vosk-model-small-uk-v3-nano", "large": "vosk-model-uk-v3"},
    "fr": {"small": "vosk-model-small-fr-0.22", "large": "vosk-model-fr-0.22"},
    "de": {"small": "vosk-model-small-de-0.15", "large": "vosk-model-de-0.21"},
    "es": {"small": "vosk-model-small-es-0.42", "large": "vosk-model-es-0.42"},
    "it": {"small": "vosk-model-small-it-0.22", "large": "vosk-model-it-0.22"},
    "pt": {
        "small": "vosk-model-small-pt-0.3",
        "large": "vosk-model-pt-fb-v0.1.1-20220516_2113",
    },
    "pl": {"small": "vosk-model-small-pl-0.22", "large": None},
    "nl": {
        "small": "vosk-model-small-nl-0.22",
        "large": "vosk-model-nl-spraakherkenning-0.6",
    },
    "tr": {"small": "vosk-model-small-tr-0.3", "large": None},
    "fa": {"small": "vosk-model-small-fa-0.42", "large": "vosk-model-fa-0.42"},
    "hi": {"small": "vosk-model-small-hi-0.22", "large": "vosk-model-hi-0.22"},
    "el-gr": {"small": None, "large": "vosk-model-el-gr-0.7"},
    "ar": {"small": None, "large": "vosk-model-ar-mgb2-0.4"},
    "vn": {"small": "vosk-model-small-vn-0.4", "large": "vosk-model-vn-0.4"},
    "ja": {"small": "vosk-model-small-ja-0.22", "large": "vosk-model-ja-0.22"},
    "ko": {"small": "vosk-model-small-ko-0.22", "large": None},
    "cs": {"small": "vosk-model-small-cs-0.4-rhasspy", "large": None},
    "sv": {"small": "vosk-model-small-sv-rhasspy-0.15", "large": None},
    "kz": {"small": "vosk-model-small-kz-0.42", "large": "vosk-model-kz-0.42"},
    "ky": {"small": "vosk-model-small-ky-0.42", "large": "vosk-model-ky-0.42"},
    "uz": {"small": "vosk-model-small-uz-0.22", "large": None},
    "tg": {"small": "vosk-model-small-tg-0.22", "large": "vosk-model-tg-0.22"},
    "ka": {"small": "vosk-model-small-ka-0.42", "large": "vosk-model-ka-0.42"},
    "gu": {"small": "vosk-model-small-gu-0.42", "large": "vosk-model-gu-0.42"},
    "te": {"small": "vosk-model-small-te-0.42", "large": None},
    "ca": {"small": "vosk-model-small-ca-0.4", "large": None},
    "eo": {"small": "vosk-model-small-eo-0.42", "large": None},
    "br": {"small": None, "large": "vosk-model-br-0.8"},
    "tl-ph": {"small": None, "large": "vosk-model-tl-ph-generic-0.6"},
}


class ModelNotAvailableError(RuntimeError):
    """Запрошенная модель (размер/язык) не существует в реестре."""


class DownloadCancelled(Exception):
    """Пользователь отменил скачивание (stop_event установлен)."""


# ---------------------------------------------------------------------------
# Реестр
# ---------------------------------------------------------------------------


def known_langs() -> list[str]:
    """Отсортированный список установленных языков реестра."""
    return sorted(MODELS)


def model_name(lang: str, size: str = "small") -> str:
    """Имя архива VOSK для языка/размера.

    Валидирует язык и размер: неизвестный язык -> ModelNotAvailableError,
    нет размера -> ModelNotAvailableError с подсказкой про альтернативу.
    """
    lang = lang.lower()
    if lang not in MODELS:
        raise ModelNotAvailableError(
            f"Неизвестный язык '{lang}'. Доступны: {', '.join(known_langs())}"
        )
    fname = MODELS[lang].get(size)
    if fname is None:
        other = "large" if size == "small" else "small"
        alt = MODELS[lang].get(other)
        msg = f"Для языка '{lang}' нет модели размера '{size}'."
        if alt:
            msg += f" Доступен '{other}' ({alt})."
        else:
            msg += " Для этого языка в реестре только другой размер."
        raise ModelNotAvailableError(msg)
    return fname


def model_url(lang: str, size: str = "small") -> str:
    return f"{MODELS_BASE}/{model_name(lang, size)}.zip"


def format_models_table() -> str:
    """Готовый для вывода табличный список моделей (для `list`)."""
    lines = ["Языки и модели (имя архива VOSK):"]
    for lang in known_langs():
        small = MODELS[lang].get("small") or "-"
        large = MODELS[lang].get("large") or "-"
        lines.append(f"  {lang:6s}  small={small:42s}  large={large}")
    first = known_langs()[0] if known_langs() else "ru"
    lines.append(f"\nУстановить: py main.py download --lang {first} [--size small|large]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Файловая система
# ---------------------------------------------------------------------------


def _lang_matches(name: str, lang: str) -> bool:
    """Совпадает ли каталог модели с языком — ТОЛЬКО по именам из реестра.

    Подстрочный матч не используется намеренно: иначе 'ar' цепляет
    'vosk-model-small-ar-tn-...' (тунисский арабский), а 'en' — 'en-in'.
    Модели, скачанные вручную, подключаются указанием --model-dir на саму папку.
    """
    return name in {n for n in MODELS.get(lang, {}).values() if n}


def _is_model_dir(path: Path) -> bool:
    """Похоже ли содержимое на каталог модели VOSK (а не на папку с моделями).

    Признак — наличие am/final.mdl. Имя не проверяем: ручная модель может
    называться как угодно, и тогда на неё указывают --model-dir напрямую.
    """
    return path.is_dir() and (path / "am" / "final.mdl").exists()


def find_model(
    model_dir: Path,
    lang: Optional[str] = None,
    size: Optional[str] = None,
) -> Optional[Path]:
    """Путь к установленной модели по языку/размеру/каталогу.

    - Если model_dir сам является папкой модели — возвращаем его (а не ищем внутри).
    - lang:  язык по реестру; None — любая.
    - size:  'small'/'large'; None — любая (приоритет large).
    - None:  подходящих моделей нет.
    """
    if _is_model_dir(model_dir):
        return model_dir
    if not model_dir.is_dir():
        return None
    lang = (lang or "").lower()

    def valid(entry: Path) -> bool:
        return (
            entry.is_dir()
            and "vosk-model" in entry.name
            and "recasepunc" not in entry.name
            and (entry / "am" / "final.mdl").exists()
        )

    all_ok = [e for e in model_dir.iterdir() if valid(e)]
    if lang:
        all_ok = [e for e in all_ok if _lang_matches(e.name, lang)]
    if not all_ok:
        return None
    if size:
        if size == "small":
            all_ok = [e for e in all_ok if "small" in e.name]
        elif size == "large":
            all_ok = [e for e in all_ok if "small" not in e.name]
        if not all_ok:
            return None

    # large (non-small) точнее — при равенстве приоритет у него
    def _key(e: Path):
        return (1 if "small" not in e.name else 0, e.name)

    return sorted(all_ok, key=_key)[-1]


def download_model(
    lang: str,
    size: str = "small",
    model_dir: Path = DEFAULT_MODEL_DIR,
    progress_cb=None,
    stop_event=None,
) -> Path:
    """Скачать и установить модель (с прогрессом). Возвращает путь к модели.

    Если каталог уже содержит именно этот архив — возвращаем его без скачивания.
    Если каталог содержит только другой размер (small против large) — качаем large.

    progress_cb(downloaded_bytes, total_bytes) — для GUI; None → печать в stdout.
    stop_event — threading.Event: установлен -> отмена, .part удаляется.
    """

    url = model_url(lang, size)
    model_dir.mkdir(parents=True, exist_ok=True)
    zip_path = model_dir / url.rsplit("/", 1)[-1]

    # Проверяем именно запрошенный архив (имя из реестра)
    archive_name = model_name(lang, size)
    candidate = model_dir / archive_name
    if _is_model_dir(candidate):
        print(f"Модель уже установлена: {candidate}")
        return candidate

    # Качаем во временный .part: повреждённый файл не должен остаться
    # под финальным именем (иначе следующий вызов решит, что модель есть).
    part = zip_path.with_suffix(zip_path.suffix + ".part")
    try:
        _fetch_archive(url, part, progress_cb=progress_cb, stop_event=stop_event)
        _extract_verified(zip_path=part, model_dir=model_dir, archive_name=archive_name)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.unlink(missing_ok=True)

    model = model_dir / archive_name
    print(f"Модель готова: {model}")
    return model


def _fetch_archive(
    url: str,
    dest: Path,
    attempts: int = 3,
    progress_cb=None,
    stop_event=None,
) -> None:
    """Скачать архив с прогрессом и проверкой размера. Повтор при обрыве.

    Отмена (stop_event) не считается обрывом и не перезапускает попытку.
    """
    import requests

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"Скачиваю: {url}")
            downloaded = 0
            total = 0
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                last_pct = -1
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if not chunk:
                            continue
                        if stop_event is not None and stop_event.is_set():
                            raise DownloadCancelled()
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb is not None:
                            progress_cb(downloaded, total)
                        elif total:
                            pct = downloaded * 100 // total
                            if pct != last_pct:
                                last_pct = pct
                                sys.stdout.write(
                                    f"\r  {pct:3d}%  ({downloaded >> 20} МБ)"
                                )
                                sys.stdout.flush()
            if progress_cb is None:
                sys.stdout.write("\n")
                sys.stdout.flush()
            if total and downloaded != total:
                raise OSError(f"скачано {downloaded} байт, ожидалось {total} — обрыв")
            if downloaded == 0:
                raise OSError("пустой ответ сервера")
            return
        except DownloadCancelled:
            raise  # отмена — не повторять
        except Exception as e:  # noqa: BLE001 - ловим и сети, и HTTP
            last_error = e
            dest.unlink(missing_ok=True)
            if attempt < attempts:
                print(f"  не получилось ({e}), попытка {attempt}/{attempts}…")
    raise SystemExit(f"Не удалось скачать модель: {last_error}")


def _extract_verified(zip_path: Path, model_dir: Path, archive_name: str) -> None:
    """Распаковать архив и проверить, что модель пригодна к работе."""
    import zipfile

    print("Распаковка...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                raise zipfile.BadZipFile(f"повреждён элемент {bad}")
            zf.extractall(model_dir)
    except zipfile.BadZipFile as e:
        # недокачанный/битый архив — распакованное убираем
        shutil.rmtree(model_dir / archive_name, ignore_errors=True)
        raise SystemExit(f"Архив модели повреждён: {e}") from None

    model = model_dir / archive_name
    missing = validate_model_dir(model)
    if missing:
        shutil.rmtree(model, ignore_errors=True)
        raise SystemExit(
            "Модель распаковалась не полностью, недостают: "
            + ", ".join(missing)
            + " (graph/*.fst — любой файл графа декодирования)"
        )


def installed_langs(model_dir: Path = DEFAULT_MODEL_DIR) -> list[str]:
    """Языки, для которых в каталоге есть хотя бы одна ASR-модель."""
    if not Path(model_dir).is_dir():
        return []
    present = {
        e.name
        for e in Path(model_dir).iterdir()
        if _is_model_dir(e) and "recasepunc" not in e.name
    }
    found = []
    for lang in MODELS:
        names = {n for n in MODELS[lang].values() if n}
        if names & present:
            found.append(lang)
    return found


#: Файлы, без которых модель VOSK точно нерабочая.
#:
#: Список НЕ привязан к конкретной модели. Имена файлов графа у моделей
#: разные: у старых (small-ru-0.22, small-uk-v3-nano) это `Gr.fst` +
#: `HCLr.fst`, у новых (ru-0.42, en-us-0.22, de-0.21, uk-v3, cn, ja, …) —
#: `HCLG.fst`. Раньше проверка требовала именно `Gr.fst` и `HCLr.fst`,
#: поэтому нормальная большая модель ru объявлялась битой: архив на 1,8 ГБ
#: скачивался и распаковывался, проверка его удаляла, и пользователь
#: оставался без модели. Обязательна лишь акустическая модель, конфиги и
#: граница слов; сам граф проверяется по REQUIRED_MODEL_GLOBS.
REQUIRED_MODEL_FILES = (
    "am/final.mdl",
    "conf/mfcc.conf",
    "conf/model.conf",
    "graph/phones/word_boundary.int",
)

#: Шаблоны, где достаточно любого подходящего файла (имя не фиксировано).
REQUIRED_MODEL_GLOBS = ("graph/*.fst",)


def validate_model_dir(path: Path) -> list[str]:
    """Проверить распакованную модель. Вернуть список недостающего.

    Нужна, чтобы поймать битый архив и недокачанный файл: приложение должно
    сказать об этом сразу, а не падать позже при загрузке модели в память.
    """
    path = Path(path)
    missing = [rel for rel in REQUIRED_MODEL_FILES if not (path / rel).exists()]
    missing += [
        pattern for pattern in REQUIRED_MODEL_GLOBS if not any(path.glob(pattern))
    ]
    return missing


def dir_size_mb(path: Path) -> int:
    """Размер каталога на диске в МБ (0, если не читается)."""
    try:
        total = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    except OSError:
        return 0
    return total // (1024 * 1024)


def free_space_mb(path: Path) -> int:
    """Свободное место на диске в МБ для каталога (или его ближайшего родителя)."""
    import shutil

    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free // (1024 * 1024)
    except OSError:
        return 0


def list_installed(model_dir: Path = DEFAULT_MODEL_DIR) -> list[dict]:
    """Что установлено: по записи на язык.

    Каждая запись: lang, small/large (имя каталога или None), path,
    size_mb. Используется вкладкой «Модели» в настройках.
    """
    model_dir = Path(model_dir)
    rows: list[dict] = []
    for lang in sorted(MODELS):
        entry: dict[str, Any] = {"lang": lang, "path": None, "size_mb": 0}
        for size in ("small", "large"):
            name = MODELS[lang].get(size)
            found = (model_dir / name) if name else None
            if found is not None and _is_model_dir(found):
                entry[size] = name
                entry["path"] = found
                entry["size_mb"] = dir_size_mb(found)
            else:
                entry[size] = None
        rows.append(entry)
    return rows


def delete_model(path: Path) -> int:
    """Удалить каталог модели. Вернуть освобождённое место в МБ.

    Отказываем, если это не каталог модели (am/final.mdl) — чтобы не снести
    случайно каталог моделей целиком.
    """
    target = Path(path)
    if target.resolve() == DEFAULT_MODEL_DIR.resolve():
        raise ValueError("Нельзя удалить корневой каталог моделей")
    if not _is_model_dir(target):
        raise ValueError(f"Это не каталог модели: {target}")
    freed = dir_size_mb(target)
    shutil.rmtree(target, ignore_errors=True)
    return freed


def archive_size_mb(lang: str, size: str) -> Optional[int]:
    """Примерный размер архива в МБ по данным реестра (None, если неизвестно)."""
    name = MODELS.get(lang, {}).get(size)
    if name is None:
        return None
    installed = DEFAULT_MODEL_DIR / name
    if _is_model_dir(installed):
        return dir_size_mb(installed)
    return None


# ---------------------------------------------------------------------------
# Загрузка (VOSK)
# ---------------------------------------------------------------------------

#: Фазы загрузки модели — их получает progress_cb.
PHASE_CHECKING = "checking"  # поиск папки, проверка файлов — мгновенно
PHASE_LOADING = "loading"  # чтение модели в память — долго (large: 60-90 с)
PHASE_READY = "ready"  # модель готова, можно говорить


def _load_with_progress(model_path: Path, on_tick=None):
    """Загрузить VOSK Model с индикатором времени.

    Model(...) — блокирующий C-вызов, прервать его нельзя. Фоновый поток
    каждую секунду сообщает, что процесс жив:
      - on_tick(phase, elapsed) — если передан;
      - иначе печать в stdout (поведение CLI).
    """
    import threading
    import time

    from vosk import Model

    stop = threading.Event()

    if on_tick is not None:
        on_tick(PHASE_LOADING, 0.0)

    def _tick() -> None:
        t0 = time.time()
        next_log = 10
        while not stop.wait(1.0):
            elapsed = int(time.time() - t0)
            if on_tick is not None:
                on_tick(PHASE_LOADING, float(elapsed))
                # В GUI прогресс идёт в окно, но в консоль тоже пишем раз
                # в 10 с — иначе 70 с тишины выглядят как зависание.
                if elapsed >= next_log:
                    print(f"  загрузка модели... {elapsed:>4} с", flush=True)
                    next_log += 10
            else:
                sys.stdout.write(f"\r  загрузка модели... {elapsed:>4} с  ")
                sys.stdout.flush()

    def _clear() -> None:
        if on_tick is not None:
            return
        sys.stdout.write("\r" + " " * 48 + "\r")
        sys.stdout.flush()

    th = threading.Thread(target=_tick, daemon=True)
    th.start()
    t0 = time.time()
    try:
        model = Model(str(model_path))
    finally:
        stop.set()
        th.join(timeout=0.2)
        _clear()
    if on_tick is not None:
        on_tick(PHASE_READY, time.time() - t0)
    return model


def load_model(
    model_dir: Path = DEFAULT_MODEL_DIR,
    lang: str = "ru",
    size: Optional[str] = None,
    auto_download: bool = True,
    progress_cb=None,
):
    """Открыть VOSK Model по каталогу/языку/размеру.

    size 'small'/'large' — точный выбор размера модели. None → любое (large приоритет).
    progress_cb(phase, elapsed) — вызывается с PHASE_CHECKING/PHASE_LOADING/PHASE_READY,
    чтобы GUI показывал фазу и время. None → обычный вывод в stdout (CLI).
    VOSK (C++) не открывает файлы по пути с не-ASCII (кириллица). Если путь
    содержит не-ASCII символы — сразу используем junction в ASCII-локацию,
    чтобы не было ERROR в stderr.
    """
    from vosk import SetLogLevel

    SetLogLevel(-1)  # тишина: подавить C-level VOSK messages

    def notify(phase: str, elapsed: float = 0.0) -> None:
        if progress_cb is not None:
            progress_cb(phase, elapsed)

    notify(PHASE_CHECKING)
    path = find_model(model_dir, lang, size)
    if path is None:
        if not auto_download:
            label = f" [{size}]" if size else ""
            raise SystemExit(
                f"Модель для '{lang}'{label} не найдена в {model_dir}. "
                "Запустите: py main.py download --lang ... --size ..."
            )
        dl_size = size if size in ("small", "large") else "small"
        print(f"Модель для '{lang}' [{dl_size}] не найдена, скачиваю...")
        path = download_model(lang, dl_size, model_dir)

    p = str(path)
    chosen = size or ("large" if "small" not in path.name else "small")
    # Лог всегда: пользователю нужно видеть, что происходит. GUI дополнительно
    # рисует прогресс в окне, консоль дублирует его раз в 10 секунд.
    print(f"Загружаю модель: {path.name}  [{chosen}/{lang}]", flush=True)

    # Проверяем ДО попытки загрузки: если путь содержит не-ASCII — сразу junction.
    # Это предотвращает ERROR в stderr VOSK, который нельзя перехватить в Python.
    if any(ord(c) > 127 for c in p):
        dest = make_ascii_junction(model_dir)
        return _load_with_progress(dest / path.name, notify)
    return _load_with_progress(path, notify)


def _junction_root() -> Path:
    """Куда класть junction'ы: %LOCALAPPDATA%\\dictophone\\vosk_ascii (или env)."""
    import os

    override = os.environ.get("VOSK_ASCII_ROOT")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "dictophone" / "vosk_ascii"


def make_ascii_junction(model_dir: Path) -> Path:
    """Создать junction на каталог моделей по пути без не-ASCII. Вернуть junction-путь.

    Имя junction'а выводится из пути каталога (санитайз + хэш), поэтому разные
    каталоги моделей не затирают друг друга.
    """
    import hashlib
    import os
    import re

    src = model_dir.resolve()
    digest = hashlib.sha1(str(src).encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", src.name) or "models"
    root = _junction_root()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{slug}_{digest}"

    # Убираем старый junction. На Windows junction выглядит как каталог,
    # а os.path.islink() его не распознаёт, а rmtree() по нему падает —
    # поэтому сначала пробуем os.rmdir (снимает сам junction).
    if os.path.lexists(dest):
        try:
            os.rmdir(dest)
        except OSError:
            if os.path.islink(dest):
                os.unlink(dest)
            else:
                shutil.rmtree(dest)

    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(dest), str(src)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest
