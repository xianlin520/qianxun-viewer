"""千寻影集 QianXun Album
版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

离线冒烟测试：不依赖真窗口、不联网，构造各视图并走一遍关键交互。

跑法（任意目录）：

    ./.venv/Scripts/python.exe tests/smoke_app.py

与 tests/test_pure.py 的分工：那边测纯逻辑，这里测需要 QApplication 的
窗口构造与信号行为。设置项用独立的应用名隔离，绝不动用户真实配置。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# 隔离设置：改应用名，让 QSettings 落到另一个 ini。
# 不能用环境变量隔离：Qt 的 QSettings 走 Windows 已知文件夹，不看 APPDATA。
import src.core.settings as _S

_S.ORG_NAME = "QianXunSmoke"
_S.APP_NAME = "QianXunViewerSmoke"

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

app = QApplication([])
app.setApplicationName(_S.APP_NAME)
app.setOrganizationName(_S.ORG_NAME)
QSettings.setDefaultFormat(QSettings.Format.IniFormat)

tmp = Path(tempfile.mkdtemp(prefix="qx_lib_"))
for i, (w, h) in enumerate([(1200, 800), (800, 1200), (600, 600), (1600, 900)]):
    Image.new("RGB", (w, h), (30 * i, 60, 120)).save(tmp / f"img{i}.jpg")
# 一对重复图
import shutil
shutil.copy(tmp / "img0.jpg", tmp / "dupA.jpg")
shutil.copy(tmp / "img0.jpg", tmp / "dupB.jpg")

results = []
def step(name, fn):
    try:
        fn()
        results.append(f"  {name} OK")
    except Exception:
        results.append(f"  {name} 失败\n{traceback.format_exc()}")
        raise


from src.core.settings import AppSettings
from src.core.favorites import FavoritesStore

def t_settings():
    s = AppSettings()
    s.upload_threads = 99
    assert s.upload_threads == 8, s.upload_threads
    s.share_days = 0
    assert s.share_days == 1
    s.server_base = "https://x.y/"
    assert s.server_base == "https://x.y", s.server_base
    s.oss_ak_secret = "SK-TEST"
    assert s.oss_ak_secret == "SK-TEST"
    s.sync()
step("设置项读写与夹取", t_settings)

def t_fav():
    st = FavoritesStore(tmp)
    assert st.toggle(tmp / "img1.jpg") is True
    assert st.contains(tmp / "img1.jpg")
    assert not st.contains(tmp / "img2.jpg")
    assert not st.contains(tmp / "nope.jpg")
    # 已收藏项的绝对路径（含子目录拼接）仍应命中
    assert st.contains(Path(tmp.as_posix()) / "img1.jpg")
step("收藏路径换算", t_fav)

from src.ui.main_window import MainWindow
mw = None
def t_main():
    global mw
    mw = MainWindow()
    mw.resize(1280, 860)
    mw.show()
    app.processEvents()
    mw.close()
step("主窗体构造/显示/关闭", t_main)

from src.core import duplicates
from src.workers.workers import HashWorker
from src.core.phash import phash_hex

def t_dup():
    class I:
        def __init__(self, p):
            self.path = p; self.phash = phash_hex(Image.open(p))
    items = [I(p) for p in sorted(tmp.glob("*.jpg"))]
    items = [x for x in items if x.phash]
    groups = duplicates.find_groups(items, 4)
    names = sorted(sorted(Path(x.path).name for x in g) for g in groups)
    # dupA/dupB 都是 img0 的副本，三张必然同组
    assert any({"dupA.jpg", "dupB.jpg"} <= set(g) for g in names), names
step(f"查重识别重复对", t_dup)

def t_thumb_cache():
    from src.ui.thumb_cache import THUMBS, tier_for
    from src.core import thumbnail
    assert tier_for(300) == 512 and tier_for(200) == 256
    assert THUMBS.best(None, type("X", (), {"phash": "", "path": tmp/"img0.jpg",
                                           "size_bytes": 1, "mtime": 0})()) is None
step("缩略图门面", t_thumb_cache)

from src.ui.viewer import ViewerOverlay
def t_viewer():
    v = ViewerOverlay(None, None)
    v.resize(900, 700); v.show(); app.processEvents()
    from PySide6.QtGui import QPixmap
    for w, h in ((40, 40), (4000, 3000)):
        v._pix = QPixmap(w, h); v._pix.fill()
        v._scale = min(v._fit_scale(), 1.0)
        a = v._scale
        t1 = v._double_click_target(); v._scale = t1
        t2 = v._double_click_target()
        assert abs(t1 - a) > 1e-6, f"{w}x{h} 双击无变化"
        assert abs(t2 - a) < 1e-6, f"{w}x{h} 回不去"
    v.close_overlay()
    assert v._pix.isNull(), "关闭后未释放 pixmap"
    v.close()
step("大图双击切换与释放", t_viewer)

from src.ui.pager import PagerBar
def t_pager():
    from PySide6.QtCore import QSize
    p = PagerBar()
    got = []
    p.page_changed.connect(lambda n: got.append(n))
    p.set_state(1, 5)
    # 同一目标连发两次只应发出一次（修掉的正是这个重复信号）
    p._goto(2); p._goto(2)
    assert got == [2], got
    # 点「下一页」两次应连续前进：第二次读到的是刚更新的 _page
    p.btn_next.click(); p.btn_next.click()
    assert got == [2, 3, 4], got
    # 越界载荷被夹取
    got.clear(); p._goto(-5); p._goto(99)
    assert got == [0, 4], got
step("分页夹取", t_pager)

from src.ui.duplicates_dialog import DuplicatesDialog
def t_dup_dialog():
    d = DuplicatesDialog(mw.controller, [], mw)
    d.close()
step("查重面板构造", t_dup_dialog)

from src.ui.settings_dialog import SettingsDialog
def t_settings_dialog():
    d = SettingsDialog(AppSettings(), mw)
    d.close()
step("设置对话框构造", t_settings_dialog)

from src.ui.shares_dialog import SharesDialog
def t_shares_dialog():
    d = SharesDialog(mw.controller, mw)
    d.close()
step("分享记录对话框构造", t_shares_dialog)

print()
print("\n".join(results))
print("\n全部通过")
