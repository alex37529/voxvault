# VoxVault — 语音转文字（离线、免费、注重隐私）

[Русский](README.ru.md) | [English](../README.md) | **简体中文**

**一款完全离线运行、绝不把您的数据发送到互联网的免费语音识别程序。**

基于 [VOSK](https://alphacephei.com/vosk/)（Kaldi ASR）引擎的麦克风录音与音频文件转写——
全部在本地 CPU 上完成，无需显卡，也不依赖云端。支持 30 多种识别语言、9 种界面语言。

<p align="center">
  <a href="../LICENSE"><img alt="许可：Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <img alt="版本" src="https://img.shields.io/badge/version-v0.1.1-8A2BE2">
  <img alt="平台" src="https://img.shields.io/badge/platform-Windows%20x64-0078D4">
  <img alt="Python" src="https://img.shields.io/badge/python-3.9%2B-3776AB">
  <img alt="界面" src="https://img.shields.io/badge/GUI-PySide6%206.11-2F6FB5">
  <img alt="识别引擎" src="https://img.shields.io/badge/ASR-VOSK-4B8B3F">
  <img alt="隐私" src="https://img.shields.io/badge/privacy-100%25%20offline-success">
  <img alt="界面语言数" src="https://img.shields.io/badge/UI-9%20languages-6E7781">
  <img alt="识别语言数" src="https://img.shields.io/badge/ASR-33%20languages-6E7781">
</p>

<p align="center">
  <img src="screen.png" alt="VoxVault 窗口：麦克风、暂停与停止按钮、实时转写文本" width="820">
</p>

## 为什么选择 VoxVault

- **免费** —— 无需订阅、付费或观看广告。
- **隐私** —— 录音和文本只保存在您的电脑上。
- **离线** —— 模型下载完成后，不再需要互联网。
- **实时转写** —— 说话时文字即时出现，支持暂停与停止。
- **历史记录** —— 所有识别结果保存在 SQLite 数据库中，可随时搜索。

## 安装

从本 GitHub 仓库的 **Releases** 部分下载 `VoxVault-<版本号>-win64.zip`，
解压到任意文件夹并运行 `VoxVault.exe`。压缩包内只有一个可执行文件，
不需要再安装任何东西。无需安装 Python。

首次启动时，程序会询问界面语言，并提示下载所选语言的识别模型。
**模型不包含在发布包中**（每个模型 50 MB–1.8 GB），它们单独下载并保存在程序旁边。

<details>
<summary>从源码运行（开发用）</summary>

```powershell
py -m pip install -e ".[gui]"     # 加上 CLI 依赖
winget install Gyan.FFmpeg        # 可选，用于 mp3/m4a/ogg

py main.py gui-qt                 # 图形界面
py -m pytest                      # 运行测试
```

</details>

## 构建 exe（开发者）

需要 Python 3.12（PyInstaller 对最新 Python 版本的跟进总是滞后）。

```powershell
py -m pip install -e ".[gui,dev]"
python packaging\build.py --clean --onefile --zip
```

产物：`dist\VoxVault.exe` 和 `dist\VoxVault-<版本号>-win64.zip` —— zip 里
**只有一个文件**，它就是上传到 GitHub Releases 的附件。没有 `_internal` 文件夹，
也没有一堆散落的 DLL：下载、解压、运行即可。

发布版本使用 `--onefile` 构建：程序每次启动都会把自己的依赖库解压到
Windows 临时目录。实测启动约 2.0 秒，而文件夹版本约 1.0 秒。

### 用文件夹构建代替单文件

`onedir` 同样可用：启动更快、更少触发杀毒软件，代价是磁盘上会多出
约 1000 个文件：

```powershell
python packaging\build.py --clean --zip
```

| | 文件夹（`onedir`） | 单文件（`onefile`，用于发布） |
|---|---|---|
| 启动速度 | 约 1.0 秒 | 约 2.0 秒 |
| 磁盘占用 | 152 MB | 55 MB |
| 启动时的额外操作 | 无 | 解压 147 MB 到临时目录 |
| 杀毒软件 | 很少误报 | 明显更容易误报 |

日常频繁使用建议用文件夹，但发布包只放一个文件，用户下载解压后即可运行。

### 用安装程序代替 zip

发布压缩包内已经只有一个可执行文件。如果您需要传统的“一个 setup.exe”
并带开始菜单快捷方式，那是另一项单独的工作
（NSIS / Inno Setup / InstallShield），目前尚未完成。

已构建程序的诊断命令（出问题时把输出附上）：

```powershell
dist\VoxVault.exe --selftest
```

发布流程基于标签：推送 `v0.1.0` 标签后，GitHub Actions 会构建 exe、
运行测试和 `--selftest`，并把 zip 附到发布页面上
（见 `.github/workflows/release.yml`）。

## 快速上手（命令行）

```powershell
dictophone gui-qt                            # 图形界面
dictophone list                              # 可用语言和模型
dictophone devices                           # 麦克风列表
dictophone config lang=uk size=small         # 保存设置
dictophone file meeting.mp3                  # → out_text\meeting.txt
dictophone mic                               # 实时 → out_text\mic_<ts>.txt
dictophone history                           # 之前的识别记录
```

所有命令也可以写成 `py main.py <命令>`，在已构建的程序中则是
`VoxVault.exe file meeting.mp3`。

## 命令一览

| 命令 | 作用 |
|---|---|
| `gui` | 图形界面（tkinter 备用版） |
| `gui-qt` | 图形界面（PySide6，主程序） |
| `list` | 列出语言和 VOSK 模型名称 |
| `devices` | 列出输入音频设备（麦克风） |
| `config [键=值 …]` | 查看/修改设置；`--reset` 重置；`--path` 指定其他文件 |
| `download` | 下载模型：`--lang`、`--size small\|large` |
| `file 音频` | 转写文件：`--lang`、`--size`、`-o`、`--output-dir`、`--words`、`--no-punct`、`--no-history` |
| `mic` | 麦克风实时识别：`--lang`、`--size`、`--device`、`-o`、`--output-dir`、`--words`、`--no-punct`、`--no-history` |
| `history` | 识别历史：`--limit`、`--search`、`--lang`、`--kind`；子命令 `show <id>`、`delete <id>`、`clear --yes` |

`file`/`mic`/`download` 共用选项：`--model-dir` —— 模型目录
（默认为 `<根目录>/models`）。

## 图形界面

```powershell
dictophone gui-qt
```

窗口中包含麦克风、识别语言和模型大小的选择器，带图标的录音/暂停/停止按钮
（配有提示文字）、实时文本区域、设置对话框，以及可搜索的历史记录窗口。

识别在独立线程中进行，事件通过 Qt 信号传回界面，因此即使使用 `large` 模型
（加载需一到一分半钟）界面也不会卡顿。设置写入同一个配置文件，所以命令行和
图形界面使用相同的选项。

启动时程序会检查所选语言的模型是否存在，不存在就提示下载。模型在后台预热，
因此录音按钮立即可用。

### 只允许一个实例

不能同时运行两个副本：第二个会检测到锁定的标记并给出提示。这样可以避免
出现两个窗口、两次后台模型加载，以及共享 `history.db` 上的 SQLite 锁定冲突。
调试用的应急开关是环境变量 `VOXVAULT_NO_SINGLE_INSTANCE=1`（测试中已启用）。

## 识别历史（SQLite）

每次识别都会自动写入数据库（`%APPDATA%\dictophone\history.db`）：
时间、来源类型（`mic`/`file`）、语言、模型大小、设备、音频时长和识别出的文本。

```powershell
dictophone history --limit 10
dictophone history --search "会议"
dictophone history show 3
dictophone history delete 3
dictophone history clear --yes
```

关闭记录：`dictophone config history=false` 或使用 `--no-history` 参数。
图形界面的“历史”窗口显示的是同一个数据库。

## 标点与大小写

VOSK 输出的文本没有大写字母和标点。默认启用 `postprocess=heuristic` 启发式规则：
短语首字母大写、段落边界加句号、结尾加句号。

```powershell
dictophone file a.wav                 # 带标点
dictophone file a.wav --no-punct      # 保持 VOSK 原始输出
dictophone config postprocess=off     # 永久关闭
```

诚实地说明局限：**逗号无法恢复** —— 没有语法分析，任何规则都会产出
“How, are you”这类乱码。神经网络模型（`vosk-recasepunc`，1.6 GB，PyPI 上没有
单独的包）可以通过 `postprocess.set_backend()` 接入，扩展点已经预留。

## 自动语言检测

```powershell
dictophone file speech.wav --lang auto
```

程序会尝试所有已安装的模型，平均词置信度最高的胜出（面对不属于自己语言的内容时
置信度会下降）。该功能适用于文件；麦克风实时识别没有意义。准确率属于启发式，
在非常相近的语言之间可能判断错误。

## 设置

文件位置：`%APPDATA%\dictophone\config.json`
（可用环境变量 `DICTOPHONE_CONFIG` 覆盖）。

```powershell
dictophone config                                   # 查看
dictophone config lang=en-us size=large             # 设置
dictophone config device=                           # 重置设备
dictophone config --reset                           # 全部恢复默认
```

| 键 | 含义 | 默认值 |
|---|---|---|
| `lang` | 识别语言（或 `auto`） | `ru` |
| `size` | `small` / `large` | `small` |
| `device` | 麦克风索引或名称的一部分 | 系统默认设备 |
| `output_dir` | 转写文本的保存位置 | `<根目录>/out_text` |
| `model_dir` | 模型存放位置 | `<根目录>/models` |
| `postprocess` | `heuristic` / `off` | `heuristic` |
| `history` | 是否写入 SQLite | `true` |
| `db_path` | 历史数据库路径 | `%APPDATA%/dictophone/history.db` |
| `ui_lang` | 界面语言 | 首次运行时选择 |

**优先级：** 内置默认值 < 设置文件 < 命令行参数。因此执行
`dictophone config lang=de` 后，`dictophone file a.wav` 使用 `de`，
而 `dictophone file a.wav --lang fr` 使用 `fr`。

## 实时识别的原理

1. `devices.resolve_device()` 根据设置或参数选择输入设备。
2. `iter_mic()` 是事件生成器：以约 0.4 秒为一块读取 16 kHz 单声道 int16 PCM，
   并产出 `SpeechEvent(kind="partial"|"final", text=...)`。
3. `transcribe_mic()` 就地打印临时结果，`final` 结果另起一行，并返回完整文本。

生成器是图形界面的扩展点：在自己的线程里运行它，就能在回调中得到临时结果，
无需重写任何东西。停止方式：图形界面用 `threading.Event`，命令行用 Ctrl+C
（此时最后一段也会被正确输出）。

## 模型

```powershell
dictophone download --lang ru --size small    # 约 50 MB
dictophone download --lang ru --size large    # 约 1.8 GB，更准确
```

- `small` —— 速度快，约占 300 MB 内存，适合麦克风实时识别。
- `large` —— 更准确，但**加载需 60–90 秒**且占用大量内存。适合 `file`，
  用于 `mic` 则过大。
- 大小用 `--size` 显式指定。
- 语言严格按注册表匹配，所以 `--lang ar` 不会误用突尼斯阿拉伯语
  `vosk-model-small-ar-tn-…`。注册表之外的自定义模型可以直接指定文件夹：
  `--model-dir <模型文件夹路径>`。

- 也可以从官方页面手动下载模型，解压到 `models/` 即可。
- 下载先写入临时 `.part` 文件，最多尝试三次：损坏的文件不会留在最终名字下，
  压缩包会做完整性校验，解压后还会检查必需文件（`am/final.mdl`、
  `conf/mfcc.conf`、`conf/model.conf`、`graph/Gr.fst`、`graph/HCLr.fst`、
  `graph/phones/word_boundary.int`）。不完整的模型会被删除。
  请注意：官方 VOSK 压缩包中**没有** `graph/words.txt`，不能把它当作必需文件，
  否则完全正常的模型会被误判为不完整而删除。

### 支持识别的语言（33 种）

下表中的代码用于 `--lang` 和设置项 `config lang=…`。模型由程序下载；
`—` 表示 VOSK 注册表中该语言没有对应大小的模型。

| 代码 | small | large |
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

- 仅有 `large`：`ar`、`br`、`el-gr`、`tl-ph`。
- 仅有 `small`：`ca`、`cs`、`eo`、`ko`、`pl`、`sv`、`te`、`tr`、`uz`。
- 同样的表格也可以用 `dictophone list` 命令输出。

界面语言是另一回事，共有 9 种：`ru`、`uk`、`be`、`en`、`de`、`fr`、`es`、`it`、`zh`，
在首次运行时或“设置 → 接口”中选择，它不必与识别语言一致。

## 性能（参考值）

| 模型 | 加载 | 内存 | 俄语质量 |
|---|---|---|---|
| small-ru-0.22 | 数秒 | 约 0.3 GB | 良好 |
| ru-0.42 | 60–90 秒 | 数 GB | 明显更好 |

两种模型的识别速度都快于实时。

## 项目结构

```
├── main.py                  — 入口（无需安装包）
├── pyproject.toml           — 元数据、依赖、extras、pytest 配置
├── README.md                — 英语（默认）
├── LICENSE                  — Apache-2.0
├── docs/
│   ├── README.ru.md         — 俄语
│   ├── README.zh.md         — 简体中文
│   └── screen.png           — 应用程序截图
├── src/
│   ├── requirements.txt     — 依赖清单（以 pyproject.toml 为准）
│   └── dictophone/
│       ├── __init__.py      — 版本号
│       ├── cli.py           — 参数解析、设置、命令路由
│       ├── gui_qt.py        — 主窗口（PySide6）
│       ├── qt_settings.py   — 设置对话框
│       ├── qt_history.py    — 历史记录窗口
│       ├── qt_model_dialog.py — 启动时选择并下载模型
│       ├── qt_language.py   — 首次启动选择界面语言
│       ├── qt_workers.py    — 后台任务（模型、麦克风、网络）
│       ├── single_instance.py — 单实例运行锁
│       ├── app_icon.py      — 窗口图标和 exe 的 .ico
│       ├── i18n.py          — 翻译，locales/*.json
│       ├── models.py        — 注册表、下载、加载、完整性校验
│       ├── transcribe.py    — 音频与识别（文件 / 麦克风）
│       ├── config.py        — 用户设置
│       ├── devices.py       — 输入音频设备
│       ├── storage.py       — 识别历史（SQLite）
│       ├── postprocess.py   — 大小写与标点
│       ├── gui.py           — 备用的 tkinter 界面
│       └── console.py       — 控制台 UTF-8
├── packaging/
│   ├── VoxVault.spec        — PyInstaller 构建（onedir）
│   ├── launcher.py          — exe 入口 + --selftest
│   ├── build.py             — 构建、检查、发布用 zip
│   └── make_icon.py         — 生成 assets/VoxVault.ico
├── .github/workflows/       — ci.yml（测试+构建）、release.yml（打标签发布）
├── tests/                   — pytest
├── models/                  — VOSK 模型（输入，**不提交到 git**）
├── out_text/                — 转写文本（输出）
└── test/                    — 测试音频
```

模块依赖：`cli → (models, transcribe, config, devices, storage, gui*)`，
`transcribe → (models, postprocess)`，`config ↔ postprocess`（仅做取值校验）。
各模块之间没有循环依赖。

作为库使用：

```python
from pathlib import Path
from dictophone.transcribe import transcribe, iter_mic, transcribe_file
from dictophone.models import load_model
from dictophone.storage import Storage, Entry

result = transcribe(Path("audio.wav"), lang="ru", size="small")
print(result.text, result.audio_s, result.avg_conf)

model = load_model(lang="ru", size="small")
for event in iter_mic(model, device=None):      # 事件流
    print(event.kind, event.text)

with Storage() as db:
    db.add(Entry(kind="file", text=result.text, lang=result.lang))
```

## Windows 相关说明

- VOSK（C++/Kaldi）无法打开非 ASCII 路径下的文件。如果项目位于含西里尔字母的
  文件夹中（例如 `C:\work\диктофон`），加载模型时会在
  `%LOCALAPPDATA%\dictophone\vosk_ascii\<文件夹>_<哈希>` 自动创建目录联接
  （junction），并从该处加载模型。可用 `VOSK_ASCII_ROOT` 覆盖。
- 控制台会自动切换到 UTF-8，否则俄文会显示为乱码。
- mp3/m4a/ogg 需要 `ffmpeg`。
- 在已构建的版本中，模型和文本放在 **exe 旁边**；如果该文件夹不可写
  （例如安装在 `Program Files` 下），则改用 `%LOCALAPPDATA%\VoxVault`。

## 后续计划

- 神经网络标点/大小写（`vosk-recasepunc`）——`postprocess.set_backend()`
  扩展点已就绪，只缺后端实现。
- 发布验证通过后移除备用的 tkinter 界面（`gui.py`）。
- 改进自动语言检测（目前是基于平均置信度的启发式算法）。
- 支持断点续传下载模型（HTTP Range）。
