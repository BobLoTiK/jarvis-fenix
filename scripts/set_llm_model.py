"""Устанавливает llm_model в config.json.

Используется из install.bat после выбора модели.

Запуск:
    python scripts/set_llm_model.py qwen2.5:7b-instruct

Путь к config.json берётся через jarvis.paths — то есть
%APPDATA%\\Phoenix\\config.json (USER_DIR), а не рядом с кодом.
Запись — атомарная, через config_manager.
"""

import sys
from pathlib import Path

# Достаём корень проекта, чтобы импортировать jarvis.*
BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from jarvis import config_manager  # noqa: E402
from jarvis import paths as _paths  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print("Использование: python scripts/set_llm_model.py <model_name>")
        return 1

    model = sys.argv[1].strip()
    if not model:
        print("Пустое имя модели")
        return 1

    config_path = _paths.config_path()

    data = config_manager.load(path=config_path)
    old = data.get("llm_model")
    data["llm_model"] = model

    ok = config_manager.save(data, path=config_path)
    if not ok:
        print(f"Не удалось записать {config_path}")
        return 1

    print(f"llm_model: {old} -> {model}")
    print(f"Файл: {config_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())