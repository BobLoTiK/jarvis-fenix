"""Банк шуток: длина, уникальность и «колода» без повторов."""

import random

from jarvis import jokes


def test_jokes_are_short_and_single_line():
    for text in jokes.JOKES:
        assert isinstance(text, str) and text
        assert "\n" not in text
        assert len(text) <= 160, text
        assert text[-1] in ".!?"


def test_jokes_are_unique():
    assert len(set(jokes.JOKES)) == len(jokes.JOKES)


def test_deck_serves_every_joke_once_per_cycle():
    jokes.reset()
    served = [jokes.next_joke() for _ in range(len(jokes.JOKES))]
    assert sorted(served) == sorted(jokes.JOKES)


def test_deck_does_not_repeat_across_cycle_boundary():
    jokes.reset()
    served = [jokes.next_joke() for _ in range(len(jokes.JOKES) * 2)]
    assert all(left != right for left, right in zip(served, served[1:]))


def test_deck_is_deterministic_with_seeded_rng():
    jokes.reset()
    first = [jokes.next_joke(random.Random(7)) for _ in range(5)]
    jokes.reset()
    second = [jokes.next_joke(random.Random(7)) for _ in range(5)]
    assert first == second
