# -*- coding: utf-8 -*-
"""Дизайн-токены: шкала, поверхности и измеряемый контраст палитр."""
import flet as ft
import pytest
from jarvis import gui as module
from jarvis import gui_tokens as T


def test_space_scale_is_short_and_ordered():
    values = list(T.SPACE.values())
    assert values == sorted(values)
    assert all(value % 4 == 0 and 0 < value <= 48 for value in values)
    assert T.SPACE["xs"] < T.SPACE["md"] < T.SPACE["xxl"]


def test_radius_scale_grows_from_sm_to_pill():
    assert T.RADIUS["sm"] < T.RADIUS["md"] < T.RADIUS["lg"] < T.RADIUS["pill"]
    assert T.RADIUS["sm"] >= 6


def test_type_roles_shrink_from_display_to_caption():
    sizes = [spec["size"] for spec in T.TYPE.values()]
    assert sizes == sorted(sizes, reverse=True)
    assert len(set(sizes)) == len(sizes)
    assert T.TYPE["display"]["size"] <= 34 and T.TYPE["caption"]["size"] >= 10
    for spec in T.TYPE.values():
        assert isinstance(spec["weight"], ft.FontWeight)


def test_text_builder_uses_role_and_allows_overrides():
    control = T.text("title", "Привет", color="#123456")
    assert isinstance(control, ft.Text)
    assert control.value == "Привет"
    assert control.size == T.TYPE["title"]["size"]
    assert control.weight == T.TYPE["title"]["weight"]
    assert control.color == "#123456"
    assert T.text("body", "x", color="#000000", italic=True).italic is True
    assert T.text("неизвестная роль", "x", color="#000000").size == T.TYPE["body"]["size"]


def test_card_and_pill_surfaces_use_palette():
    for name in ("dark", "light"):
        module._apply_palette(name)
        card = T.card(module.P)
        assert card.bgcolor == module.P.bg_card
        assert card.border_radius == T.RADIUS["md"]
        assert card.shadow is not None and card.border is not None
        assert T.card(module.P, border=False).border is None
        assert T.pill(module.P).border_radius == T.RADIUS["pill"]
        assert T.pill(module.P).bgcolor == module.P.sidebar
    module._apply_palette("dark")


@pytest.mark.parametrize("palette", ["dark", "light"])
def test_text_contrast_meets_wcag_on_both_palettes(palette):
    module._apply_palette(palette)
    p = module.P
    for background in (p.bg_main, p.bg_card):
        assert T.contrast(p.text, background) >= 4.5
        assert T.contrast(p.text_dim, background) >= 4.5
    assert T.contrast(p.brand, p.bg_card) >= 3.0
    assert T.contrast(p.error, p.bg_main) >= 3.0
    module._apply_palette("dark")


def test_unknown_color_is_rejected_instead_of_silently_zero():
    with pytest.raises(ValueError):
        T.contrast("не цвет", "#000000")
