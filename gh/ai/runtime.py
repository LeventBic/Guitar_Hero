"""Model dosyalari ve onnxruntime oturumlari.

Modeller `assets/models/` altindadir (PyInstaller datas ile exe'ye girer):
  htdemucs_6s.onnx      Demucs v4 htdemucs_6s (MIT, Meta) - STFT/iSTFT disarida, agirliklar fp16 saklanir
  basic_pitch_nmp.onnx  Spotify basic-pitch ICASSP 2022 modeli (Apache-2.0)
Uretim: tools/export_models.py (yalniz gelistirme ortaminda torch gerekir).
"""
from __future__ import annotations

import os
import threading

DEMUCS_FILE = "htdemucs_6s.onnx"
BASIC_PITCH_FILE = "basic_pitch_nmp.onnx"

_lock = threading.Lock()
_sessions: dict[tuple[str, int], object] = {}


class Cancelled(Exception):
    """Kullanici islemi iptal etti (Esc)."""


def check_cancel(cancel) -> None:
    """cancel: None | threading.Event | cagrilabilir -> True ise Cancelled firlat."""
    if cancel is None:
        return
    flag = cancel.is_set() if hasattr(cancel, "is_set") else bool(cancel())
    if flag:
        raise Cancelled()


def models_dir() -> str:
    env = os.environ.get("RIFF_MODELS_DIR")
    if env:
        return env
    from ..config import resource_root
    return os.path.join(resource_root(), "assets", "models")


def model_path(name: str) -> str:
    return os.path.join(models_dir(), name)


def models_available() -> tuple[bool, str]:
    """(kullanilabilir mi, neden degil). Model dosyalari + onnxruntime."""
    for f in (DEMUCS_FILE, BASIC_PITCH_FILE):
        if not os.path.isfile(model_path(f)):
            return False, f"model file missing: {f}"
    try:
        import onnxruntime  # noqa: F401
    except Exception as exc:  # pragma: no cover - paket eksik / DLL yuklenemedi
        return False, f"onnxruntime unavailable: {exc}"
    return True, ""


def default_threads() -> int:
    """Fiziksel cekirdek sayisi tahmini (SMT'de mantiksal/2); arayuz icin bir cekirdek bos kalir."""
    n = os.cpu_count() or 4
    phys = n // 2 if n >= 8 else n
    return max(1, min(16, phys))


def session(name: str, threads: int | None = None):
    """Onbellekli onnxruntime.InferenceSession (CPU)."""
    import onnxruntime as ort
    threads = threads or default_threads()
    key = (name, threads)
    with _lock:
        s = _sessions.get(key)
        if s is not None:
            return s
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.log_severity_level = 3
        # bosta donen is parcaciklari arayuz is parcacigindan CPU calmasin
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        s = ort.InferenceSession(model_path(name), sess_options=so, providers=["CPUExecutionProvider"])
        _sessions[key] = s
        return s


def release_sessions() -> None:
    with _lock:
        _sessions.clear()
