# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""统一配色：一套或两套调色板，一个切换入口。

背景：`styles.qss` 与自绘代码（wall_view / grid_view / viewer）此前各用一套
色值，同一语义在两处可能不同（例如选中色 QSS 用 #0b57d0、图片墙用 #31406b），
换主题要改两处、还容易漏。这里集中定义，QSS 通过同名占位符保持视觉一致。

两处约定：

1. **自绘代码必须写 `theme.BG_CARD`，不要 `from .theme import BG_CARD`。**
   后者在导入时把字符串绑死，之后调 `apply_palette()` 换不了已经导入的名字。
   这是 1.6.7 之前三个视图文件的写法，加浅色主题时才暴露出来。
2. **调色板项只增不改语义。** 加一个键要同时补进 `_DARK` 与 `_LIGHT`，
   `apply_palette` 会校验两边键集合相同，漏一边在启动时就报错。
"""

import re

# ---- 深色（默认）----
_DARK = {
    # 基础表面
    "BG_APP": "#202124",          # 主背景 / 图片墙底色
    "BG_VIEWER": "#101112",       # 大图浏览器底色（更暗，让图片更突出）
    "BG_CARD": "#26272b",         # 卡片底色
    "BG_CARD_HOVER": "#2c2d31",   # 卡片悬停 / 图片墙占位
    "BG_CARD_SEL": "#31406b",     # 卡片选中
    "BG_PLACEHOLDER": "#333438",  # 缩略图未就绪的占位块
    "BG_BUTTON": "#26272b",
    "BG_BUTTON_HOVER": "#313236",
    "BG_CORRUPTED": "#3a3b3e",    # 损坏图 / 角标底色
    "BORDER": "#3a3b3e",          # 分隔线
    # 前景
    "FG_PRIMARY": "#e8eaed",
    "FG_SECONDARY": "#c7cbd4",
    "FG_MUTED": "#8a8f98",
    # 强调
    "ACCENT": "#8ab4f8",          # 焦点框 / 链接
    "STAR": "#ffd54f",            # 最爱星标 / 选中描边
    "DUP": "#1e88e5",             # 重复标记
    "DANGER": "#e57373",
    "SUCCESS": "#81c784",
    "HUD_BG": "#82000000",        # 大图 HUD 文字底条；Qt 的 #AARRGGBB 写法，
                                  # 不是 CSS 的 rgba()（QColor("rgba(0,0,0,130)")
                                  # 得到的是无效色，实际渲染成不透明黑）
    # 仅 qss 使用的表面/描边（自绘代码不走这些）
    "TOOLBAR_BG": "#292a2d",
    "INPUT_BG": "#3a3b3e",
    "INPUT_BORDER": "#4a4b4e",
    "INPUT_HOVER": "#4a4b4e",
    "INPUT_PRESSED": "#55565a",
    "SELECTED_BG": "#31406b",
    "DISABLED_FG": "#77797d",
    "DISABLED_BG": "#2c2d30",
    "MENU_BG": "#2c2d30",
    "SCROLL_HANDLE": "#4a4b4e",
    "SCROLL_HOVER": "#5f6165",
    "FG_ON_ACCENT": "#ffffff",
}

# ---- 浅色 ----
# 取向：白底、灰边、深字。强调色比深色版压暗一档，
# 否则 #8ab4f8 这种浅蓝放在白底上对比度不足，链接和焦点框看不清。
_LIGHT = {
    "BG_APP": "#f5f6f8",
    "BG_VIEWER": "#101112",       # 看图始终用深底：浅底会让图片边缘发灰
    "BG_CARD": "#ffffff",
    "BG_CARD_HOVER": "#eef0f3",
    "BG_CARD_SEL": "#d6e2fb",
    "BG_PLACEHOLDER": "#e7e9ed",
    "BG_BUTTON": "#ffffff",
    "BG_BUTTON_HOVER": "#eef0f3",
    "BG_CORRUPTED": "#e0e2e6",
    "BORDER": "#d8dbe0",
    "FG_PRIMARY": "#1f2126",
    "FG_SECONDARY": "#4a4f57",
    "FG_MUTED": "#6b7178",
    "ACCENT": "#1a5fd0",
    "STAR": "#e8a30c",
    "DUP": "#1565c0",
    "DANGER": "#c62828",
    "SUCCESS": "#2e7d32",
    "HUD_BG": "#82000000",
    "TOOLBAR_BG": "#fbfbfc",
    "INPUT_BG": "#ffffff",
    "INPUT_BORDER": "#c9cdd4",
    "INPUT_HOVER": "#eef0f3",
    "INPUT_PRESSED": "#dfe2e7",
    "SELECTED_BG": "#d6e2fb",
    "DISABLED_FG": "#a6abb3",
    "DISABLED_BG": "#f0f1f4",
    "MENU_BG": "#ffffff",
    "SCROLL_HANDLE": "#c9cdd4",
    "SCROLL_HOVER": "#aab0b9",
    "FG_ON_ACCENT": "#ffffff",
}

PALETTES = {"dark": _DARK, "light": _LIGHT}
DEFAULT_PALETTE = "dark"

_current_name = DEFAULT_PALETTE

# 键集合必须一致，否则某个主题下会出现「取不到颜色」的空值
if set(_DARK) != set(_LIGHT):
    raise RuntimeError(
        f"调色板键不一致：{sorted(set(_DARK) ^ set(_LIGHT))}")

# 把当前调色板铺成模块级名字，供 `theme.BG_CARD` 读取
globals().update(_DARK)

# 容器类控件才铺底色。之前是 `QWidget { background-color }` 全局铺，
# 导致每个复合控件都继承不透明底色，只好在 QLabel 和 MainWindow 里
# 逐点补透明；补丁越加越多，且新控件一加就多一块「深色方块压在图片上」。
CONTAINER_SELECTOR = (
    "QMainWindow, QDialog, QScrollArea, QListView, QTableWidget, "
    "QToolBar, QStatusBar, QMenu, QSplitter, QStackedWidget"
)

# 参与 qss 渲染的色值表：键即 qss 里的 @KEY@。
# 保持同一个 dict 对象（render_qss 持有引用），换主题时就地更新。
QSS_VARS = {}


def _rebuild_qss_vars() -> None:
    QSS_VARS.clear()
    for key in _DARK:
        QSS_VARS[key] = globals()[key]
    QSS_VARS["CONTAINER_SELECTOR"] = CONTAINER_SELECTOR


_rebuild_qss_vars()


def current_palette() -> str:
    return _current_name


def apply_palette(name: str) -> bool:
    """切换调色板。返回是否真的发生了变化。

    只改 theme 模块的全局名字与 QSS_VARS。调用方负责把新的 qss 重新
    塞给 QApplication，并让自绘控件重绘（见 ui/theme.apply 的封装）。
    """
    global _current_name
    name = (name or "").strip().lower()
    if name not in PALETTES:
        name = DEFAULT_PALETTE
    if name == _current_name:
        return False
    _current_name = name
    globals().update(PALETTES[name])
    _rebuild_qss_vars()
    return True


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


def qss_path(base):
    return base / "src" / "ui" / "styles.qss"


def load_qss(base) -> str:
    """读取并渲染 styles.qss。文件缺失时返回空串（不阻断启动）。"""
    path = qss_path(base)
    if not path.exists():
        return ""
    return render_qss(path.read_text("utf-8"))


def apply(name: str = None) -> bool:
    """换主题并让整个应用立刻跟上。

    做三件事：切调色板、重设 QApplication 样式表、让自绘控件重绘。
    第三件必须显式做 —— QSS 变化会触发 Qt 自己的重绘，但
    grid_view / wall_view / viewer 的配色来自 paintEvent 里的
    theme.X，样式表变了它们不会自己收到通知。
    """
    from PySide6.QtWidgets import QApplication

    changed = apply_palette(name) if name else False
    app = QApplication.instance()
    if app is None:
        return changed
    qss = load_qss(_base_dir())
    if qss:
        app.setStyleSheet(qss)
    for w in app.allWidgets():
        w.update()
    return changed


def _base_dir():
    """程序根目录：打包后是 sys._MEIPASS，源码运行时是项目根。"""
    import sys
    from pathlib import Path

    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent.parent
