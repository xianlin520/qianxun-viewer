# 千寻图片查看器 QianXun Viewer
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""阿里云 OSS 集成：上传 / 列表 / 签名 / 下载 + 增量上传索引。"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import quote
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


def oss_region(endpoint: str) -> str:
    """从 Endpoint 推导 OSS 地域：oss-cn-qingdao.aliyuncs.com → cn-qingdao。

    推导不出时返回空串（自定义域名 / 加速域名），此时退回 V1 签名。"""
    host = endpoint.strip().split("//")[-1].split("/")[0].lower()
    if not host.endswith("aliyuncs.com"):
        return ""
    seg = host.split(".")[0]
    if not seg.startswith("oss-"):
        return ""
    region = seg[len("oss-"):]
    for suffix in ("-internal", "-vpc", "-intranet"):
        if region.endswith(suffix):
            region = region[: -len(suffix)]
    return "" if region.startswith("accelerate") else region


_ERROR_HINTS = (
    ("v1 signature is forbidden",
     "该 Bucket 只接受 V4 签名：Endpoint 请填地域域名（如 https://oss-cn-qingdao.aliyuncs.com）"),
    ("does not belong to you",
     "地域不匹配或 RAM 权限不足：核对 Bucket 地域与 Endpoint，并授予 oss:ListObjects、oss:GetBucketInfo"),
    ("no right to access this object",
     "对象操作被拒：请给 AccessKey 授予 oss:DeleteObject 等对象级权限"),
    ("secondleveldomainforbidden", "Endpoint 与 Bucket 地域不匹配"),
    ("nosuchbucket", "Bucket 不存在：核对名称与地域"),
    ("signaturedoesnotmatch", "AccessKey Secret 不正确"),
    ("invalidaccesskeyid", "AccessKey ID 不存在或已禁用"),
)


def friendly_error(exc) -> str:
    """把 OSS 报错压成一行并附可操作提示（原始 dict 报错直接展示会很长）。"""
    text = str(exc)
    details = getattr(exc, "details", None)
    # 类型化异常（AccessDenied 等）details 即内层字典；
    # 通用 ServerError 则多包一层 {'status':…, 'details': {…}}。
    if isinstance(details, dict) and isinstance(details.get("details"),
                                               (dict, str)):
        details = details["details"]
    if isinstance(details, dict):
        code = str(details.get("Code") or "")
        msg = str(details.get("Message") or "")
        if code or msg:
            text = ": ".join(x for x in (code, msg) if x)
    else:
        m = re.search(r"'Code':\s*'([^']+)'.*?'Message':\s*'([^']*)'",
                      text, re.S)
        if m:
            text = f"{m.group(1)}: {m.group(2)}"
    low = text.lower().replace(" ", "")
    for needle, hint in _ERROR_HINTS:
        if needle.replace(" ", "") in low:
            return f"{text[:160]}｜提示：{hint}"
    return text[:200]


class OssIndex:
    """本地增量上传索引：sha1(路径|大小|mtime) -> {key, size, mtime, at}。

    按 Bucket 分文件存放，换桶后不会误用旧桶的记录。"""

    def __init__(self, bucket: str = "") -> None:
        safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in bucket)
        name = f"oss_index_{safe}.json" if safe else "oss_index.json"
        self.path = app_data_dir() / name
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
        self.region = oss_region(endpoint)
        if self.region and hasattr(oss2, "AuthV4"):
            # 新开通/新建的 Bucket 仅接受 V4 签名（旧桶同样兼容 V4）
            auth = oss2.AuthV4(ak_id, ak_secret)
        else:
            auth = oss2.Auth(ak_id, ak_secret)
        try:
            self.bucket = oss2.Bucket(auth, endpoint, bucket,
                                      region=self.region or None)
        except TypeError:   # 老版本 oss2 不接受 region 参数
            self.bucket = oss2.Bucket(auth, endpoint, bucket)

    def test(self) -> str:
        info = self.bucket.get_bucket_info()
        return getattr(info, "name", self.bucket_name) or self.bucket_name

    def head(self, key: str) -> bool:
        try:
            self.bucket.head_object(key)
            return True
        except Exception:
            return False

    def list_keys(self) -> set:
        """一次列举全部对象 key（上传前去重用）。"""
        try:
            return {o.key for o in self._oss2.ObjectIterator(self.bucket)}
        except Exception:
            return set()

    def list_images(self, max_workers: int = 8) -> list:
        """返回 [(key, size, last_modified, width, height)]。

        列举整个 Bucket（任意文件夹下的图片都纳入），
        跳过目录占位对象与非图片文件。"""
        objs = [o for o in self._oss2.ObjectIterator(self.bucket)
                if not o.key.endswith("/")
                and Path(o.key).suffix.lower() in IMAGE_EXTS]

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

    def public_url(self, key: str) -> str:
        """对象公共读后的永久直链（需先 make_public）。"""
        host = self.bucket.endpoint.split("//", 1)[-1].rstrip("/")
        return f"https://{self.bucket_name}.{host}/{quote(key, safe='/')}"

    def make_public(self, key: str) -> None:
        """单个对象设为公共读（桶可保持私有）。"""
        self.bucket.put_object_acl(key, self._oss2.OBJECT_ACL_PUBLIC_READ)

    def revoke_public(self, key: str) -> None:
        """撤回公共读（对象 ACL 恢复继承桶权限）。"""
        self.bucket.put_object_acl(key, self._oss2.OBJECT_ACL_DEFAULT)

    def is_public(self, key: str) -> bool:
        try:
            return self.bucket.get_object_acl(key).acl == "public-read"
        except Exception:
            return False

    def delete_object(self, key: str) -> None:
        """删除云端对象（不可逆，调用方需自行确认）。"""
        self.bucket.delete_object(key)

    def download_to(self, key: str, dest: Path, thumb: int = 0) -> None:
        self.bucket.get_object_to_file(key, str(dest),
                                       process=self._process(thumb))

    def upload(self, local: Path, key: str, cb=None) -> None:
        self._oss2.resumable_upload(self.bucket, key, str(local),
                                    part_size=8 * 1024 * 1024, num_threads=2,
                                    progress_callback=cb)
