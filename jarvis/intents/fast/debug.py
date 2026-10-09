"""Диагностика: «что ты слышал», «почему не понял»."""

import re


def debug_fast(handler, cmd: str) -> str | None:
    # «что ты слышал»
    if (re.search(r"(что|чё)\s+ты\s+слышал", cmd)
            or cmd in {"что ты слышал", "что слышал", "история"}):
        phrases = []
        if handler.listener is not None and hasattr(handler.listener, "recent_phrases"):
            phrases = list(handler.listener.recent_phrases)
        if not phrases:
            phrases = list(handler._recent_phrases)
        if not phrases:
            return "Пока ничего не слышал."
        lines = [f"{i+1}. {p}" for i, p in enumerate(phrases[-5:])]
        return "Последние фразы: " + "; ".join(lines) + "."

    # «почему не понял»
    if (re.search(r"почему\s+(ты\s+)?не\s+понял", cmd)
            or cmd in {"почему не понял", "почему не поняла"}):
        d = handler._last_debug
        if not d:
            return "Пока нечего диагностировать."
        parts = [f"Фраза: «{d.get('cmd', '?')}»"]
        parts.append(f"Режим: {d.get('mode', '?')}")
        if d.get("llm"):
            intent = d.get("intent")
            if intent:
                parts.append(f"LLM вернула: {intent.get('action', '?')}")
            else:
                parts.append("LLM не разобрала")
        else:
            parts.append(f"LLM: {d.get('reason', 'выкл')}")
        return ". ".join(parts) + "."

    return None