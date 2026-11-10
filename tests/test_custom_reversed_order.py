"""Свои команды с обратным порядком слов (commands_reversed_order)."""

from jarvis.intents.fast.custom import find_custom


def _entry(phrase: str):
    return ([phrase], "открыть", "Выполняю.")


def test_reversed_order_matches_when_words_are_rearranged():
    custom = [_entry("включи ночной режим сети")]
    # Перестановка четырёх слов: обычная нечёткая сверка ниже порога 0.85.
    heard = "сети режим ночной включи"
    assert find_custom(custom, heard) is None
    assert find_custom(custom, heard, reversed_order=True) is not None


def test_reversed_order_does_not_match_other_words():
    custom = [_entry("включи ночной режим сети")]
    # Другой набор слов: совпадения нет даже при сравнении по сортировке.
    assert find_custom(custom, "открой корзину и папку", reversed_order=True) is None


def test_reversed_order_requires_all_words():
    custom = [_entry("включи ночной режим сети")]
    # Пропущено слово — отсортированные фразы слишком разные для порога 0.85.
    assert find_custom(custom, "сети режим включи", reversed_order=True) is None


def test_reversed_order_keeps_plain_fuzzy_behavior():
    custom = [_entry("открой калькулятор сейчас")]
    # Обычное нечёткое совпадение работает и без флага.
    assert find_custom(custom, "открой калькулятор сейчаc") is not None


def test_reversed_order_ignores_exact_builder_entries():
    exact = (["включи ночной режим сети"], ["открыть"], "", {"exact": True})
    assert find_custom([exact], "сети режим ночной включи",
                       reversed_order=True) is None


def test_reversed_order_skips_short_phrases():
    custom = [_entry("открой свет")]
    # Меньше 12 символов — нечёткие пороги не применяются вовсе.
    assert find_custom(custom, "свет открой", reversed_order=True) is None
