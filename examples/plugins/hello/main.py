"""Пример плагина Феникса: читает JSON из stdin, пишет JSON в stdout.

Запускается отдельным процессом: `python -I main.py` с рабочим каталогом
плагина. Ничего не пишет на диск и не ходит в сеть — только отвечает.
"""

import json
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        print(json.dumps({"error": "нужен JSON в stdin"}))
        return 0
    action = str(payload.get("command") or "")
    if action != "hello":
        print(json.dumps({"error": f"неизвестная команда: {action}"}))
        return 0
    phrase = str(payload.get("phrase") or "")
    print(json.dumps({"text": f"Плагин hello на связи (фраза: {phrase})."},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
