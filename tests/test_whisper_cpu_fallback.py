"""CUDA iterator failure -> same locally cached CPU model -> unchanged quality gate."""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from jarvis import stt, paths
from tests.test_recognition_quality import PCM,segment


def transcriber(tmp_path):
    w=stt.WhisperTranscriber.__new__(stt.WhisperTranscriber)
    w._infer_lock=threading.RLock();w._active_device='cuda';w._active_model_name='deepdml/cached-model'
    w._config={};w._load_error=None;w._loading=False;w._loaded=threading.Event()
    def broken(*a,**k):
        def iterator():
            raise RuntimeError('Library cublas64_12.dll is not found or cannot be loaded')
            yield
        return iterator(),None
    w._model=NS(transcribe=broken)
    return w


def models(monkeypatch,tmp_path,segments=None,fail=False):
    download=Mock(return_value=str(tmp_path/'cached'))
    cpu=NS(transcribe=Mock(side_effect=RuntimeError('CPU failure')) if fail else Mock(return_value=(iter(segments or [segment()]),None)))
    constructor=Mock(return_value=cpu)
    monkeypatch.setitem(sys.modules,'faster_whisper',NS(WhisperModel=constructor))
    monkeypatch.setitem(sys.modules,'faster_whisper.utils',NS(download_model=download))
    monkeypatch.setattr(paths,'program_whisper_cache_dir',lambda:tmp_path/'cache')
    return download,constructor,cpu


def test_cuda_encode_failure_retries_cpu_local_only(monkeypatch,tmp_path):
    w=transcriber(tmp_path);download,constructor,cpu=models(monkeypatch,tmp_path)
    assert w.transcribe(PCM)=='Открой блокнот'
    assert w.last_quality.accepted and w._active_device=='cpu'
    download.assert_called_once_with('deepdml/cached-model',cache_dir=str(tmp_path/'cache'),local_files_only=True)
    constructor.assert_called_once_with(str(tmp_path/'cached'),device='cpu',compute_type='int8',local_files_only=True)


def test_cpu_retry_does_not_relax_confidence(monkeypatch,tmp_path):
    w=transcriber(tmp_path);models(monkeypatch,tmp_path,[segment(avg_logprob=-3)])
    assert w.transcribe(PCM)=='' and not w.last_quality.accepted


def test_cpu_failure_disables_retry_in_this_session(monkeypatch,tmp_path):
    w=transcriber(tmp_path);download,constructor,cpu=models(monkeypatch,tmp_path,fail=True)
    with pytest.raises(RuntimeError,match='GPU и локальный CPU'):w.transcribe(PCM)
    assert w.last_quality is None and w._model is None and w._load_error
    with pytest.raises(RuntimeError):w.transcribe(PCM)
    assert constructor.call_count==1 and download.call_count==1


def test_cache_miss_does_not_request_online_download(monkeypatch,tmp_path):
    w=transcriber(tmp_path);download,constructor,cpu=models(monkeypatch,tmp_path)
    download.side_effect=FileNotFoundError('not cached')
    with pytest.raises(RuntimeError):w.transcribe(PCM)
    assert download.call_args.kwargs['local_files_only'] is True
    constructor.assert_not_called()


def test_explicit_model_directory_does_not_resolve_other_model(monkeypatch,tmp_path):
    w=transcriber(tmp_path);w._active_model_name=str(tmp_path)
    download,constructor,cpu=models(monkeypatch,tmp_path)
    assert w.transcribe(PCM)
    download.assert_not_called()
    assert constructor.call_args.args==(str(tmp_path),)


@pytest.mark.parametrize('device,message',[('cpu','cuda missing'),('cuda','unrelated decoder error')])
def test_unrelated_or_cpu_errors_not_hidden(monkeypatch,tmp_path,device,message):
    w=transcriber(tmp_path);w._active_device=device
    w._model=NS(transcribe=Mock(side_effect=RuntimeError(message)))
    retry=Mock();w._retry_on_cpu=retry
    with pytest.raises(RuntimeError,match=message):w.transcribe(PCM)
    retry.assert_not_called()


def test_pending_background_load_is_bounded(tmp_path):
    w=transcriber(tmp_path);w._model=None;w._loading=True;w._loaded=Mock();w._loaded.wait.return_value=False
    with pytest.raises(RuntimeError,match='готовится'):w._ensure_loaded()
    w._loaded.wait.assert_called_once_with(timeout=1.0)


def test_successful_cpu_model_is_reused_on_next_phrase(monkeypatch,tmp_path):
    w=transcriber(tmp_path);download,constructor,cpu=models(monkeypatch,tmp_path)
    cpu.transcribe.side_effect=lambda *a,**k:(iter([segment()]),None)
    assert w.transcribe(PCM) and w.transcribe(PCM)
    assert constructor.call_count==1 and download.call_count==1
    assert cpu.transcribe.call_count==2
