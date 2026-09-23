# PyInstaller spec: pyinstaller RIFF.spec --noconfirm --clean  (build.ps1 kullanin)
# onedir: hizli acilis; Songs/ klasoru exe'nin yanina kopyalanir (kullanici kendi sarkilarini ekleyebilsin).

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest", "soundfile", "PIL", "IPython", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RIFF",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="RIFF")
