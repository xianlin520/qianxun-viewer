# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""阿里云 OSS 集成：上传 / 列表 / 签名 / 下载 + 增量上传索引。"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
PREFIX = "qx/"
SHARE_EXPIRES = 7 * 24 * 3600   # 外链最长 7 天


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA",
                               str(Path.home() / "AppData" / "Local")))
    d = base / "QianXunViewer"
    d.mkdir(parents=True, exist_ok=True)
    return d


class OssIndex:
    """本地增量上传索引：sha1(路径|大小|mtime) -> {key, size, mtime, at}。"""

    def __init__(self) -> None:
        self.path = app_data_dir() / "oss_index.json"
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        try:
            self.data = json.loads(self.path.read_text("utf-8"))
        except Exception:
            self.data = {}

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False), "utf-8")
        except OSError:
            pass

    @staticmethod
    def make_key(rel: str) -> str:
        return PREFIX + Path(rel).as_posix()

    def get(self, ck: str):
        return self.data.get(ck)

    def put(self, ck: str, key: str, size: int, mtime: float) -> None:
        self.data[ck] = {"key": key, "size": size, "mtime": mtime,
                         "at": int(time.time())}


class OssLibrary:
    """OSS 操作封装（oss2 延迟导入，未配置在线功能时不要求安装）。"""

    def __init__(self, endpoint: str, bucket: str, ak_id: str,
                 ak_secret: str) -> None:
        import oss2
        self._oss2 = oss2
        self.bucket_name = bucket
        self.bucket = oss2.Bucket(oss2.Auth(ak_id, ak_secret), endpoint, bucket)

    def test(self) -> str:
        info = self.bucket.get_bucket_info()
        return getattr(info, "name", self.bucket_name) or self.bucket_name

    def head(self, key: str) -> bool:
        try:
            self.bucket.head_object(key)
            return True
        except Exception:
            return False

    def list_images(self, max_workers: int = 8) -> list:
        """返回 [(key, size, last_modified, width, height)]。"""
        objs = [o for o in self._oss2.ObjectIterator(self.bucket, prefix=PREFIX)
                if Path(o.key).suffix.lower() in IMAGE_EXTS]

        def info(o):
            try:
                r = self.bucket.get_object(
                    o.key, params={"x-oss-process": "image/info"})
                d = json.loads(r.read())
                w = int(d["ImageWidth"]["value"])
                h = int(d["ImageHeight"]["value"])
            except Exception:
                w = h = 0
            return (o.key, o.size, o.last_modified, w, h)

        with ThreadPoolExecutor(max_workers) as ex:
            return list(ex.map(info, objs))

    @staticmethod
    def _process(size: int) -> str | None:
        if not size:
            return None
        return f"image/resize,m_lfit,w_{size},h_{size}/format,jpg"

    def sign(self, key: str, expires: int = 3600, thumb: int = 0) -> str:
        params = {"x-oss-process": self._process(thumb)} if thumb else None
        return self.bucket.sign_url("GET", key, expires, params=params,
                                    slash_safe=True)

    def download_to(self, key: str, dest: Path, thumb: int = 0) -> None:
        self.bucket.get_object_to_file(key, str(dest),
                                       process=self._process(thumb))

    def upload(self, local: Path, key: str, cb=None) -> None:
        self._oss2.resumable_upload(self.bucket, key, str(local),
                                    part_size=8 * 1024 * 1024, num_threads=2,
                                    progress_callback=cb)
