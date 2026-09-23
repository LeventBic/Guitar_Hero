"""GELISTIRME ARACI: gitar algilama modellerini assets/models/ altina ONNX olarak hazirla ve dogrula.

Oyun calisirken torch GEREKMEZ; bu betik yalniz ayri bir gelistirme ortaminda calisir:
    py -3.14 -m venv %LOCALAPPDATA%\\riff-dev\\export-venv
    <venv>\\Scripts\\pip install torch onnx onnxscript onnxruntime numpy soundfile julius einops pyyaml tqdm
    <venv>\\Scripts\\pip install --no-deps demucs openunmix basic-pitch
    <venv>\\Scripts\\python tools\\export_models.py [--verify]

1) Demucs htdemucs_6s (MIT, Meta/facebookresearch): agirliklar resmi adresten indirilir
   https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th (sha256 34c22ccb... onekli).
   Agin cekirdegi (normalizasyon + encoder/decoder + cross-transformer) ONNX'e aktarilir; STFT/iSTFT ve cac
   maskesi numpy'da (gh/ai/spec.py). Buyuk fp32 agirliklar fp16 saklanir + Cast (orijinal .th zaten fp16
   saklar -> dogruluk kaybi yok, dosya ~yari boy). Girdi: mix (1,2,343980), mag (1,4,2048,336);
   cikti: x (1,6,4,2048,336) frekans dali, xt (1,6,2,343980) zaman dali.
2) basic-pitch (Apache-2.0, Spotify): pip paketindeki saved_models/icassp_2022/nmp.onnx aynen kopyalanir.
--verify: gh.ai.demucs (numpy + onnxruntime) ciktisini demucs.apply.apply_model (torch) ile karsilastirir.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEMUCS_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
DEMUCS_SHA_PREFIX = "34c22ccb"
OUT_DIR = os.path.join(ROOT, "assets", "models")
CACHE = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "riff-dev", "weights")


def fetch_weights() -> str:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, os.path.basename(DEMUCS_URL))
    if not os.path.exists(path):
        print("downloading", DEMUCS_URL)
        urllib.request.urlretrieve(DEMUCS_URL, path)
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if not h.startswith(DEMUCS_SHA_PREFIX):
        raise SystemExit(f"checksum mismatch for {path}: {h}")
    return path


def load_demucs(path: str):
    from demucs.states import load_model
    m = load_model(path)
    m.eval()
    return m


def make_core(model):
    import torch
    from einops import rearrange

    class Core(torch.nn.Module):
        """HTDemucs.forward, _spec/_magnitude oncesi ve _mask/_ispec sonrasi haric (egitim uzunlugunda)."""

        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, mix, mag):
            m = self.m
            x = mag
            B, C, Fq, T = x.shape
            mean = x.mean(dim=(1, 2, 3), keepdim=True)
            std = x.std(dim=(1, 2, 3), keepdim=True)
            x = (x - mean) / (1e-5 + std)
            xt = mix
            meant = xt.mean(dim=(1, 2), keepdim=True)
            stdt = xt.std(dim=(1, 2), keepdim=True)
            xt = (xt - meant) / (1e-5 + stdt)
            saved, saved_t, lengths, lengths_t = [], [], [], []
            for idx, encode in enumerate(m.encoder):
                lengths.append(x.shape[-1])
                inject = None
                if idx < len(m.tencoder):
                    lengths_t.append(xt.shape[-1])
                    tenc = m.tencoder[idx]
                    xt = tenc(xt)
                    if not tenc.empty:
                        saved_t.append(xt)
                    else:
                        inject = xt
                x = encode(x, inject)
                if idx == 0 and m.freq_emb is not None:
                    frs = torch.arange(x.shape[-2], device=x.device)
                    emb = m.freq_emb(frs).t()[None, :, :, None].expand_as(x)
                    x = x + m.freq_emb_scale * emb
                saved.append(x)
            if m.crosstransformer:
                if m.bottom_channels:
                    b, c, f, t = x.shape
                    x = rearrange(x, "b c f t-> b c (f t)")
                    x = m.channel_upsampler(x)
                    x = rearrange(x, "b c (f t)-> b c f t", f=f)
                    xt = m.channel_upsampler_t(xt)
                x, xt = m.crosstransformer(x, xt)
                if m.bottom_channels:
                    x = rearrange(x, "b c f t-> b c (f t)")
                    x = m.channel_downsampler(x)
                    x = rearrange(x, "b c (f t)-> b c f t", f=f)
                    xt = m.channel_downsampler_t(xt)
            for idx, decode in enumerate(m.decoder):
                skip = saved.pop(-1)
                x, pre = decode(x, skip, lengths.pop(-1))
                offset = m.depth - len(m.tdecoder)
                if idx >= offset:
                    tdec = m.tdecoder[idx - offset]
                    length_t = lengths_t.pop(-1)
                    if tdec.empty:
                        pre = pre[:, :, 0]
                        xt, _ = tdec(pre, None, length_t)
                    else:
                        skip = saved_t.pop(-1)
                        xt, _ = tdec(xt, skip, length_t)
            S = len(m.sources)
            x = x.view(B, S, -1, Fq, T)
            x = x * std[:, None] + mean[:, None]
            xt = xt.view(B, S, -1, mix.shape[-1])
            xt = xt * stdt[:, None] + meant[:, None]
            return x, xt

    return Core(model).eval()


def fp16_initializers(onnx_path: str, min_elems: int = 1024) -> None:
    """Buyuk fp32 agirliklari fp16 sakla, hemen ardindan Cast(float) ekle (hesap fp32 kalir)."""
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    model = onnx.load(onnx_path)
    g = model.graph
    new_inits, casts = [], []
    for init in g.initializer:
        if init.data_type == TensorProto.FLOAT and int(np.prod(init.dims)) >= min_elems:
            arr = numpy_helper.to_array(init).astype(np.float16)
            h = numpy_helper.from_array(arr, init.name + "__fp16")
            new_inits.append(h)
            casts.append(helper.make_node("Cast", [h.name], [init.name], to=TensorProto.FLOAT,
                                          name=init.name + "__cast"))
        else:
            new_inits.append(init)
    del g.initializer[:]
    g.initializer.extend(new_inits)
    nodes = list(g.node)
    del g.node[:]
    g.node.extend(casts + nodes)
    onnx.checker.check_model(model)
    onnx.save(model, onnx_path)


def export_demucs(weights: str, out: str, fp16: bool = True) -> None:
    import numpy as np
    import torch
    from gh.ai.demucs import SEGMENT
    from gh.ai.spec import cac_magnitude, demucs_spec
    model = load_demucs(weights)
    core = make_core(model)
    rng = np.random.default_rng(0)
    mix = (0.1 * rng.standard_normal((1, 2, SEGMENT))).astype(np.float32)
    mag = cac_magnitude(demucs_spec(mix))
    tmp = out + ".tmp.onnx"
    t0 = time.perf_counter()
    torch.backends.mha.set_fastpath_enabled(False)      # aten::_native_multi_head_attention ONNX'te yok
    with torch.no_grad():
        torch.onnx.export(core, (torch.from_numpy(mix), torch.from_numpy(mag)), tmp, input_names=["mix", "mag"],
                          output_names=["x", "xt"], opset_version=17, dynamo=False, do_constant_folding=True)
    print(f"exported in {time.perf_counter() - t0:.1f}s")
    if fp16:
        fp16_initializers(tmp)
    os.replace(tmp, out)
    for extra in (tmp + ".data",):
        if os.path.exists(extra):
            os.remove(extra)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
    # ayni girdide torch cekirdegi ile birebir karsilastir
    import onnxruntime as ort
    sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
    ox, oxt = sess.run(None, {"mix": mix, "mag": mag})
    with torch.no_grad():
        tx, txt = core(torch.from_numpy(mix), torch.from_numpy(mag))
    for name, a, b in (("x", ox, tx.numpy()), ("xt", oxt, txt.numpy())):
        err = float(np.abs(a - b).max())
        rel = float(np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-12))
        print(f"  core {name}: max abs err {err:.2e}, rel l2 {rel:.2e}")


def copy_basic_pitch(out: str) -> None:
    import basic_pitch
    src = os.path.join(os.path.dirname(basic_pitch.__file__), "saved_models", "icassp_2022", "nmp.onnx")
    shutil.copyfile(src, out)
    print(f"wrote {out} ({os.path.getsize(out) / 1e3:.0f} kB) from {src}")


def sdr(ref, est) -> float:
    import numpy as np
    ref = np.asarray(ref, dtype=np.float64)
    est = np.asarray(est, dtype=np.float64)
    return float(10 * np.log10((ref ** 2).sum() / max(((ref - est) ** 2).sum(), 1e-20)))


def verify(weights: str, seconds: float = 30.0) -> None:
    """Tam sarki yolu: numpy+ORT (gh.ai.demucs.separate) vs torch apply_model(split, overlap .25, shifts 0)."""
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from gh.ai import demucs as gd
    folder = os.path.join(ROOT, "Songs", "RIFF Demo Band - Voltage Run")
    s, sr = sf.read(os.path.join(folder, "song.ogg"), dtype="float32", always_2d=True)
    g, _ = sf.read(os.path.join(folder, "guitar.ogg"), dtype="float32", always_2d=True)
    n = min(len(s), len(g), int(seconds * sr))
    mix = (s[:n] + g[:n]).T
    if mix.shape[0] == 1:
        mix = np.concatenate([mix, mix])
    t0 = time.perf_counter()
    st = gd.separate(mix, keep_all=True)
    t_onnx = time.perf_counter() - t0
    model = load_demucs(weights)
    torch.set_num_threads(os.cpu_count() // 2 or 1)
    wav = torch.from_numpy(np.ascontiguousarray(mix))
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    t0 = time.perf_counter()
    with torch.no_grad():
        out = apply_model(model, ((wav - mean) / std)[None], shifts=0, split=True, overlap=0.25, progress=False)[0]
    out = (out * std + mean).numpy()
    t_torch = time.perf_counter() - t0
    for i, name in enumerate(gd.SOURCES):
        print(f"  {name:7s} SDR(onnx vs torch) {sdr(out[i], st.all[i]):6.1f} dB")
    print(f"  guitar  SDR vs true guitar.ogg: onnx {sdr(g[:n].T.mean(0), st.guitar.mean(0)):.2f} dB, "
          f"torch {sdr(g[:n].T.mean(0), out[gd.GUITAR].mean(0)):.2f} dB")
    print(f"  time {n / sr:.0f}s audio: onnx {t_onnx:.1f}s  torch {t_torch:.1f}s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--no-fp16", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    w = fetch_weights()
    if not args.skip_export:
        export_demucs(w, os.path.join(args.out, "htdemucs_6s.onnx"), fp16=not args.no_fp16)
        copy_basic_pitch(os.path.join(args.out, "basic_pitch_nmp.onnx"))
    if args.verify:
        os.environ["RIFF_MODELS_DIR"] = args.out
        verify(w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
