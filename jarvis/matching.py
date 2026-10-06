"""Нечёткое сопоставление речи с названиями: транслитерация + difflib.

Vosk выдаёт только кириллицу («обс студио»), а программы называются латиницей
(«OBS Studio»), поэтому сравниваем и оригинал, и транслит.
"""

import re
from difflib import SequenceMatcher

_RU_DIGRAPHS = {"дж": "j"}  # фонетика: «джарвис» -> jarvis, а не dzharvis
_RU_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    text = text.lower()
    for ru, lat in _RU_DIGRAPHS.items():
        text = text.replace(ru, lat)
    return "".join(_RU_LAT.get(ch, ch) for ch in text)


_FOLD = str.maketrans({"c": "k", "q": "k", "w": "v", "x": "ks"})


def _fold(s: str) -> str:
    """Фонетическое выравнивание латиницы: Camo ~ камо(kamo), roblox ~ роблокс."""
    return s.replace("ph", "f").translate(_FOLD)


_NUM = {"ноль": "0", "один": "1", "одна": "1", "два": "2", "две": "2", "три": "3",
        "четыре": "4", "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
        "девять": "9", "десять": "10"}


def _num_norm(s: str) -> str:
    """«дота два» -> «дота 2»: в названиях номера всегда цифрами."""
    return " ".join(_NUM.get(w, w) for w in s.split())


def wake_score(token: str, wake_word: str) -> float:
    """Строгая похожесть для wake-слова.

    №94: убраны лишние сравнения. Раньше было 4 сравнения через
    set comprehension, включая бессмысленное token vs token-транслит.
    Теперь — 4 явных сравнения, семантика ясная:
        token ~ wake
        translit(token) ~ translit(wake)
        token ~ translit(wake)
        translit(token) ~ wake
    """
    if not token or not wake_word:
        return 0.0
    tok = token.lower()
    wake = wake_word.lower()
    tok_t = translit(tok)
    wake_t = translit(wake)
    return max(
        SequenceMatcher(None, tok, wake).ratio(),
        SequenceMatcher(None, tok_t, wake_t).ratio(),
        SequenceMatcher(None, tok, wake_t).ratio(),
        SequenceMatcher(None, tok_t, wake).ratio(),
    )


def _skeleton(s: str) -> str:
    """Согласный скелет: stim/steam -> stm. Гласные между языками плавают,
    согласные при транслитерации сохраняются."""
    return re.sub(r"[aeiouy\s]", "", translit(s))


def match_score(spoken: str, candidate: str) -> float:
    """Похожесть сказанного на название (0..1). Оба сравниваются в нижнем регистре,
    сказанное — ещё и в транслите; пробуем целиком, без пробелов и по словам."""
    cand = re.sub(r"\(.*?\)", " ", candidate.lower()).strip()
    cand = re.sub(r"\s+", " ", cand)
    if not spoken or not cand:
        return 0.0
    spoken = _num_norm(spoken)
    cand = _num_norm(cand)

    len_spoken = len(spoken.replace(" ", ""))

    best = 0.0
    for s in {spoken, _fold(translit(spoken))}:
        for c in {cand, _fold(translit(cand))}:
            if s == c:
                return 1.0
            if len(s) >= 5 and (s in c or c in s):
                best = max(best, 0.9)
            best = max(best, SequenceMatcher(None, s, c).ratio())
            best = max(best, SequenceMatcher(None, s.replace(" ", ""), c.replace(" ", "")).ratio())
            s_words, c_words = s.split(), c.split()
            for word in c_words:
                best = max(best, SequenceMatcher(None, s, word).ratio())
            if len(s_words) > 1 and c_words:
                avg = sum(
                    max(SequenceMatcher(None, sw, cw).ratio() for cw in c_words)
                    for sw in s_words
                ) / len(s_words)
                best = max(best, avg)
    sk_s, sk_c = _skeleton(spoken), _skeleton(cand)
    if len(sk_s) >= 3 and sk_s == sk_c:
        best = max(best, 0.8)

    if len_spoken < 4 and best < 0.85:
        return 0.0

    return best