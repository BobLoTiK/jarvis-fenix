"""Управление памятью диалога.

«короткая память» → memory_max = 40, llm_context_messages = 10
«обычная память»  → 100 / 20
«долгая память»   → 200 / 40
"""

import re

from jarvis import memory


def memory_fast(handler, cmd: str) -> str | None:
    if re.search(r"(коротк|быстр)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 40,
            "llm_context_messages": 10,
        })
        return "Память: короткая. 40 сообщений, контекст LLM — 10."

    if re.search(r"(обычн|стандартн|нормальн)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 100,
            "llm_context_messages": 20,
        })
        return "Память: обычная. 100 сообщений, контекст LLM — 20."

    if re.search(r"(долг|глубок)\w*\s+память", cmd):
        handler.config.update({
            "memory_max": 200,
            "llm_context_messages": 40,
        })
        return "Память: долгая. 200 сообщений, контекст LLM — 40."

    if (re.search(r"(какая|текущ)\w*\s+память", cmd)
            or cmd in {"какая память", "текущая память"}):
        mm = handler.config.get("memory_max", 100)
        lc = handler.config.get("llm_context_messages", 20)
        return f"Память: {mm} сообщений, контекст LLM — {lc}."

    return None