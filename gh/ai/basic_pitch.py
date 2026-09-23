"""Polifonik nota cikarimi: Spotify basic-pitch (ICASSP 2022 "nmp" modeli) onnxruntime ile + numpy son isleme.

Bu dosyanin pencereleme (window_audio / unwrap_output), zaman ekseni (model_frames_to_time) ve nota olusturma
(get_infered_onsets, output_to_notes_polyphonic) kisimlari basic-pitch 0.4.0 kaynak kodundan
(basic_pitch/inference.py, basic_pitch/note_creation.py) numpy'a uyarlanmistir; scipy / librosa / tensorflow
kullanilmaz (scipy.signal.argrelmax yerine esdeger numpy karsilastirmasi).

    Copyright 2022 Spotify AB

    Licensed under the Apache License, Version 2.0 (the "License");
    you may not use this file except in compliance with the License.
    You may obtain a copy of the License at

        http://www.apache.org/licenses/LICENSE-2.0

    Unless required by applicable law or agreed to in writing, software
    distributed under the License is distributed on an "AS IS" BASIS,
    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    See the License for the specific language governing permissions and
    limitations under the License.

Degisiklikler (RIFF): numpy'a tasima, toplu (batch) model cagrisi, iptal/ilerleme geri cagrilari, NoteEvent sinifi.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .runtime import BASIC_PITCH_FILE, check_cancel, session

AUDIO_SAMPLE_RATE = 22050
FFT_HOP = 256
ANNOTATIONS_FPS = AUDIO_SAMPLE_RATE // FFT_HOP            # 86 (tam sayi, orijinaldeki gibi)
AUDIO_N_SAMPLES = AUDIO_SAMPLE_RATE * 2 - FFT_HOP          # 43844
ANNOT_N_FRAMES = ANNOTATIONS_FPS * 2                       # 172
N_OVERLAPPING_FRAMES = 30
OVERLAP_LEN = N_OVERLAPPING_FRAMES * FFT_HOP               # 7680
HOP_SIZE = AUDIO_N_SAMPLES - OVERLAP_LEN                   # 36164
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87
IN_NAME = "serving_default_input_2:0"
OUT_NAMES = ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2", "StatefulPartitionedCall:0"]  # note, onset, contour

# basic_pitch.inference.predict varsayilanlari
ONSET_THRESH = 0.5
FRAME_THRESH = 0.3
MIN_NOTE_LEN = 11            # int(round(127.70 ms * 86.13 kare/s))
ENERGY_TOL = 11


@dataclass
class NoteEvent:
    start: float          # s
    end: float            # s
    pitch: int            # midi
    amplitude: float      # 0..1 (kare aktivasyonu ortalamasi)
    onset: bool = True    # False: melodia hilesiyle (onset tepesi olmadan) bulunan nota

    @property
    def duration(self) -> float:
        return self.end - self.start


# --------------------------------------------------------------------------- model

def window_audio(audio: np.ndarray) -> np.ndarray:
    """get_audio_input + window_audio_file: basa overlap/2 sifir, HOP_SIZE adimli AUDIO_N_SAMPLES pencereler.
    (pencere, AUDIO_N_SAMPLES, 1) float32."""
    a = np.concatenate([np.zeros(OVERLAP_LEN // 2, dtype=np.float32), np.asarray(audio, dtype=np.float32)])
    starts = list(range(0, a.shape[0], HOP_SIZE))
    out = np.zeros((len(starts), AUDIO_N_SAMPLES, 1), dtype=np.float32)
    for k, i in enumerate(starts):
        w = a[i:i + AUDIO_N_SAMPLES]
        out[k, :w.size, 0] = w
    return out


def unwrap_output(output: np.ndarray, audio_original_length: int) -> np.ndarray:
    """(pencere, 172, f) -> (kare, f): her pencerenin basindan/sonundan yarim ortusme atilir."""
    n_olap = N_OVERLAPPING_FRAMES // 2
    if n_olap > 0:
        output = output[:, n_olap:-n_olap, :]
    n_orig = int(np.floor(audio_original_length * (ANNOTATIONS_FPS / AUDIO_SAMPLE_RATE)))
    return output.reshape(-1, output.shape[2])[:n_orig, :]


def run_model(audio22k: np.ndarray, *, progress=None, cancel=None, batch: int = 8,
              threads: int | None = None) -> dict[str, np.ndarray]:
    """22.05 kHz mono ses -> {'note': (T,88), 'onset': (T,88), 'contour': (T,264)}."""
    sess = session(BASIC_PITCH_FILE, threads)
    wins = window_audio(audio22k)
    outs: dict[str, list] = {"note": [], "onset": [], "contour": []}
    for s in range(0, wins.shape[0], batch):
        check_cancel(cancel)
        note, onset, contour = sess.run(OUT_NAMES, {IN_NAME: wins[s:s + batch]})
        outs["note"].append(note)
        outs["onset"].append(onset)
        outs["contour"].append(contour)
        if progress is not None:
            progress(min(1.0, (s + batch) / wins.shape[0]))
    n = int(np.asarray(audio22k).shape[0])
    return {k: unwrap_output(np.concatenate(v), n) for k, v in outs.items()}


def model_frames_to_time(n_frames: int) -> np.ndarray:
    original_times = np.arange(n_frames) * FFT_HOP / AUDIO_SAMPLE_RATE
    window_numbers = np.floor(np.arange(n_frames) / ANNOT_N_FRAMES)
    window_offset = (FFT_HOP / AUDIO_SAMPLE_RATE) * (ANNOT_N_FRAMES - (AUDIO_N_SAMPLES / FFT_HOP)) + 0.0018
    return original_times - (window_offset * window_numbers)


# --------------------------------------------------------------------------- nota olusturma

def argrelmax_axis0(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """scipy.signal.argrelmax(x, axis=0) (order=1, mode='clip'): kenarlar hic tepe olmaz."""
    if x.shape[0] < 3:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    c = x[1:-1]
    mask = (c > x[:-2]) & (c > x[2:])
    t, f = np.nonzero(mask)
    return t + 1, f


def get_infered_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    diffs = []
    for n in range(1, n_diff + 1):
        fa = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(fa[n:, :] - fa[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    mx = np.max(frame_diff)
    frame_diff = np.max(onsets) * frame_diff / mx if mx > 0 else frame_diff * 0.0
    return np.max([onsets, frame_diff], axis=0)


def constrain_frequency(onsets, frames, max_midi: float | None, min_midi: float | None):
    if max_midi is not None:
        i = int(np.round(max_midi - MIDI_OFFSET))
        onsets[:, max(i, 0):] = 0
        frames[:, max(i, 0):] = 0
    if min_midi is not None:
        i = int(np.round(min_midi - MIDI_OFFSET))
        onsets[:, :max(i, 0)] = 0
        frames[:, :max(i, 0)] = 0
    return onsets, frames


def output_to_notes_polyphonic(frames: np.ndarray, onsets: np.ndarray, onset_thresh: float = ONSET_THRESH,
                               frame_thresh: float = FRAME_THRESH, min_note_len: int = MIN_NOTE_LEN,
                               infer_onsets: bool = True, max_midi: float | None = None,
                               min_midi: float | None = None, melodia_trick: bool = True,
                               energy_tol: int = ENERGY_TOL) -> list[tuple[int, int, int, float, bool]]:
    """[(baslangic karesi, bitis karesi, midi, genlik, onset'li mi)] - basic-pitch ile ayni sira ve sonuc."""
    frames = np.array(frames, dtype=np.float64)
    onsets = np.array(onsets, dtype=np.float64)
    n_frames = frames.shape[0]
    onsets, frames = constrain_frequency(onsets, frames, max_midi, min_midi)
    if infer_onsets:
        onsets = get_infered_onsets(onsets, frames)
    peak_thresh_mat = np.zeros(onsets.shape)
    peaks = argrelmax_axis0(onsets)
    peak_thresh_mat[peaks] = onsets[peaks]
    onset_idx = np.where(peak_thresh_mat >= onset_thresh)
    onset_time_idx = onset_idx[0][::-1]
    onset_freq_idx = onset_idx[1][::-1]
    remaining = frames.copy()
    notes: list[tuple[int, int, int, float, bool]] = []
    for note_start_idx, freq_idx in zip(onset_time_idx.tolist(), onset_freq_idx.tolist()):
        if note_start_idx >= n_frames - 1:
            continue
        col = remaining[:, freq_idx]
        i = note_start_idx + 1
        k = 0
        while i < n_frames - 1 and k < energy_tol:
            if col[i] < frame_thresh:
                k += 1
            else:
                k = 0
            i += 1
        i -= k
        if i - note_start_idx <= min_note_len:
            continue
        remaining[note_start_idx:i, freq_idx] = 0
        if freq_idx < MAX_FREQ_IDX:
            remaining[note_start_idx:i, freq_idx + 1] = 0
        if freq_idx > 0:
            remaining[note_start_idx:i, freq_idx - 1] = 0
        amp = float(np.mean(frames[note_start_idx:i, freq_idx]))
        notes.append((note_start_idx, i, freq_idx + MIDI_OFFSET, amp, True))
    if melodia_trick:
        # orijinal: "while np.max(remaining) > frame_thresh: argmax(...)" - tek argmax ile ayni sonuc
        shape = remaining.shape
        while True:
            flat = int(np.argmax(remaining))
            i_mid, freq_idx = divmod(flat, shape[1])
            if remaining[i_mid, freq_idx] <= frame_thresh:
                break
            remaining[i_mid, freq_idx] = 0
            i = i_mid + 1
            k = 0
            while i < n_frames - 1 and k < energy_tol:
                if remaining[i, freq_idx] < frame_thresh:
                    k += 1
                else:
                    k = 0
                remaining[i, freq_idx] = 0
                if freq_idx < MAX_FREQ_IDX:
                    remaining[i, freq_idx + 1] = 0
                if freq_idx > 0:
                    remaining[i, freq_idx - 1] = 0
                i += 1
            i_end = i - 1 - k
            i = i_mid - 1
            k = 0
            while i > 0 and k < energy_tol:
                if remaining[i, freq_idx] < frame_thresh:
                    k += 1
                else:
                    k = 0
                remaining[i, freq_idx] = 0
                if freq_idx < MAX_FREQ_IDX:
                    remaining[i, freq_idx + 1] = 0
                if freq_idx > 0:
                    remaining[i, freq_idx - 1] = 0
                i -= 1
            i_start = i + 1 + k
            if i_end - i_start <= min_note_len:
                continue
            amp = float(np.mean(frames[i_start:i_end, freq_idx]))
            notes.append((i_start, i_end, freq_idx + MIDI_OFFSET, amp, False))
    return notes


def notes_from_output(output: dict[str, np.ndarray], **kw) -> list[NoteEvent]:
    """model_output_to_notes (pitch bend olmadan): saniye cinsinden, baslangica gore sirali."""
    frames = output["note"]
    raw = output_to_notes_polyphonic(frames, output["onset"], **kw)
    times = model_frames_to_time(frames.shape[0])
    ev = [NoteEvent(float(times[s]), float(times[e]), int(p), float(a), bool(o)) for s, e, p, a, o in raw]
    ev.sort(key=lambda n: (n.start, n.pitch))
    return ev


def transcribe(audio22k: np.ndarray, *, progress=None, cancel=None, threads: int | None = None,
               **kw) -> tuple[list[NoteEvent], dict[str, np.ndarray]]:
    out = run_model(audio22k, progress=progress, cancel=cancel, threads=threads)
    check_cancel(cancel)
    return notes_from_output(out, **kw), out
