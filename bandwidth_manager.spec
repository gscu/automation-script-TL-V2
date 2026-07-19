# PyInstaller spec for Bandwidth Report Manager.
# Build with:  pyinstaller bandwidth_manager.spec   (see BUILD_EXE.bat)
#
# Produces a one-folder app:  dist/Bandwidth Report Manager/Bandwidth Report Manager.exe
# - windowed (no console window, ever)
# - bundles customtkinter and its theme assets
#
# IMPORTANT: only the manager GUI is frozen. The report scripts
# ("Morning BW Reports.py" / "Afternoon BW Reports.py") must stay as loose
# .py files NEXT TO the exe, because:
#   1. the manager patches credentials/paths directly into them, and
#   2. they run under the machine's own Python (Playwright, Outlook COM).
# BUILD_EXE.bat copies them into the dist folder after the build.

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# customtkinter ships .json theme files + fonts that must be collected.
for pkg in ("customtkinter",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h


block_cipher = None

a = Analysis(
    ["bandwidth_report_manager.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Bandwidth Report Manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # <- no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,                # drop a bw.ico next to this spec to brand it
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Bandwidth Report Manager",
)
