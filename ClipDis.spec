# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
onefile = os.environ.get("CLIPDIS_ONEFILE", "0") == "1"
console = os.environ.get("CLIPDIS_CONSOLE", "1") != "0"

keyring_hiddenimports = collect_submodules("keyring.backends")

datas = [
    (str(project_root / "app" / "gui"), "app/gui"),
    (str(project_root / "app" / "gui" / "assets" / "app_icon.ico"), "."),
]

for notice_dir, target_dir in (
    (project_root / "app" / "ffmpeg", "app/ffmpeg"),
    (project_root / "app" / "ffmpeg" / "bin", "app/ffmpeg/bin"),
):
    for pattern in ("LICENSE*", "COPYING*", "NOTICE*"):
        for notice_path in notice_dir.glob(pattern):
            if notice_path.is_file():
                datas.append((str(notice_path), target_dir))

binaries = [
    (str(project_root / "app" / "ffmpeg" / "bin" / "ffmpeg.exe"), "app/ffmpeg/bin"),
    (str(project_root / "app" / "ffmpeg" / "bin" / "ffprobe.exe"), "app/ffmpeg/bin"),
]

hiddenimports = [
    # Keep Qt collection intentionally narrow. The app uses a QML/Quick
    # Controls UI, QWidget-based tray/dialog helpers, and QLocalServer/Socket.
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtNetwork",
    *keyring_hiddenimports,
    "PIL.Image",
    "requests",
]

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtDesigner",
        "PySide6.QtGraphs",
        "PySide6.QtHelp",
        "PySide6.QtHttpServer",
        "PySide6.QtLocation",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetworkAuth",
        "PySide6.QtNfc",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtPrintSupport",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickTest",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialBus",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtStateMachine",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtTextToSpeech",
        "PySide6.QtUiTools",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "PySide6.QtWebView",
        "PySide6.QtXml",
    ],
    noarchive=False,
    optimize=0,
)

unused_qt_payload_markers = (
    "Qt6WebEngine",
    "QtWebEngine",
    "WebEngine",
    "Qt63D",
    "Qt3D",
    "QtQuick3D",
    "Quick3D",
    "Qt6Charts",
    "QtCharts",
    "Qt6Graphs",
    "QtGraphs",
    "Qt6DataVisualization",
    "QtDataVisualization",
    "Qt6Designer",
    "QtDesigner",
    "Qt6Help",
    "QtHelp",
    "qt_help_",
    "Qt6HttpServer",
    "QtHttpServer",
    "Qt6Location",
    "QtLocation",
    "Qt6Multimedia",
    "QtMultimedia",
    "Qt6NetworkAuth",
    "QtNetworkAuth",
    "Qt6Nfc",
    "QtNfc",
    "Qt6Pdf",
    "QtPdf",
    "QtQuick/Pdf",
    "QtQuick\\Pdf",
    "Qt6Positioning",
    "QtPositioning",
    "Qt6RemoteObjects",
    "QtRemoteObjects",
    "Qt6Scxml",
    "QtScxml",
    "Qt6Sensors",
    "QtSensors",
    "Qt6Serial",
    "QtSerial",
    "Qt6SpatialAudio",
    "QtSpatialAudio",
    "Qt6StateMachine",
    "QtStateMachine",
    "Qt6Svg",
    "QtSvg",
    "Qt6TextToSpeech",
    "QtTextToSpeech",
    "Qt6UiTools",
    "QtUiTools",
    "Qt6WebChannel",
    "QtWebChannel",
    "Qt6WebSockets",
    "QtWebSockets",
    "Qt6WebView",
    "QtWebView",
    "qmltooling",
    "qmlformat",
    "qmlls",
    "qmlcachegen",
    "qmlpreview",
    "qmlprofiler",
    "qmltestrunner",
    "qmltyperegistrar",
    "qml\\QtQuick\\Controls\\designer",
    "qml/QtQuick/Controls/designer",
)


def keep_qt_payload(entry):
    haystack = " ".join(str(part) for part in entry)
    return not any(marker in haystack for marker in unused_qt_payload_markers)


# The PySide6 hooks include some optional Qt families through QML dependency
# collection. ClipDis only imports QtQuick, QtQuick.Controls, QtQuick.Layouts,
# QtWidgets, QtGui, QtCore, QtQml, QtNetwork, and QtQuickControls2.
a.binaries = type(a.binaries)([entry for entry in a.binaries if keep_qt_payload(entry)])
a.datas = type(a.datas)([entry for entry in a.datas if keep_qt_payload(entry)])

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [] if not onefile else a.binaries,
    [] if not onefile else a.datas,
    [],
    name="ClipDis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "app" / "gui" / "assets" / "app_icon.ico"),
)

if not onefile:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="ClipDis",
    )
