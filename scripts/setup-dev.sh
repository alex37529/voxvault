#!/usr/bin/env bash
# Подготовка рабочей копии разработчика: зависимости + включённые хуки git.
#
#   bash scripts/setup-dev.sh
#
# Что делает:
#   1. ставит проект с extras [gui,dev] (тесты, линтеры, pre-commit);
#   2. `pre-commit install` — кладёт .git/hooks/pre-commit, и дальше
#      проверки качества запускаются на КАЖДЫЙ `git commit` локально;
#   3. прогоняет `pre-commit run --all-files`, чтобы прогреть изолированные
#      окружения хуков и показать, есть ли нарушения.
#
# Повторный запуск безопасен. Аргументы: --skip-install (только хуки).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

step() { printf '\n==> %s\n' "$1"; }

if [ "${1:-}" != "--skip-install" ]; then
    step "Ставлю зависимости (включая pre-commit)"
    python -m pip install --upgrade pip
    python -m pip install -e ".[gui,dev]"
else
    step "Пропускаю установку зависимостей (--skip-install)"
fi

step "Включаю git-хуки (pre-commit install)"
python -m pre_commit install
test -f .git/hooks/pre-commit || {
    echo "Файл .git/hooks/pre-commit не появился — хуки не включатся" >&2
    exit 1
}

step "Прогреваю окружения хуков и проверяю весь репозиторий"
if python -m pre_commit run --all-files; then
    printf '\n%s\n' "Готово: проверки (ruff, mypy, bandit) будут запускаться при каждом git commit."
else
    printf '\n%s\n' "Проверки нашли замечания — посмотрите вывод выше." >&2
fi
