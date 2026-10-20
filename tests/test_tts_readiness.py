"""Bounded voice readiness and command release; no synthesis/audio devices."""
import threading
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from jarvis import tts
from jarvis.reply import Reply
from tests.test_recognition_quality import method


def pending_speaker():
    s=tts.Speaker.__new__(tts.Speaker)
    s._engine=None;s._engine_ready=Mock();s._init_engine=Mock(side_effect=AssertionError('second initialization'))
    return s

@pytest.mark.parametrize('timeout,expected',[(-1,0),(0,0),(.01,.01),(100,60)])
def test_readiness_is_bounded_and_never_reinitializes(timeout,expected):
    s=pending_speaker()
    assert not s._ensure_engine(timeout)
    s._engine_ready.wait.assert_called_once_with(expected)
    s._init_engine.assert_not_called()


def test_play_declines_without_spawning_worker():
    s=pending_speaker()
    s.stop=Mock(side_effect=AssertionError('should not start'))
    assert s.play_async('Готово') is False
    s._engine_ready.wait.assert_called_once_with(1.0)


def test_ready_engine_does_not_wait():
    s=pending_speaker();s._engine=object()
    assert s._ensure_engine()
    s._engine_ready.wait.assert_not_called()


def test_live_switch_does_not_wait_behind_loader():
    s=pending_speaker();s._init_lock=threading.Lock();s._init_lock.acquire()
    try:assert not s._recreate_engine()
    finally:s._init_lock.release()


def test_pending_real_background_loader_does_not_start_again(monkeypatch):
    started=threading.Event();release=threading.Event();calls=[]
    def get_engine(*a):
        calls.append(a);started.set();release.wait(3);return None
    monkeypatch.setattr(tts,'get_engine',get_engine)
    s=tts.Speaker({},lazy=True)
    try:
        assert started.wait(1)
        assert not s._ensure_engine(.01)
        assert len(calls)==1
    finally:
        release.set();assert s._engine_ready.wait(2)


def core(speaker):
    c=NS(speaker=speaker,gui=Mock(),listener=NS(muted=False,flush=Mock()),barge_enabled=False,_say_lock=threading.RLock())
    c._say_text=method('jarvis/main.py','Jarvis','_say_text',safety=NS(check_response=lambda t:(True,''),SAFE_REPLY='safe')).__get__(c)
    c._say_locked=method('jarvis/main.py','Jarvis','_say_locked').__get__(c)
    c.say=method('jarvis/main.py','Jarvis','say').__get__(c)
    return c


def test_unready_voice_releases_state_and_next_command():
    speaker=NS(play_async=Mock(return_value=False))
    c=core(speaker)
    assert c.say(Reply(text='Открываю')) is False
    assert c.say(Reply(text='Следующая команда')) is False
    assert speaker.play_async.call_count==2
    assert c.gui.set_state.call_args.args==('idle',)
    assert not c.listener.muted
    assert c.listener.flush.call_count==2


def test_stop_breaks_wait_even_if_native_worker_still_alive():
    s=NS(play_async=Mock(return_value=True),is_playing=lambda:True,stop_requested=lambda:True,wait_end=Mock())
    c=core(s);c.say(Reply(text='Ответ'))
    s.wait_end.assert_called_once_with(timeout=2.0)
    assert c.gui.set_state.call_args.args==('idle',)


def test_plain_reply_deadline_stops_worker():
    clock=NS(monotonic=Mock(side_effect=[0,121]),sleep=Mock())
    s=NS(play_async=Mock(return_value=True),is_playing=lambda:True,stop_requested=lambda:False,wait_end=Mock(),stop=Mock())
    c=core(s)
    fn=method('jarvis/main.py','Jarvis','_say_text',safety=NS(check_response=lambda t:(True,'')),time=clock)
    fn(c,'Ответ');s.stop.assert_called_once();s.wait_end.assert_called_once_with(timeout=2.0)


def test_busy_old_worker_does_not_start_new_playback(monkeypatch):
    s=pending_speaker();s._engine=object();s.stop=Mock();s.wait_end=Mock(return_value=False)
    assert s.play_async('Новый ответ') is False
    s.wait_end.assert_called_once_with(timeout=2.0)
