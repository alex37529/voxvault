# VoxVault — распознавание речи → текст (офлайн, бесплатно, приватно)

**Русский** | [English](../README.md) | [简体中文](README.zh.md)

**Бесплатная программа для распознавания речи, которая работает офлайн и не
отправляет ваши данные в интернет.**

Запись с микрофона и транскрибация аудиофайлов на движке
[VOSK](https://alphacephei.com/vosk/) (Kaldi ASR) — локально, на CPU, без GPU
и без облака. 30+ языков распознавания, 9 языков интерфейса.

<p align="center">
  <a href="../LICENSE"><img alt="Лицензия: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <img alt="Версия" src="https://img.shields.io/badge/version-v0.3.0-8A2BE2">
  <img alt="Платформа" src="https://img.shields.io/badge/platform-Windows%20x64-0078D4">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-3776AB">
  <img alt="Интерфейс" src="https://img.shields.io/badge/GUI-PySide6%206.11-2F6FB5">
  <img alt="Движок распознавания" src="https://img.shields.io/badge/ASR-VOSK-4B8B3F">
  <img alt="Приватность" src="https://img.shields.io/badge/privacy-100%25%20offline-success">
  <img alt="Языков интерфейса" src="https://img.shields.io/badge/UI-9%20languages-6E7781">
  <img alt="Языков распознавания" src="https://img.shields.io/badge/ASR-33%20languages-6E7781">
</p>

<p align="center">
  <img src="screen.png" alt="Окно VoxVault: микрофон, пауза и стоп, живая расшифровка" width="820">
</p>

## Почему VoxVault

- **Бесплатно** — без подписки, оплаты и рекламы.
- **Приватность** — записи и тексты остаются на вашем компьютере.
- **Офлайн** — после загрузки моделей интернет не нужен.
- **Живая расшифровка** — текст появляется во время речи, есть пауза и стоп.
- **История** — все распознавания сохраняются в SQLite, с поиском.

## Установка

Скачайте `VoxVault-<версия>-win64.zip` из раздела **Releases** этого
репозитория на GitHub, распакуйте в любую папку и запустите `VoxVault.exe`.
Python не требуется.

При первом запуске программа спросит язык интерфейса и предложит скачать модель
распознавания под выбранный язык. **Модели не входят в сборку** (50 МБ–1,8 ГБ
каждый) — они скачиваются отдельно и хранятся рядом с программой.

<details>
<summary>Запуск из исходников (для разработки)</summary>

```powershell
py -m pip install -e ".[gui]"     # + зависимости CLI
winget install Gyan.FFmpeg        # опционально, для mp3/m4a/ogg

py main.py gui-qt                 # графическое приложение
py -m pytest                      # тесты
```

</details>

## Сборка exe (для разработчиков)

Нужен Python 3.12 (PyInstaller отстаёт от свежих версий Python).

```powershell
py -m pip install -e ".[gui,dev]"
python packaging\build.py --clean --zip
```

Результат: `dist\VoxVault\` (папка с exe и DLL) и
`dist\VoxVault-<версия>-win64.zip` — zip и есть файл для GitHub Releases.

Сборка `onedir`, а не `onefile`: запуск из папки мгновенный, а `onefile` каждый
раз распаковывает ~55 МБ во временный каталог и попадает под срабатывания
антивирусов.

### Один файл вместо папки

Нужен ровно один `.exe` без папки `_internal`:

```powershell
python packaging\build.py --clean --onefile
```

Получится `dist\VoxVault.exe` (55 МБ) — он сам распаковывается в
`%TEMP%\_MEI…` при каждом запуске. Работает, проверено, но:

| | папка (`onedir`) | один файл (`onefile`) |
|---|---|---|
| запуск | ~1,0 с | ~2,0 с |
| размер на диске | 152 МБ | 55 МБ |
| лишние файлы при запуске | нет | распаковка 147 МБ во временный каталог |
| антивирусы | срабатывают редко | срабатывают заметно чаще |

Для быстрого ежедневного запуска лучше папка. Если нужен ровно один файл
для скачивания — берите `--onefile` либо установщик (см. ниже).

### Установщик вместо zip

Portable zip требует распаковки и оставляет `_internal` рядом с exe. Если нужен
привычный «один setup.exe» с ярлыком в меню «Пуск» — это отдельная задача
(NSIS/Inno Setup/InstallShield), она не сделана.

Диагностика собранного приложения (приложите вывод, если что-то не работает):

```powershell
dist\VoxVault\VoxVault.exe --selftest
```

Релиз публикуется тегом: пуш `v0.3.0` → GitHub Actions собирает exe, прогоняет
тесты и `--selftest` и прикрепляет zip к релизу (`.github/workflows/release.yml`).

## Быстрый старт (CLI)

```powershell
dictophone gui-qt                            # графическое приложение
dictophone list                               # доступные языки и модели
dictophone devices                            # список микрофонов
dictophone config lang=uk size=small          # запомнить настройки
dictophone file meeting.mp3                   # → out_text\meeting.txt
dictophone mic                                # realtime → out_text\mic_<ts>.txt
dictophone history                            # что распознавали раньше
```

Все команды доступны и как `py main.py <команда>`, и в собранном exe:
`VoxVault.exe file meeting.mp3`.

## Команды

| Команда | Что делает |
|---|---|
| `gui` | графическое приложение (tkinter) |
| `list` | список языков и имён моделей VOSK |
| `devices` | список входных аудиоустройств (микрофонов) |
| `config [КЛЮЧ=ЗНАЧЕНИЕ …]` | показать/изменить настройки; `--reset` — сброс; `--path` — свой файл |
| `download` | скачать модель: `--lang`, `--size small\|large` |
| `file АУДИО` | распознать файл: `--lang`, `--size`, `-o`, `--output-dir`, `--words`, `--no-punct`, `--no-history` |
| `mic` | realtime с микрофона: `--lang`, `--size`, `--device`, `-o`, `--output-dir`, `--words`, `--no-punct`, `--no-history` |
| `history` | история распознаваний: `--limit`, `--search`, `--lang`, `--kind`; подкоманды `show <id>`, `delete <id>`, `clear --yes` |

Опции, общие для `file`/`mic`/`download`: `--model-dir` — каталог моделей
(по умолчанию `<корень>/models`).

## Графическое приложение

```powershell
dictophone gui-qt
```

Окно содержит выбор микрофона, языка распознавания и размера модели, кнопки
записи/паузы/стоп с пиктограммами и подсказками, живое поле текста, диалог
настроек и просмотр истории с поиском.

Распознавание идёт в отдельном потоке, события приходят в Qt через сигналы —
интерфейс не блокируется даже на модели `large` (её загрузка занимает до
полутора минут). Настройки пишутся в общий конфиг, поэтому CLI и GUI работают
с одними и теми же параметрами.

При запуске приложение проверяет, есть ли модель для выбранного языка, и
предлагает скачать её, если её нет. Модель прогревается в фоне, поэтому кнопка
записи срабатывает сразу.

### Только одна копия

Запустить две копии нельзя: вторая увидит занятый замок и выведет сообщение.
Это защищает от двух окон, двух фоновых загрузок модели и блокировок SQLite в
общей `history.db`. Для аварийного обхода есть переменная окружения
`VOXVAULT_NO_SINGLE_INSTANCE=1` (в тестах она включена).


## История распознаваний (SQLite)

Каждое распознавание автоматически попадает в базу
(`%APPDATA%\dictophone\history.db`): дата, вид (`mic`/`file`), язык, размер
модели, устройство, длительность аудио и сам текст.

```powershell
dictophone history --limit 10
dictophone history --search "митинг"
dictophone history show 3
dictophone history delete 3
dictophone history clear --yes
```

Отключить запись: `dictophone config history=false` или флаг `--no-history`.
GUI показывает ту же базу в окне «История».

## Знаки препинания и регистр

VOSK выдаёт текст без заглавных букв и знаков. По умолчанию включена
эвристика `postprocess=heuristic`: капитализация в начале фраз и точка на
границах сегментов плюс точка в конце.

```powershell
dictophone file a.wav                 # с пунктуацией
dictophone file a.wav --no-punct      # как распознал VOSK — «как есть»
dictophone config postprocess=off     # то же постоянно
```

Честно о границах: **запятые не восстанавливаются** — без синтаксического
разбора любое правило даёт мусор вроде «Как, дела». Нейросетевая модель
(`vosk-recasepunc`, 1.6 ГБ, на PyPI отдельного пакета не имеет) подключается
через `postprocess.set_backend()` — точка расширения готова.

## Автоопределение языка

```powershell
dictophone file speech.wav --lang auto
```

Перебираются все установленные модели, побеждает та, у которой выше средняя
уверенность слов (у «не своего» языка `conf` падает). Работает для файлов;
для микрофона в realtime смысла не имеет. Точность — эвристическая, при
очень похожих языках может ошибиться.

## Настройки

Файл: `%APPDATA%\dictophone\config.json`
(переопределяется переменной окружения `DICTOPHONE_CONFIG`).

```powershell
dictophone config                                   # показать
dictophone config lang=en-us size=large             # задать
dictophone config device=                           # сбросить устройство
dictophone config --reset                           # всё по умолчанию
```

| Ключ | Смысл | По умолчанию |
|---|---|---|
| `lang` | язык распознавания (или `auto`) | `ru` |
| `size` | `small` / `large` | авто (приоритет large) |
| `device` | индекс или часть имени микрофона | устройство по умолчанию |
| `output_dir` | куда складывать распознанное | `<корень>/out_text` |
| `model_dir` | где лежат модели | `<корень>/models` |
| `postprocess` | `heuristic` / `off` | `heuristic` |
| `history` | писать ли в SQLite | `true` |
| `db_path` | путь к базе истории | `%APPDATA%/dictophone/history.db` |
| `ui_lang` | язык интерфейса | выбирается при первом запуске |

**Приоритет:** встроенные значения < файл настроек < аргументы CLI.
То есть `dictophone config lang=de`, затем `dictophone file a.wav` возьмёт `de`,
а `dictophone file a.wav --lang fr` — уже `fr`.

## Как работает realtime

1. `devices.resolve_device()` выбирает вход по настройке/аргументу.
2. `iter_mic()` — генератор событий: читает PCM 16 кГц mono int16 блоками
   по ~0.4 с и отдаёт `SpeechEvent(kind="partial"|"final", text=...)`.
3. `transcribe_mic()` печатает partial в текущей строке, final — отдельной
   строкой, и возвращает полный текст.

Генератор — точка расширения для GUI: запустите его в своём потоке и получите
partial-строки в колбэк, ничего не переписывая. Остановка: `threading.Event`
(для GUI) или Ctrl+C (для CLI, в этом случае последний сегмент тоже доходит).

## Модели

```powershell
dictophone download --lang ru --size small    # ~50 МБ
dictophone download --lang ru --size large    # ~1.8 ГБ, точнее
```

- `small` — быстро, ~300 МБ RAM, подходит для realtime с микрофона.
- `large` — точнее, но **грузится 60–90 с** и требует много RAM. Для `file` —
  лучший выбор, для `mic` — избыточен.
- Размер выбирается явно: `--size`. Без флага берётся `large`, если она
  установлена.
- Язык определяется строго по реестру, поэтому `--lang ar` не подхватит
  тунисский `vosk-model-small-ar-tn-…`. Свою модель (не из реестра) подключают
  прямым указанием папки: `--model-dir <путь-к-папке-модели>`.

- Скачать модель можно и вручную с официальной страницы — распакуйте в `models/`.
- Загрузка идёт во временный `.part` с тремя попытками: оборванный файл не
  остаётся под финальным именем, архив проверяется на целостность, а после
  распаковки проверяется наличие обязательных файлов (`am/final.mdl`,
  `conf/mfcc.conf`, `conf/model.conf`, `graph/Gr.fst`, `graph/HCLr.fst`,
  `graph/phones/word_boundary.int`). Недокачанная модель удаляется.
  Обратите внимание: `graph/words.txt` в официальных архивах VOSK **отсутствует**,
  требовать его нельзя — иначе корректная модель удаляется как неполная.

### Распознаваемые языки (33)

Коды используются в `--lang` и в настройке `config lang=…`. Модели качаются
программой; `—` означает, что в реестре VOSK такой размер для языка не
существует.

| Код | small | large |
|---|---|---|
| `ar` | — | `vosk-model-ar-mgb2-0.4` |
| `br` | — | `vosk-model-br-0.8` |
| `ca` | `vosk-model-small-ca-0.4` | — |
| `cn` | `vosk-model-small-cn-0.22` | `vosk-model-cn-0.22` |
| `cs` | `vosk-model-small-cs-0.4-rhasspy` | — |
| `de` | `vosk-model-small-de-0.15` | `vosk-model-de-0.21` |
| `el-gr` | — | `vosk-model-el-gr-0.7` |
| `en-in` | `vosk-model-small-en-in-0.4` | `vosk-model-en-in-0.5` |
| `en-us` | `vosk-model-small-en-us-0.15` | `vosk-model-en-us-0.22` |
| `eo` | `vosk-model-small-eo-0.42` | — |
| `es` | `vosk-model-small-es-0.42` | `vosk-model-es-0.42` |
| `fa` | `vosk-model-small-fa-0.42` | `vosk-model-fa-0.42` |
| `fr` | `vosk-model-small-fr-0.22` | `vosk-model-fr-0.22` |
| `gu` | `vosk-model-small-gu-0.42` | `vosk-model-gu-0.42` |
| `hi` | `vosk-model-small-hi-0.22` | `vosk-model-hi-0.22` |
| `it` | `vosk-model-small-it-0.22` | `vosk-model-it-0.22` |
| `ja` | `vosk-model-small-ja-0.22` | `vosk-model-ja-0.22` |
| `ka` | `vosk-model-small-ka-0.42` | `vosk-model-ka-0.42` |
| `ko` | `vosk-model-small-ko-0.22` | — |
| `ky` | `vosk-model-small-ky-0.42` | `vosk-model-ky-0.42` |
| `kz` | `vosk-model-small-kz-0.42` | `vosk-model-kz-0.42` |
| `nl` | `vosk-model-small-nl-0.22` | `vosk-model-nl-spraakherkenning-0.6` |
| `pl` | `vosk-model-small-pl-0.22` | — |
| `pt` | `vosk-model-small-pt-0.3` | `vosk-model-pt-fb-v0.1.1-20220516_2113` |
| `ru` | `vosk-model-small-ru-0.22` | `vosk-model-ru-0.42` |
| `sv` | `vosk-model-small-sv-rhasspy-0.15` | — |
| `te` | `vosk-model-small-te-0.42` | — |
| `tg` | `vosk-model-small-tg-0.22` | `vosk-model-tg-0.22` |
| `tl-ph` | — | `vosk-model-tl-ph-generic-0.6` |
| `tr` | `vosk-model-small-tr-0.3` | — |
| `uk` | `vosk-model-small-uk-v3-nano` | `vosk-model-uk-v3` |
| `uz` | `vosk-model-small-uz-0.22` | — |
| `vn` | `vosk-model-small-vn-0.4` | `vosk-model-vn-0.4` |

- Только `large`: `ar`, `br`, `el-gr`, `tl-ph`.
- Только `small`: `ca`, `cs`, `eo`, `ko`, `pl`, `sv`, `te`, `tr`, `uz`.
- Та же таблица выводится командой `dictophone list`.

Язык **интерфейса** — отдельная вещь, у него свой список из 9 языков:
`ru`, `uk`, `be`, `en`, `de`, `fr`, `es`, `it`, `zh`. Выбирается при первом
запуске и в `Настройки → Интерфейс`. Он не обязан совпадать с языком
распознавания.

## Производительность (ориентир)

| | загрузка | RAM | качество RU |
|---|---|---|---|
| small-ru-0.22 | секунды | ~0.3 ГБ | хорошее |
| ru-0.42 | 60–90 с | несколько ГБ | заметно лучше |

Распознавание идёт быстрее реального времени на обеих моделях.

## Структура

```
├── main.py                  — точка входа (без установки пакета)
├── pyproject.toml           — метаданные, зависимости, extras, настройки pytest
├── README.md                — английский (по умолчанию)
├── LICENSE                  — Apache-2.0
├── docs/
│   ├── README.ru.md         — русский
│   ├── README.zh.md         — китайский (упрощённый)
│   └── screen.png           — скриншот приложения
├── src/
│   ├── requirements.txt     — зависимости (канонично — в pyproject.toml)
│   └── dictophone/
│       ├── __init__.py      — версия
│       ├── cli.py           — ArgumentParser, настройки, роутинг
│       ├── gui_qt.py        — основное окно (PySide6)
│       ├── qt_settings.py   — диалог настроек
│       ├── qt_history.py    — окно истории
│       ├── qt_model_dialog.py — выбор и скачивание модели при запуске
│       ├── qt_language.py   — выбор языка при первом запуске
│       ├── qt_workers.py    — фоновые задачи (модель, микрофон, сеть)
│       ├── single_instance.py — запуск только одной копии
│       ├── app_icon.py      — иконка окна и .ico для exe
│       ├── i18n.py          — переводы, locales/*.json
│       ├── models.py        — реестр, скачивание, загрузка, проверка целостности
│       ├── transcribe.py    — аудио + распознавание (файл / микрофон)
│       ├── config.py        — настройки пользователя
│       ├── devices.py       — входные аудиоустройства
│       ├── storage.py       — история распознаваний (SQLite)
│       ├── postprocess.py   — регистр и пунктуация
│       ├── gui.py           — запасное приложение (tkinter)
│       └── console.py       — UTF-8 в консоли
├── packaging/
│   ├── VoxVault.spec        — сборка PyInstaller (onedir)
│   ├── launcher.py          — точка входа exe + --selftest
│   ├── build.py             — сборка, проверки, zip для релиза
│   └── make_icon.py         — генерация assets/VoxVault.ico
├── .github/workflows/       — ci.yml (тесты+сборка), release.yml (релиз по тегу)
├── tests/                   — pytest
├── models/                  — модели VOSK (вход, в git НЕ коммитится)
├── out_text/                — распознанные тексты (выход)
└── test/                    — тестовые аудиофайлы
```

Зависимости: `cli → (models, transcribe, config, devices, storage, gui)`,
`transcribe → (models, postprocess)`, `postprocess → config` (только проверка
значений), `config → postprocess` (то же).

Как библиотека:

```python
from pathlib import Path
from dictophone.transcribe import transcribe, iter_mic, transcribe_file
from dictophone.models import load_model
from dictophone.storage import Storage, Entry

result = transcribe(Path("audio.wav"), lang="ru", size="small")
print(result.text, result.audio_s, result.avg_conf)

model = load_model(lang="ru", size="small")
for event in iter_mic(model, device=None):      # поток событий
    print(event.kind, event.text)

with Storage() as db:
    db.add(Entry(kind="file", text=result.text, lang=result.lang))
```

## Специфика Windows

- VOSK (C++/Kaldi) не открывает файлы по пути с не-ASCII. Если проект лежит в
  кириллической папке (например `C:\work\диктофон`), при загрузке модели
  автоматически создаётся junction в
  `%LOCALAPPDATA%\dictophone\vosk_ascii\<каталог>_<хэш>` и модель грузится
  оттуда. Переопределяется `VOSK_ASCII_ROOT`.
- Консоль переводится в UTF-8 автоматически, иначе русский текст — кракозябры.
- Для mp3/m4a/ogg нужен `ffmpeg`.
- Модели и тексты в собранной версии кладутся **рядом с exe**, а если папка
  не для записи (например, установка в `Program Files`) — в
  `%LOCALAPPDATA%\VoxVault`.

## Что дальше (планируется)

- Нейросетевая пунктуация/регистр (`vosk-recasepunc`) — точка расширения
  `postprocess.set_backend()` готова, не хватает только бэкенда.
- Удаление запасного tkinter-интерфейса (`gui.py`) — после успешных сборок.
- Улучшение автоопределения языка (сейчас — эвристика по средней уверенности).
- Досылка прерванной загрузки модели (HTTP Range).
