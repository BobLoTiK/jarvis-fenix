"""Executable Russian language corpus: understanding, morphology and speech.

No microphone, Windows desktop, network, user profile or LLM is needed.
The tests specify supported constructions rather than claiming full syntax parsing.
"""

from collections import deque
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import ast
import re
import time

import pytest

from jarvis.language import analyze_command
from jarvis.language.numbers import cardinal, roman_value, word_numbers
from jarvis.language.time import parse_duration
from jarvis.text_utils import prepare_text, normalize
from jarvis import memory, mood, timers
from jarvis.intents.handler import IntentHandler
from jarvis.intents.stages.fast import FastHandlersStage
from jarvis.intents.fast.timers import timers_fast
from jarvis.intents.fast.system import system_fast


def plain(text):
    return re.sub(r"\s+", " ", text.replace("ё", "е")).strip()


@pytest.mark.parametrize(
    "source,expected",
    [
        ("0", "ноль"),
        ("21 метр", "двадцать один метр"),
        ("с 21 метром", "с двадцатью одним метром"),
        ("к 21 участнику", "к двадцати одному участнику"),
        ("до 142 метров", "до ста сорока двух метров"),
        ("над 51 мостом", "над пятьюдесятью одним мостом"),
        ("1 мин", "одна минута"),
        ("2 мин", "две минуты"),
        ("5 мин", "пять минут"),
        ("5кг", "пять килограммов"),
        ("1 кг", "один килограмм"),
        ("2 кг", "два килограмма"),
        ("к 5 кг", "к пяти килограммам"),
        ("с 2026 метрами", "с двумя тысячами двадцатью шестью метрами"),
        ("1%", "один процент"),
        ("2%", "два процента"),
        ("5%", "пять процентов"),
        ("11%", "одиннадцать процентов"),
        ("21%", "двадцать один процент"),
        ("к 5%", "к пяти процентам"),
        ("1,5 кг", "одна целая пять десятых килограмма"),
        ("−3,5 °C", "минус три целых пять десятых градуса Цельсия"),
        ("к 3,5 кг", "к трем целым пяти десятым килограмма"),
        ("1 м²", "один квадратный метр"),
        ("2 м²", "два квадратных метра"),
        ("5 м³", "пять кубических метров"),
        ("5 м/с", "пять метров в секунду"),
        ("1 км/ч", "один километр в час"),
        ("2 МБ", "два мегабайта"),
        ("1234,50 ₽", "одна тысяча двести тридцать четыре рубля пятьдесят копеек"),
        ("2 руб.", "два рубля"),
        ("0,50 ₽", "ноль рублей пятьдесят копеек"),
        ("1/2", "одна вторая"),
        ("3/4", "три четвертых"),
        ("2+2=4", "два плюс два равно четыре"),
        ("3×4", "три умножить на четыре"),
        ("2 < 5", "два меньше чем пять"),
        ("5–7", "от пяти до семи"),
        ("в XXI веке", "в двадцать первом веке"),
        ("к XXI веку", "к двадцать первому веку"),
        ("Пётр I", "Петр первый"),
        ("о Петре I", "о Петре первом"),
        ("при Екатерине II", "при Екатерине второй"),
        ("в главе IV", "в главе четвертой"),
        ("в ⅩⅩⅠ веке", "в двадцать первом веке"),
        ("римское число XIV", "римское число четырнадцать"),
        ("к 21-му участнику", "к двадцать первому участнику"),
        ("в 21-м веке", "в двадцать первом веке"),
        ("15.10.2026", "пятнадцатое октября две тысячи двадцать шестого года"),
        ("до 15.10.2026", "до пятнадцатого октября две тысячи двадцать шестого года"),
        ("2026-10-15", "пятнадцатое октября две тысячи двадцать шестого года"),
        ("в 2026 году", "в две тысячи двадцать шестом году"),
        ("в 2026 г.", "в две тысячи двадцать шестом году"),
        ("в 18:30", "в восемнадцать часов тридцать минут"),
        ("в 1:01", "в один час одну минуту"),
        ("код 0012", "код ноль ноль один два"),
        ("Python 3.11", "Python три точка один один"),
        ("версия 1.2.3", "версия один точка два точка три"),
        ("## Ответ\n**5 кг**", "Ответ пять килограммов"),
        ("[сайт](https://example.org)", "сайт"),
        ("Я к Петру. 21 метр", "Я к Петру. двадцать один метр"),
    ],
)
def test_speech_corpus(source, expected):
    assert plain(prepare_text(source)) == plain(expected)
    assert plain(prepare_text(prepare_text(source))) == plain(expected)


@pytest.mark.parametrize(
    "text", ["MIX", "CIVIL", "VS Code", "Final Fantasy VII", "USB-C", "README.md"]
)
def test_non_numeric_names_are_not_roman_numbers(text):
    assert prepare_text(text) == text


@pytest.mark.parametrize(
    "token,value",
    [
        ("I", 1),
        ("IV", 4),
        ("XIV", 14),
        ("MCMXCIV", 1994),
        ("MMMCMXCIX", 3999),
        ("ⅩⅩⅠ", 21),
        ("IIII", None),
        ("IC", None),
        ("CIVIL", None),
        ("mix", None),
    ],
)
def test_roman_validation(token, value):
    assert roman_value(token) == value


@pytest.mark.parametrize(
    "text,value,kind",
    [
        ("двадцать одна", 21, "cardinal"),
        ("двадцатью одним", 21, "cardinal"),
        ("ста сорока двух", 142, "cardinal"),
        ("двести пятьдесят шесть", 256, "cardinal"),
        ("две тысячи двадцать шестого", 2026, "ordinal"),
        ("двухтысячного", 2000, "ordinal"),
        ("минус пять", -5, "cardinal"),
        ("три целых пять десятых", Decimal("3.5"), "cardinal"),
        ("ноль целых пять сотых", Decimal("0.05"), "cardinal"),
        ("полтора", Decimal("1.5"), "cardinal"),
    ],
)
def test_numeric_lexicon(text, value, kind):
    entities = list(word_numbers(text))
    assert len(entities) == 1
    n = entities[0]
    assert (n.value, n.kind, n.source) == (Decimal(value), kind, text)
    assert text[n.start : n.end] == text


@pytest.mark.parametrize("case", ["nomn", "gent", "datv", "accs", "ablt", "loct"])
@pytest.mark.parametrize("value", [0, 1, 2, 21, 42, 101, 142, 999, 1000, 2026, 120034])
def test_cardinal_roundtrip(value, case):
    spoken = cardinal(value, case)
    entities = list(word_numbers(spoken))
    assert len(entities) == 1 and entities[0].value == value


@pytest.mark.parametrize(
    "source,expected",
    [
        ("громкость пятьдесят пять процентов", "громкость 55 процентов"),
        ("яркость на девяносто девять", "яркость на 99"),
        ("сделай на двадцать пять потише", "сделай на 25 потише"),
        (
            "напомни через двадцать одну минуту выпить чай",
            "напомни через 1260 секунд выпить чай",
        ),
        (
            "напомни через полтора часа выпить чай",
            "напомни через 5400 секунд выпить чай",
        ),
        ("напомни через 1,5 часа выпить чай", "напомни через 5400 секунд выпить чай"),
        ("таймер на один час и тридцать минут", "таймер через 5400 секунд"),
        (
            "напомни в половине седьмого вечера позвонить маме",
            "напомни в 18:30 позвонить маме",
        ),
        (
            "напомни в восемнадцать часов тридцать минут позвонить маме",
            "напомни в 18:30 позвонить маме",
        ),
        ("напомни в семь вечера позвонить маме", "напомни в 19:00 позвонить маме"),
        ("напомни в 18:30 позвонить маме", "напомни в 18:30 позвонить маме"),
        ("расскажи о Петре I", "расскажи о Петре первом"),
    ],
)
def test_input_corpus(source, expected):
    result = analyze_command(source)
    assert result.issue is None
    assert result.command == expected
    assert result.original == source


@pytest.mark.parametrize(
    "text",
    [
        "Первый канал",
        "открой Первый канал",
        "открой Final Fantasy VII",
        "добавь в список купить двадцать один метр кабеля",
        "напиши три плюс пять",
        "запомни код двадцать один",
        "добавь в список купить таймер на двадцать минут",
    ],
)
def test_payloads_are_not_rewritten(text):
    assert analyze_command(text).command == text


@pytest.mark.parametrize(
    "text",
    [
        "громкость минус пять",
        "яркость сто один",
        "громкость 3,5",
        "громкость три целых пять десятых процента",
        "напомни через минус пять минут",
        "таймер на ноль секунд",
        "напомни в половине седьмого позвонить маме",
        "напомни в двадцать пять часов позвонить маме",
        "напомни в 25:99 позвонить маме",
    ],
)
def test_invalid_or_ambiguous_commands_require_clarification(text):
    assert analyze_command(text).issue


@pytest.mark.parametrize(
    "text,seconds,body",
    [
        ("напомни через двадцать одну минуту выпить чай", 1260, "выпить чай"),
        ("напомни через две с половиной минуты проверить чай", 150, "проверить чай"),
        ("напомни через час с половиной проверить чай", 5400, "проверить чай"),
        ("таймер на один час и тридцать минут", 5400, ""),
        ("напомни через полчаса выпить чай", 1800, "выпить чай"),
        (
            "напомни через 5 минут проверить таймер через полчаса",
            300,
            "проверить таймер через полчаса",
        ),
    ],
)
def test_shared_duration_parser(text, seconds, body):
    assert timers._parse_duration(text) == seconds
    assert timers._extract_reminder_text(text) == body


def test_duration_not_taken_from_arbitrary_reminder_body():
    assert parse_duration("завтра зайти на 5 этаж") is None


def make_handler():
    h = IntentHandler.__new__(IntentHandler)
    h._pending_password = None
    h._pending_question = None
    h.mode = "combo"
    h._recent_phrases = deque(maxlen=10)
    h.dialog = deque(maxlen=100)
    h.config = {}
    h._pipeline = [FastHandlersStage()]
    h._fast_handlers_cache = [
        ("timer", lambda cmd: timers_fast(h, cmd)),
        ("system", lambda cmd: system_fast(h, cmd)),
    ]
    return h


def test_spoken_duration_reaches_real_handler_and_preserves_history():
    h = make_handler()
    source = "напомни через двадцать одну минуту выпить чай"
    with (
        patch.object(timers, "add", return_value={}) as add,
        patch.object(memory, "append"),
        patch.object(mood, "apply_from_text"),
    ):
        before = time.time()
        result = h.handle(source)
    text, fire_at = add.call_args.args
    assert text == "выпить чай"
    assert abs(fire_at - before - 1260) < 1
    assert h._raw_cmd == source
    assert h.dialog[0]["content"] == source
    assert result.text


def test_spoken_level_reaches_action():
    from jarvis import actions, history

    h = make_handler()
    with (
        patch.object(actions, "get_volume", return_value=20),
        patch.object(actions, "set_volume", return_value=True) as set_volume,
        patch.object(history, "push"),
        patch.object(memory, "append"),
        patch.object(mood, "apply_from_text"),
    ):
        h.handle("громкость пятьдесят пять процентов")
    set_volume.assert_called_once_with(55)


def test_password_never_enters_numeric_language_layer():
    h = make_handler()
    h.config = {"danger_password": "1234"}
    h._pending_password = {"intent": {}, "expires_at": time.time() + 30}
    with patch("jarvis.language.analyze_command") as analyze:
        h.handle("неверный пароль")
    analyze.assert_not_called()


def load_method(filename, classname, name, namespace):
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname
    )
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def test_wake_extraction_preserves_original_numeric_punctuation():
    method = load_method(
        "jarvis/main.py",
        "Jarvis",
        "_extract_command",
        {"time": time, "normalize": normalize},
    )
    app = SimpleNamespace(
        _wake_word_required=True, _awaiting_until=0, _is_wake=lambda s: s == "феникс"
    )
    assert method(app, "Феникс, напомни через 1,5 часа") == "напомни через 1,5 часа"


def test_whisper_refinement_preserves_original_numeric_punctuation():
    method = load_method(
        "jarvis/main.py",
        "Jarvis",
        "_refine",
        {"normalize": normalize, "log": Mock(), "_REJECT": object()},
    )
    app = SimpleNamespace(
        whisper=SimpleNamespace(
            transcribe=lambda _, **kw: "Феникс, напомни в 18:30",
            last_quality=SimpleNamespace(accepted=True),
        ),
        config={},
        _is_wake=lambda s: s == "феникс",
    )
    assert method(app, b"", True) == "напомни в 18:30"


def test_speaker_direct_path_uses_same_preparation():
    from jarvis.tts import Speaker

    speaker = Speaker.__new__(Speaker)
    speaker._ensure_engine = Mock(return_value=True)
    speaker._new_token = Mock(return_value=Mock())
    speaker._engine_name = "piper"
    speaker._engine = Mock()
    speaker._engine.synthesize.return_value = b""
    speaker.voice = "ruslan"
    speaker.rate = 1.0
    speaker.speak("в XXI веке")
    assert (
        plain(speaker._engine.synthesize.call_args.args[0]) == "в двадцать первом веке"
    )


@pytest.mark.parametrize(
    "source,expected",
    [
        ("при петре I", "при петре первом"),
        ("1,5 м²", "одна целая пять десятых квадратного метра"),
        ("±5 °C", "плюс-минус пять градусов Цельсия"),
        ("№ 21", "номер двадцать один"),
    ],
)
def test_additional_speech_cases(source, expected):
    assert plain(prepare_text(source)) == plain(expected)


@pytest.mark.parametrize(
    "source",
    [
        "громкость пятьдесят двадцать",
        "напомни через двадцать тридцать минут",
        "напомни через один час и минус тридцать минут",
    ],
)
def test_malformed_quantities_do_not_partially_execute(source):
    assert analyze_command(source).issue


def test_entities_include_contextual_roman_value():
    result = analyze_command("расскажи о Петре I")
    n = result.numbers[-1]
    assert n.kind == "ordinal" and n.value == 1 and n.source == "I"


def test_cardinal_does_not_cross_punctuation():
    values = list(word_numbers("двадцать, один"))
    assert [n.value for n in values] == [20, 1]


def test_large_numbers_do_not_break_tts():
    assert prepare_text("в 9999999999999999 веке")


def test_speaker_async_path_uses_same_preparation():
    from jarvis.tts import Speaker

    class ThreadNow:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    speaker = Speaker.__new__(Speaker)
    speaker._ensure_engine = Mock(return_value=True)
    speaker._new_token = Mock(return_value=SimpleNamespace(is_set=lambda: False))
    speaker.stop = Mock()
    speaker.wait_end = Mock(return_value=True)
    import threading

    speaker._play_lock = threading.Lock()
    speaker._playing = False
    speaker._engine_name = "piper"
    speaker._engine = Mock()
    speaker._engine.synthesize.return_value = b""
    speaker.voice = "ruslan"
    speaker.rate = 1.0
    with patch("jarvis.tts.threading.Thread", ThreadNow):
        speaker.play_async("в XXI веке")
    assert (
        plain(speaker._engine.synthesize.call_args.args[0]) == "в двадцать первом веке"
    )


@pytest.mark.parametrize("engine", ["piper", "silero", "sapi"])
def test_all_streaming_engines_use_shared_preparation(engine):
    path = (
        Path(__file__).resolve().parents[1]
        / "jarvis"
        / "tts_engines"
        / (engine + ".py")
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    play = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef)
        and n.name == ("_say" if engine == "sapi" else "_play")
    )
    assert any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "prepare_text"
        for n in ast.walk(play)
    )


def test_written_and_spoken_roman_queries_match():
    assert normalize(analyze_command("расскажи о Петре I").command) == normalize(
        analyze_command("расскажи о Петре первом").command
    )
    result = analyze_command("римское число XIV")
    assert result.command == "римское число четырнадцать"
    assert result.numbers[-1].kind == "cardinal"


def test_spoken_clock_reaches_real_timer_handler():
    h = make_handler()
    with (
        patch.object(timers, "add", return_value={}) as add,
        patch.object(memory, "append"),
        patch.object(mood, "apply_from_text"),
    ):
        h.handle("напомни в половине седьмого вечера позвонить маме")
    text, fire_at = add.call_args.args
    import datetime

    clock = datetime.datetime.fromtimestamp(fire_at)
    assert (clock.hour, clock.minute, text) == (18, 30, "позвонить маме")


def test_compound_commands_preserve_decimal_comma():
    from jarvis import actions, history
    from jarvis.intents.stages.compound import CompoundStage

    h = make_handler()
    h._pipeline = [CompoundStage(), FastHandlersStage()]
    with (
        patch.object(actions, "get_volume", return_value=10),
        patch.object(actions, "set_volume", return_value=True) as set_volume,
        patch.object(history, "push"),
        patch.object(timers, "add", return_value={}) as add,
        patch.object(memory, "append"),
        patch.object(mood, "apply_from_text"),
    ):
        before = time.time()
        h.handle("поставь громкость двадцать, напомни через 1,5 часа выпить чай")
    set_volume.assert_called_once_with(20)
    assert add.call_args.args[0] == "выпить чай"
    assert abs(add.call_args.args[1] - before - 5400) < 1


def test_standalone_negative_survives_wake_extraction():
    method = load_method(
        "jarvis/main.py",
        "Jarvis",
        "_extract_command",
        {"time": time, "normalize": normalize},
    )
    app = SimpleNamespace(
        _wake_word_required=True, _awaiting_until=0, _is_wake=lambda s: s == "феникс"
    )
    assert method(app, "Феникс, -5") == "-5"
