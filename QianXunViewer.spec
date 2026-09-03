# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。
#
# 打包配置：环境变量 QX_ONEFILE=1 出单文件版，否则出目录版。
# 精简未使用模块（Qml/Quick/OpenGL/Pdf/AVIF）与 opengl32sw 软件渲染库
# （合计约 40MB），显著降低单文件版启动解压耗时与目录版体积。
import os

ONEFILE = os.environ.get("QX_ONEFILE", "") == "1"

a = Analysis(
    ["main.py"],
    datas=[("assets/logo.png", "assets"), ("src/ui/styles.qss", "src/ui")],
    excludes=["PySide6.QtQml", "PySide6.QtQmlModels", "PySide6.QtQuick",
              "PySide6.QtQuickWidgets", "PySide6.QtOpenGL",
              "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PIL._avif"],
)

# 过滤 Qt 未用二进制与 qml/pdf 插件资源
_drop = ("opengl32sw", "Qt6Qml", "Qt6Quick", "Qt6Pdf", "Qt6OpenGL", "qpdf")
a.binaries = [b for b in a.binaries if not any(d in b[0] for d in _drop)]
a.datas = [d for d in a.datas
           if not any(x in d[0].replace("\\", "/") for x in
                      ("PySide6/Qt/qml", "qtquick", "qpdf", "qtlabs"))]

pyz = PYZ(a.pure)

if ONEFILE:
    EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
        name="QianXunViewer", debug=False, bootloader_ignore_signals=False,
        strip=False, upx=False, console=False, disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None, codesign_identity=None,
        entitlements_file=None, icon="assets/icon.ico")
else:
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name="QianXunViewer",
              debug=False, strip=False, upx=False, console=False,
              icon="assets/icon.ico")
    COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False,
            name="QianXunViewer")
