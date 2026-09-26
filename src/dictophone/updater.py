"""Проверка обновлений: последний релиз VoxVault на GitHub.

Как это устроено в других программах и почему именно так:

  - проверка идёт по HTTPS к публичному API GitHub Releases: без токена,
    без ключей и без регистрации; запрос отвечает за доли секунды;
  - сравнение версий — по числам (0.10.0 новее, чем 0.9.9), а не по
    строкам, иначе десятые релизы выглядят как откат;
  - приложение НЕ качает и не запускает файл само: пользователю даётся
    ссылка на релиз. exe неподписанное, и молчаливый запуск чужого
    бинарника в автообновлении — худший возможный вариант;
  - недоступность сети — не поломка приложения: показываем «не удалось
    проверить» и предлагаем повторить.

Модуль ничего не печатает и не трогает Qt: чистые функции разбора отделены
от сети, поэтому тестируются без интернета.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from dictophone import __version__

GITHUB_OWNER = "alex37529"
GITHUB_REPO = "voxvault"
REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
RELEASES_API = f"{REPO_URL}/releases/latest"
RELEASES_PAGE = f"{REPO_URL}/releases/latest"
ISSUES_URL = f"{REPO_URL}/issues"

#: Github требует User-Agent у всех запросов и обрывает соединение без него.
USER_AGENT = f"VoxVault/{__version__} (+{REPO_URL})"

#: Таймаут запроса, с. Проверка не должна задерживать интерфейс.
TIMEOUT = 8.0
#: Не чаще раза в сутки: ходить в сеть на каждом запуске невежливо.
CHECK_INTERVAL_S = 24 * 60 * 60

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class UpdateError(RuntimeError):
    """Проверить обновления не удалось (сеть, лимит, битый ответ)."""


@dataclass(frozen=True)
class Release:
    """Релиз с GitHub: чем он новее установленной версии."""

    version: str
    url: str = RELEASES_PAGE
    notes: str = ""
    download_url: Optional[str] = None

    def asset_url(self) -> str:
        """Куда ведёт кнопка «Скачать»: архив релиза, иначе страница.

        Архив сам качать нельзя: он не подписан, и решение о запуске
        новой программы должен принимать человек.
        """
        return self.download_url or self.url


def parse_version(text: str) -> tuple[int, int, int]:
    """'v0.2.0' / '0.2.0-rc1' -> (0, 2, 0).

    Тег релиза может быть с префиксом 'v' и с суффиксом сборки, поэтому
    сравниваются только числа. Неразобранная строка -> (0, 0, 0), и такая
    версия никогда не считается новее (см. is_newer).
    """
    match = _VERSION_RE.search(text or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer(candidate: str, current: str = __version__) -> bool:
    """Новее ли candidate, чем current."""
    return parse_version(candidate) > parse_version(current)


def pick_asset(assets: Any, version: str) -> Optional[str]:
    """Ссылка на архив релиза (VoxVault-<версия>-win64.zip) или None.

    Ищем по подстроке версии, а не по точному имени: в релизе могут быть
    ещё контрольные суммы и исходники, их качать не нужно.
    """
    plain = re.sub(r"^v", "", version or "")
    for asset in assets or ():
        name = str((asset or {}).get("name") or "")
        if not plain or plain not in name:
            continue
        if name.lower().endswith(".zip"):
            return str((asset or {}).get("browser_download_url") or "") or None
    return None


def parse_release(payload: Any, current: str = __version__) -> Optional[Release]:
    """Ответ GitHub -> Release, если он новее текущей версии.

    None означает «обновлений нет»: релиз совпадает, старее, либо ответ
    нерелевантен (другой репозиторий, битый JSON).
    """
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or payload.get("name") or "")
    if not tag or not is_newer(tag, current):
        return None
    version = re.sub(r"^v", "", tag)
    return Release(
        version=version,
        url=str(payload.get("html_url") or RELEASES_PAGE),
        notes=str(payload.get("body") or "").strip(),
        download_url=pick_asset(payload.get("assets"), version),
    )


def is_due(last_check: Optional[float], now: Optional[float] = None) -> bool:
    """Пора ли проверять обновления: ещё ни разу или прошло больше суток."""
    if not last_check:
        return True
    import time

    return (now if now is not None else time.time()) - float(last_check) >= CHECK_INTERVAL_S


def _get_json(url: str, timeout: float) -> Any:
    """GET с JSON-ответом. Сетевые ошибки -> UpdateError (вызывающий решит)."""
    import requests

    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
        )
    except Exception as e:  # noqa: BLE001 - сеть отдаёт что угодно
        raise UpdateError(str(e)) from None
    if response.status_code == 403:
        raise UpdateError("GitHub временно не отвечает (лимит запросов)")
    if response.status_code != 200:
        raise UpdateError(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise UpdateError("непонятный ответ GitHub") from None


def fetch_latest(
    current: str = __version__,
    timeout: float = TIMEOUT,
    get_json: Any = None,
) -> Optional[Release]:
    """Последний релиз GitHub, если он новее текущей версии.

    get_json — подмена HTTP-слоя для тестов (по умолчанию requests).
    """
    reader = get_json or _get_json
    return parse_release(reader(RELEASES_API, timeout), current)
