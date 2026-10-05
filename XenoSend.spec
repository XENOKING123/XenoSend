# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['source/modified/app/desktop/run_desktop.py'],
    pathex=['source/modified'],
    binaries=[],
    datas=[
        ('source/modified/app/desktop/web', 'app/desktop/web'),
        ('source/modified/app/assets', 'app/assets'),
    ],
    hiddenimports=[
        'webview','webview.platforms.edgechromium','clr_loader','pythonnet',
        
        'app.services.host_psm',
        'app.services.xeno',
        'app.catalogs.xeno_trainer_catalog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.datas = [d for d in a.datas if 'preview' not in d[0].lower()]
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='XenoSend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # icon file not found; exe will use default
)
