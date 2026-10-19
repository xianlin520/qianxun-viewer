# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""文件操作：另存为 / 复制剪贴板 / 定位文件 / 移入 Remove / 还原（可逆，不做删除）。"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REMOVE_DIR = "Remove"
REMOVED_MAP = ".qx_removed.json"   # Remove 内记录：移出后文件名 -> 原相对路径


def safe_join(root: Path, rel: str) -> Path | None:
    """把相对路径安全地拼到 root 下；路径穿越/绝对路径/无法解析时返回 None。

    Remove/.qx_removed.json 是可被外部编辑的文本，若其中写入
    "../../x.png" 或绝对路径，直接 join 会把文件还原到图片库之外。
    这里做归一化后校验公共前缀，越界一律拒绝（由调用方回退到根目录）。"""
    root_r = root.resolve()
    if not rel:
        return None
    try:
        base = Path(rel)
        if base.is_absolute():
            return None
        cand = (root_r / base).resolve()
        cand.relative_to(root_r)
    except (OSError, ValueError):
        return None
    return cand


def unique_path(dest_dir: Path, name: str) -> Path:
    """重名自动加 (1)/(2)… 后缀。"""
    target = dest_dir / name
    if not target.exists():
        return target
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        cand = dest_dir / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def save_as(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(dest_dir, src.name)
    shutil.copy2(src, target)
    return target


def move_to_remove(src: Path, image_root: Path) -> Path:
    """移动到图片根目录下 Remove/，重名自动加后缀，并记录原路径以便还原。"""
    remove_dir = image_root / REMOVE_DIR
    remove_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(remove_dir, src.name)
    shutil.move(str(src), str(target))
    try:
        rel = src.resolve().relative_to(image_root.resolve()).as_posix()
    except ValueError:
        rel = src.name       # 不在库内：只记文件名，还原时落回根目录
    mapping = _load_removed_map(remove_dir)
    mapping[target.name] = rel
    _save_removed_map(remove_dir, mapping)
    return target


def restore_from_remove(src: Path, image_root: Path) -> Path:
    """从 Remove/ 还原到原相对目录（目录不存在则重建，重名加后缀）。

    相对路径经 safe_join 归一化校验：即使 .qx_removed.json 被改成
    含 ../ 或绝对路径，也只会落回图片根目录，不会写出库外。"""
    remove_dir = image_root / REMOVE_DIR
    mapping = _load_removed_map(remove_dir)
    rel = mapping.get(src.name)
    target_file = safe_join(image_root, rel) if rel else None
    if target_file is not None:
        dest_dir = target_file.parent
        name = target_file.name or src.name
    else:
        # 无记录或记录越界：回落到图片根目录，绝不写到库外
        dest_dir = image_root
        name = src.name
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        dest_dir = image_root
        name = src.name
    target = unique_path(dest_dir, Path(name).name)
    shutil.move(str(src), str(target))
    mapping.pop(src.name, None)
    _save_removed_map(remove_dir, mapping)
    return target


def _load_removed_map(remove_dir: Path) -> dict:
    try:
        return json.loads((remove_dir / REMOVED_MAP).read_text("utf-8"))
    except Exception:
        return {}


def _save_removed_map(remove_dir: Path, mapping: dict) -> None:
    try:
        (remove_dir / REMOVED_MAP).write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
    except OSError:
        pass


def reveal_in_explorer(path: Path) -> None:
    # 列表参数避免中文路径引号问题
    subprocess.Popen(["explorer", "/select,", str(path)])


def copy_pixmap(pixmap) -> None:
    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setPixmap(pixmap)


def copy_file(path: Path) -> None:
    """复制文件对象到剪贴板（可粘贴到资源管理器）。"""
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QApplication
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(path))])
    QApplication.clipboard().setMimeData(md)
