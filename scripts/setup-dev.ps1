# Подготовка рабочей копии разработчика: зависимости + включённые хуки git.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
#
# Что делает:
#   1. ставит проект с extras [gui,dev] (тесты, линтеры, pre-commit);
#   2. `pre-commit install` — кладёт .git/hooks/pre-commit, и дальше
#      проверки качества запускаются на КАЖДЫЙ `git commit` локально;
#   3. прогоняет `pre-commit run --all-files`, чтобы сразу прогреть
#      изолированные окружения хуков и показать, есть ли нарушения.
#
# Повторный запуск безопасен: зависимости переустановятся, хук перезапишется.
param(
    [switch]$SkipInstall   # только включить хуки, без pip install
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

if (-not $SkipInstall) {
    Step "Ставлю зависимости (включая pre-commit)"
    python -m pip install --upgrade pip
    python -m pip install -e ".[gui,dev]"
} else {
    Step "Пропускаю установку зависимостей (-SkipInstall)"
}

Step "Включаю git-хуки (pre-commit install)"
python -m pre_commit install
if ($LASTEXITCODE -ne 0) {
    throw "pre-commit install не удался. Установи его: python -m pip install pre-commit"
}
if (-not (Test-Path ".git\hooks\pre-commit")) {
    throw "Файл .git\hooks\pre-commit не появился — хуки не включатся"
}

Step "Прогреваю окружения хуков и проверяю весь репозиторий"
python -m pre_commit run --all-files
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
    Write-Host "Готово: проверки (ruff, mypy, bandit) будут запускаться при каждом" -ForegroundColor Green
    Write-Host "git commit. Проверить всё заранее:  python -m pre_commit run --all-files"
} else {
    Write-Host "Проверки нашли замечания (код $code) — посмотрите вывод выше." -ForegroundColor Yellow
    Write-Host "Они же проверяются в CI, поэтому коммит с ними не пройдёт."
}
exit $code
