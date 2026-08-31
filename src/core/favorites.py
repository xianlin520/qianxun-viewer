# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""最爱配置：favorites.json 跟随图片目录存放，只记相对路径。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FILE_NAME = "favorites.json"


class FavoritesStore:
    def __init__(self, root: Path):
        self.root = root
        self.items: dict[str, str] = {}  # 相对路径(posix) -> 加入时间
        self.load()

    @property
    def path(self) -> Path:
        return self.root / FILE_NAME

    def load(self) -> None:
        self.items = {}
        try:
            data = json.loads(self.path.read_text("utf-8"))
            for it in data.get("items", []):
                self.items[str(it["path"])] = str(it.get("added", ""))
        except Exception:
            self.items = {}

    def contains(self, abs_path: Path) -> bool:
        return self._rel(abs_path) in self.items

    def toggle(self, abs_path: Path) -> bool:
        """切换最爱状态，落盘并返回新状态。"""
        key = self._rel(abs_path)
        if key in self.items:
            del self.items[key]
            new_state = False
        else:
            self.items[key] = datetime.now().isoformat(timespec="seconds")
            new_state = True
        self.save()
        return new_state

    def save(self) -> None:
        try:
            data = {"version": 1,
                    "items": [{"path": k, "added": v} for k, v in self.items.items()]}
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        except OSError:
            pass  # 目录只读等场景：内存态仍生效，不中断程序

    def _rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
