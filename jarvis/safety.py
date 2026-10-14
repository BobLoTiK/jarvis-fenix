"""Постфильтр ответов LLM — вторая линия «красной черты».

Первая линия — промпт в brain.py («КРАСНАЯ ЧЕРТА»): это просьба к
модели, а не гарантия. Слабые модели (qwen2.5:0.5b/3b) её иногда
игнорируют, поэтому ответ проверяется ещё раз здесь — до озвучки.

    check_response(text)  — проверка строки: (ok, reason);
    guard_stream(chunks)  — обёртка стрима: начало придерживается до
                            проверки (STREAM_GUARD_CHARS).

Заблокированный ответ не озвучивается: в TTS уходит SAFE_REPLY, а в
лог (WARNING → jarvis.log / errors.log) — категория и текст.

Чего модуль НЕ делает:
    - не фильтрует мат (мат — не «красная черта»);
    - не гарантирует безопасность: это regex по списку формулировок,
      перефразировка его обойдёт. Промпт и фильтр работают в паре.
"""

import logging
import re
from typing import Iterable, Iterator

log = logging.getLogger("jarvis.safety")

# Сколько символов начала стрима держим до проверки. ~1–2 предложения:
# TTS стартует на доли секунды позже, зато запрещённое не прозвучит.
STREAM_GUARD_CHARS = 160

# Хвост предыдущего текста, перепроверяемый вместе со следующим чанком:
# ловит фразы, разорванные границей чанков («убей» | « себя»).
OVERLAP_CHARS = 32

SAFE_REPLY = "Не могу ответить на это, сэр."


# (регулярка, категория). Порядок важен: self_harm — раньше violence,
# иначе «убей себя» попадёт в «насилие».
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"убей\w*\s+себя|убейся|сдохни|удавись|"
            r"покончи\w*\s+с\s+собой|покончить\s+с\s+жизнью|"
            r"уйди\s+из\s+жизни|вскрой\s+вены|режь\s+вены",
            re.IGNORECASE,
        ),
        "self_harm",
    ),
    (
        re.compile(
            r"(убей|убить|убью|зарежь|прикончи|пристрели|застрели|"
            r"взорви|отрав[иь]|задуши)\w*\s+"
            r"(его|её|ее|их|людей|человека|себя)",
            re.IGNORECASE,
        ),
        "violence",
    ),
    (
        re.compile(
            r"взорв\w*\s+(школ\w*|больниц\w*|метро|поезд\w*|"
            r"торгов\w*\s+центр\w*)|"
            r"массов\w+\s+(убийств|расстрел)",
            re.IGNORECASE,
        ),
        "violence",
    ),
    (
        re.compile(
            r"(сделать|собрать|изготовить|смастерить|сколотить)\w*\s+"
            r"(бомб\w*|взрывчатк\w*|взрывчатое\w*|оруж\w*|гранат\w*|"
            r"самопальн\w+\s+оруж\w*)|"
            r"(рецепт|инструкц\w*|чертёж\w*)\s+"
            r"(бомб\w*|взрывчатк\w*)",
            re.IGNORECASE,
        ),
        "weapons",
    ),
    (
        re.compile(
            r"(сварить|синтезировать|изготовить|приготовить|сделать)\w*\s+"
            r"(метамфетамин\w*|амфетамин\w*|кокаин\w*|героин\w*|"
            r"мефедрон\w*|метадон\w*|лсд)|"
            r"(рецепт|инструкц\w*)\s+"
            r"(метамфетамин\w*|амфетамин\w*|кокаин\w*|героин\w*|"
            r"мефедрон\w*)",
            re.IGNORECASE,
        ),
        "drugs",
    ),
    (
        re.compile(
            r"(детск\w*|несовершеннолетн\w*|малолетн\w*)\s+"
            r"(порн\w*|секс\w*|эротик\w*|интим\w*)|"
            r"(порн\w*|секс\w*|эротик\w*)\s+(с\s+)?"
            r"(детьми|ребёнком|ребенком|малолетн\w*|"
            r"несовершеннолетн\w*)",
            re.IGNORECASE,
        ),
        "csam",
    ),
]


def check_response(text: str) -> tuple[bool, str]:
    """Проверяет ответ LLM.

    Возвращает:
        (True, "")  — ответ безопасен, можно озвучивать;
        (False, <категория>) — запрещённое, озвучивать нельзя.
    """
    if not text:
        return True, ""

    for pattern, category in FORBIDDEN_PATTERNS:
        if pattern.search(text):
            log.warning(
                "SAFETY: ответ заблокирован (категория=%s): %r",
                category,
                text[:200],
            )
            return False, category

    return True, ""


def guard_stream(chunks: Iterable[str], state: dict | None = None) -> Iterator[str]:
    """Обёртка стрима ответа: запрещённое не уходит в TTS.

    Первые STREAM_GUARD_CHARS символов придерживаются в буфере:

    * набрался порог и текст чист — буфер уходит на озвучку, дальше
      поток идёт как есть (каждый следующий чанк проверяется вместе с
      хвостом предыдущего — OVERLAP_CHARS);
    * в проверенном тексте запрещённое — в TTS уходит только
      SAFE_REPLY, остаток стрима отбрасывается;
    * стрим кончился раньше порога — проверяется то, что набралось.

    state (если передан) заполняется для вызывающего:
        state["text"]    — весь текст, прошедший через фильтр;
        state["blocked"] — True, если ответ заблокирован;
        state["reason"]  — категория блокировки.
    """
    held: list[str] = []
    held_len = 0
    full: list[str] = []
    tail = ""
    opened = False
    blocked = False
    reason = ""

    try:
        for chunk in chunks:
            if not chunk:
                continue
            full.append(chunk)

            if opened:
                ok, why = check_response(tail + chunk)
                if not ok:
                    blocked, reason = True, why
                    break
                tail = (tail + chunk)[-OVERLAP_CHARS:]
                yield chunk
                continue

            held.append(chunk)
            held_len += len(chunk)
            if held_len < STREAM_GUARD_CHARS:
                continue

            ok, why = check_response("".join(held))
            if not ok:
                blocked, reason = True, why
                break
            opened = True
            tail = "".join(held)[-OVERLAP_CHARS:]
            # Отдаём буфер по чанкам — границы чанков сохраняем как были.
            for piece in held:
                yield piece
            held = []

        if not opened and not blocked and held:
            ok, why = check_response("".join(held))
            if not ok:
                blocked, reason = True, why
            else:
                for piece in held:
                    yield piece

        if blocked:
            log.error("SAFETY: стрим прерван (категория=%s)", reason)
            yield SAFE_REPLY
    finally:
        if state is not None:
            state["text"] = "".join(full)
            state["blocked"] = blocked
            state["reason"] = reason
