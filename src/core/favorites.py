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
import os
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
        # 根目录只 resolve 一次。此前每张图都要 root.resolve() + p.resolve()，
        # 一次扫描上千张图就是两千次 realpath 系统调用（实测 1.92ms/次）。
        try:
            self._root_resolved = root.resolve()
        except OSError:
            self._root_resolved = root
        # 路径换算只做字符串前缀比较，不碰文件系统。
        # Path.resolve() 在 Windows 上要走 realpath，本机实测 1.92ms/次；
        # 扫描时每张图都要问一次「是否收藏」，千张库就是 2.9 秒。
        self._root_abs = os.path.abspath(str(root))
        self._rel_cache: dict[str, str] = {}
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
        key = str(p)
        cached = self._rel_cache.get(key)
        if cached is not None:
            return cached
        rel = self._rel_under(os.path.abspath(key))
        # 同一张图在一次会话里会被反复问（标记、渲染、同步比对），
        # 缓存结果避免重复 abspath。
        if len(self._rel_cache) < 200_000:
            self._rel_cache[key] = rel
        return rel

    def _rel_under(self, abs_key: str) -> str:
        """把绝对路径换算成相对图库根的 posix 路径；不在库里则原样返回。

        用 abspath 加前缀比较，不调 resolve()：后者是 realpath 系统调用，
        每张图一次就够把千张库的筛选拖到几秒。代价是不再展开符号链接与
        junction，与 controllers._item_folder 的取舍保持一致。
        """
        try:
            common = os.path.commonpath([self._root_abs, abs_key])
        except ValueError:
            return Path(abs_key).as_posix()
        if os.path.normcase(common) != os.path.normcase(self._root_abs):
            return Path(abs_key).as_posix()
        return Path(os.path.relpath(abs_key, self._root_abs)).as_posix()
