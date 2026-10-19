# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""统一配色常量。

背景：`styles.qss` 与自绘代码（wall_view / grid_view / viewer）此前各用一套
色值，同一语义在两处可能不同（例如选中色 QSS 用 #0b57d0、图片墙用 #31406b），
换主题要改两处、还容易漏。这里集中定义，QSS 通过同名色值保持视觉一致。
"""

# ---- 基础表面 ----
BG_APP = "#202124"          # 主背景 / 图片墙底色
BG_VIEWER = "#101112"       # 大图浏览器底色（更暗，让图片更突出）
BG_CARD = "#26272b"         # 卡片底色
BG_CARD_HOVER = "#2c2d31"   # 卡片悬停 / 图片墙占位
BG_CARD_SEL = "#31406b"     # 卡片选中
BG_PLACEHOLDER = "#333438"  # 缩略图未就绪的占位块
BG_CORRUPTED = "#3a3b3e"    # 损坏图 / 角标底色
BORDER = "#3a3b3e"          # 分隔线

# ---- 前景 ----
FG_PRIMARY = "#e8eaed"      # 主文字
FG_SECONDARY = "#c7cbd4"    # 信息行文字
FG_MUTED = "#8a8f98"        # 次要说明文字

# ---- 强调色 ----
ACCENT = "#8ab4f8"          # 焦点框 / 链接
FOCUS = "#8ab4f8"
STAR = "#ffd54f"            # 最爱星标 / 选中描边
DUP = "#1e88e5"             # 重复标记
DANGER = "#e57373"          # 危险操作 / 已损坏
SUCCESS = "#81c784"         # 还原等安全操作
HUD_BG = "rgba(0,0,0,130)"  # 大图 HUD 文字底条（浅色图上保证可读）
