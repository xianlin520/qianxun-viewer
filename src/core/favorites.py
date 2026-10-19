# 千寻影集 QianXun Album
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
        self._readonly = False           # 原文件损坏时置位，禁止覆盖
        self.load()

    @property
    def path(self) -> Path:
        return self.root / FILE_NAME

    def load(self) -> None:
        self.items = {}
        try:
            data = json.loads(self.path.read_text("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("favorites.json 顶层不是对象")
            for it in data.get("items", []):
                self.items[str(it["path"])] = str(it.get("added", ""))
        except FileNotFoundError:
            self.items = {}
        except Exception:
            # 解析失败**不能**当成「空收藏」继续跑：下一次 toggle 会用空内存态
            # 覆盖掉用户全部最爱。这里把坏文件另存备份、只读保存，等用户处理。
            self.items = {}
            self._readonly = True
            try:
                self.path.replace(
                    self.path.with_suffix(self.path.suffix + ".corrupt"))
            except OSError:
                pass

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
        if self._readonly:
            # 原文件损坏已另存 .corrupt；这里不覆盖，避免把用户数据彻底抹掉
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            data = {"version": 1,
                    "items": [{"path": k, "added": v} for k, v in self.items.items()]}
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(self.path)     # 原子替换，避免并发读读到半个 JSON
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            # 目录只读等场景：内存态仍生效，不中断程序

    def _rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
