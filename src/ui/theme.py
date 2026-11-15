# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""统一配色常量。

背景：`styles.qss` 与自绘代码（wall_view / grid_view / viewer）此前各用一套
色值，同一语义在两处可能不同（例如选中色 QSS 用 #0b57d0、图片墙用 #31406b），
换主题要改两处、还容易漏。这里集中定义，QSS 通过同名色值保持视觉一致。
"""

import re

# ---- 基础表面 ----
BG_APP = "#202124"          # 主背景 / 图片墙底色
BG_VIEWER = "#101112"       # 大图浏览器底色（更暗，让图片更突出）
BG_CARD = "#26272b"         # 卡片底色
BG_CARD_HOVER = "#2c2d31"   # 卡片悬停 / 图片墙占位
BG_CARD_SEL = "#31406b"     # 卡片选中
BG_PLACEHOLDER = "#333438"  # 缩略图未就绪的占位块
BG_BUTTON = "#26272b"
BG_BUTTON_HOVER = "#313236"
BG_CORRUPTED = "#3a3b3e"    # 损坏图 / 角标底色
BORDER = "#3a3b3e"          # 分隔线

# ---- 前景 ----
FG_PRIMARY = "#e8eaed"      # 主文字
FG_SECONDARY = "#c7cbd4"    # 信息行文字
FG_MUTED = "#8a8f98"        # 次要说明文字

# ---- 强调色 ----
ACCENT = "#8ab4f8"          # 焦点框 / 链接
STAR = "#ffd54f"            # 最爱星标 / 选中描边
DUP = "#1e88e5"             # 重复标记
DANGER = "#e57373"          # 危险操作 / 已损坏
SUCCESS = "#81c784"         # 还原等安全操作
HUD_BG = "#82000000"        # 大图 HUD 文字底条（浅色图上保证可读）；由 viewer 使用
                            # 用 Qt 的 #AARRGGBB，不是 CSS 的 rgba()：
                            # QColor("rgba(0,0,0,130)") 得到的是无效色（实际渲染成不透明黑）

# ---- 仅 qss 使用的表面/描边（自绘代码不走这些）----
TOOLBAR_BG = "#292a2d"      # 工具栏 / 状态栏
INPUT_BG = "#3a3b3e"        # 输入框、按钮常态
INPUT_BORDER = "#4a4b4e"    # 输入框、按钮描边
INPUT_HOVER = "#4a4b4e"     # 按钮悬停
INPUT_PRESSED = "#55565a"   # 按钮按下
SELECTED_BG = "#31406b"     # 选中 / 勾选态
DISABLED_FG = "#77797d"
DISABLED_BG = "#2c2d30"
MENU_BG = "#2c2d30"         # 菜单 / 下拉弹层
SCROLL_HANDLE = "#4a4b4e"
SCROLL_HOVER = "#5f6165"
FG_ON_ACCENT = "#ffffff"

# 容器类控件才铺底色。之前是 `QWidget { background-color }` 全局铺，
# 导致每个复合控件都继承不透明底色，只好在 QLabel 和 MainWindow 里
# 逐点补透明；补丁越加越多，且新控件一加就多一块「深色方块压在图片上」。
CONTAINER_SELECTOR = (
    "QMainWindow, QDialog, QScrollArea, QListView, QTableWidget, "
    "QToolBar, QStatusBar, QMenu, QSplitter, QStackedWidget"
)

# 参与 qss 渲染的色值表：键即 qss 里的 @KEY@
QSS_VARS = {
    "BG_APP": BG_APP,
    "BG_VIEWER": BG_VIEWER,
    "BG_CARD": BG_CARD,
    "BG_CARD_HOVER": BG_CARD_HOVER,
    "BG_CARD_SEL": BG_CARD_SEL,
    "BORDER": BORDER,
    "FG_PRIMARY": FG_PRIMARY,
    "FG_SECONDARY": FG_SECONDARY,
    "FG_MUTED": FG_MUTED,
    "ACCENT": ACCENT,
    "STAR": STAR,
    "DUP": DUP,
    "DANGER": DANGER,
    "SUCCESS": SUCCESS,
    "TOOLBAR_BG": TOOLBAR_BG,
    "INPUT_BG": INPUT_BG,
    "INPUT_BORDER": INPUT_BORDER,
    "INPUT_HOVER": INPUT_HOVER,
    "INPUT_PRESSED": INPUT_PRESSED,
    "SELECTED_BG": SELECTED_BG,
    "DISABLED_FG": DISABLED_FG,
    "DISABLED_BG": DISABLED_BG,
    "MENU_BG": MENU_BG,
    "SCROLL_HANDLE": SCROLL_HANDLE,
    "SCROLL_HOVER": SCROLL_HOVER,
    "FG_ON_ACCENT": FG_ON_ACCENT,
    "CONTAINER_SELECTOR": CONTAINER_SELECTOR,
}


def css(**kv) -> str:
    """拼一段行内样式，供少数必须内联的场合使用。

    Qt 的行内 setStyleSheet 会覆盖 qss 继承，所以只在这里生成，
    不要在代码里散写字面色值 —— 那样加主题时要翻遍九个文件。
    """
    parts = []
    for key, value in kv.items():
        if value is None:
            continue
        parts.append(f"{key.replace('_', '-')}:{value}")
    return ";".join(parts) + ";"


def muted(font_size: int | None = None, bold: bool = False,
          color: str | None = None) -> str:
    """弱化说明文字的统一样式。"""
    return css(color=color or FG_MUTED, font_size=font_size,
               font_weight="bold" if bold else None)


def accent_text(font_size: int | None = None, bold: bool = False) -> str:
    """强调色文字（标题、链接）。"""
    return css(color=ACCENT, font_size=font_size,
               font_weight="bold" if bold else None)


def render_qss(raw: str) -> str:
    """把 styles.qss 里的 @KEY@ 换成 theme 的色值。

    这样「换主题」只改这一份常量，qss 不再是一份需要手动同步的字面量副本。
    """
    out = raw
    for key, value in QSS_VARS.items():
        out = out.replace(f"@{key}@", value)
    left = re.findall(r"@[A-Z_]+@", out)
    if left:
        raise ValueError(f"styles.qss 里有未定义的占位符：{sorted(set(left))}")
    return out


def load_qss(base) -> str:
    """读取并渲染 styles.qss。文件缺失时返回空串（不阻断启动）。"""
    path = base / "src" / "ui" / "styles.qss"
    if not path.exists():
        return ""
    return render_qss(path.read_text("utf-8"))
