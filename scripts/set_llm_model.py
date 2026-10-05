"""Устанавливает llm_model в config.json.

Используется из install.bat после выбора модели.

Запуск:
    python scripts/set_llm_model.py qwen2.5:7b-instruct
"""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CONFIG = BASE / "config.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("Использование: python scripts/set_llm_model.py <model_name>")
        return 1

    model = sys.argv[1].strip()
    if not model:
        print("Пустое имя модели")
        return 1

    data = {}
    if CONFIG.exists():
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Не удалось прочитать config.json: {e}")
            return 1

    old = data.get("llm_model")
    data["llm_model"] = model
    CONFIG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"llm_model: {old} -> {model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())