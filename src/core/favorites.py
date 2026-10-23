# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""最爱配置：favorites.json 跟随图片目录存放，只记相对路径。

数据结构（v2，向后兼容 v1）：
    {
      "version": 2,
      "items": [
        {"path": "sub/a.jpg", "added": "2026-10-23T15:00:00", "updated_at": 1729584000000}
      ]
    }

`updated_at` 是毫秒时间戳，用于与服务端做 LWW 合并（时间戳大者胜）。
v1 文件没有这个字段，加载时按 `added` 推一个近似值，保证老数据仍可用。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

FILE_NAME = "favorites.json"


def _ms_from_iso(text: str) -> int:
    """把 'added' 的 ISO 时间转成毫秒；解析失败返回 0。"""
    try:
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except (ValueError, TypeError, OSError):
        return 0


class FavoritesStore:
    def __init__(self, root: Path):
        self.root = root
        # 相对路径(posix) -> {"added": str, "updated_at": int}
        self.items: dict[str, dict] = {}
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
                rel = str(it["path"])
                added = str(it.get("added", ""))
                # v1 没有 updated_at：用 added 推一个近似值
                ts = it.get("updated_at")
                if not isinstance(ts, int):
                    ts = _ms_from_iso(added)
                self.items[rel] = {"added": added, "updated_at": ts}
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

    def keys(self) -> set[str]:
        """所有收藏的相对路径集合（供同步比对）。"""
        return set(self.items.keys())

    def updated_at(self, key: str) -> int:
        rec = self.items.get(key)
        return int(rec.get("updated_at") or 0) if rec else 0

    def toggle(self, abs_path: Path) -> bool:
        """切换最爱状态，落盘并返回新状态。"""
        key = self._rel(abs_path)
        if key in self.items:
            del self.items[key]
            new_state = False
        else:
            self.items[key] = {
                "added": datetime.now().isoformat(timespec="seconds"),
                "updated_at": int(datetime.now().timestamp() * 1000),
            }
            new_state = True
        self.save()
        return new_state

    def set_state(self, key: str, favorite: bool, updated_at: int) -> bool:
        """按 LWW 应用一条远端状态。返回是否真的改了本地。

        只有远端时间戳严格更大时才覆盖，避免两端来回打架。"""
        cur = self.items.get(key)
        cur_ts = int(cur.get("updated_at") or 0) if cur else 0
        if updated_at <= cur_ts:
            return False
        if favorite:
            if cur is None:
                self.items[key] = {
                    "added": datetime.now().isoformat(timespec="seconds"),
                    "updated_at": updated_at,
                }
                return True
            cur["updated_at"] = updated_at
            return True
        # 远端是「取消收藏」
        if cur is not None:
            del self.items[key]
            return True
        return False

    def save(self) -> None:
        if self._readonly:
            # 原文件损坏已另存 .corrupt；这里不覆盖，避免把用户数据彻底抹掉
            return
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            data = {
                "version": 2,
                "items": [
                    {"path": k, "added": v.get("added", ""),
                     "updated_at": int(v.get("updated_at") or 0)}
                    for k, v in self.items.items()
                ],
            }
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
