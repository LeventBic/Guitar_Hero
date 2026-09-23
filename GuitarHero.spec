# PyInstaller spec: pyinstaller GuitarHero.spec --noconfirm --clean  (build.ps1 kullanin) -> dist\GuitarHero\GuitarHero.exe
# onedir: hizli acilis; Songs/ klasoru exe'nin yanina kopyalanir (kullanici kendi sarkilarini ekleyebilsin).
# assets/models (Demucs + basic-pitch ONNX) datas ile gelir; onnxruntime ve soundfile (libsndfile: OGG stem
# yazimi) hooks-contrib kancalariyla toplanir.

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=["onnxruntime", "soundfile", "av"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "PIL", "IPython", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GuitarHero",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GuitarHero")
