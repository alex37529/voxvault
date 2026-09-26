"""Аудиоустройства ввода (PortAudio через sounddevice).

Позволяет перечислить микрофоны и выбрать конкретный по индексу или имени —
это нужно и для настроек приложения, и для будущего GUI.
"""

from __future__ import annotations

from typing import Optional, Union

DeviceSpec = Union[None, int, str]


class DeviceError(RuntimeError):
    """Устройство не найдено или недоступно."""


def _sd():
    """Ленивый импорт sounddevice: не нужен, если микрофон не используем."""
    try:
        import sounddevice as sd
    except ImportError as e:  # pragma: no cover - зависит от окружения
        raise DeviceError("sounddevice не установлен: pip install sounddevice") from e
    return sd


def list_input_devices() -> list[dict]:
    """Список устройств ввода: индекс, имя, каналы, частота по умолчанию."""
    sd = _sd()
    out: list[dict] = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) < 1:
            continue
        out.append(
            {
                "index": idx,
                "name": dev.get("name", f"device-{idx}"),
                "channels": dev.get("max_input_channels", 0),
                "samplerate": int(dev.get("default_samplerate") or 0),
                "is_default": idx == default_input_device(),
            }
        )
    return out


def default_input_device() -> Optional[int]:
    """Индекс устройства ввода по умолчанию или None."""
    sd = _sd()
    try:
        idx = sd.default.device[0]
    except Exception:  # noqa: BLE001 - PortAudio отдаёт что угодно
        return None
    return int(idx) if idx is not None and idx >= 0 else None


def resolve_device(spec: DeviceSpec = None) -> Optional[int]:
    """Превратить настройку устройства в индекс.

    None -> устройство по умолчанию; int/"3" -> по индексу;
    строка -> первое устройство ввода, чьё имя содержит подстроку
    (без учёта регистра).
    """
    if spec is None or (isinstance(spec, str) and not spec.strip()):
        return default_input_device()

    if isinstance(spec, int):
        idx = spec
    else:
        text = str(spec).strip()
        if text.lstrip("-").isdigit():
            idx = int(text)
        else:
            needle = text.casefold()
            devices = list_input_devices()
            hit = next((d for d in devices if needle in d["name"].casefold()), None)
            if hit is None:
                available = ", ".join(f"{d['index']}:{d['name']}" for d in devices)
                raise DeviceError(
                    f"Устройство {spec!r} не найдено. Доступные входы: {available or 'нет'}"
                )
            return int(hit["index"])

    devices = list_input_devices()
    if not any(d["index"] == idx for d in devices):
        raise DeviceError(f"Устройство с индексом {idx} не является входным каналом")
    return int(idx)


def format_devices_table() -> str:
    """Таблица входных устройств для вывода в терминал."""
    devices = list_input_devices()
    if not devices:
        return "Входные аудиоустройства не найдены."
    lines = ["Входные устройства (микрофоны):"]
    for d in devices:
        mark = "*" if d["is_default"] else " "
        lines.append(
            f" {mark} [{d['index']:>2}] {d['name']}  "
            f"({d['channels']} кан., {d['samplerate']} Гц)"
        )
    lines.append(
        "\n* — устройство по умолчанию. Выбрать: --device <индекс|фрагмент имени>"
    )
    return "\n".join(lines)
