# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""客户端纯逻辑测试。

跑法（项目根目录）：

    ./.venv/Scripts/python.exe -m unittest discover -s tests -v

只测不依赖 QWidget 的模块：查重索引、收藏路径换算、设置项描述符、
滚轮量纲、扩展名集合。视图层（grid_view / wall_view / viewer）需要真
窗口才能实例化，尚未纳入。

这些用例锁的是「改一处、漏一处」型缺陷：同一份规则在两个地方各写一遍，
漂移时不报错，只静默降级。
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import json
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import duplicates as DUP          # noqa: E402
from src.core.favorites import FavoritesStore   # noqa: E402
from src.core.formats import IMAGE_EXTS         # noqa: E402


class _Fake:
    """查重只用到 phash 字段。"""

    __slots__ = ("phash", "name")

    def __init__(self, h: int, name: str) -> None:
        self.phash = f"{h:016x}"
        self.name = name


def _brute(items, threshold):
    """O(n²) 参照实现，与索引版逐组比对。"""
    hashed = [(it, int(it.phash, 16)) for it in items if it.phash]
    reps, members = [], []
    for it, h in hashed:
        for ci, r in enumerate(reps):
            if bin(h ^ r).count("1") <= threshold:
                members[ci].append(it)
                break
        else:
            reps.append(h)
            members.append([it])
    return [m for m in members if len(m) > 1]


def _signature(groups):
    return sorted(sorted(x.name for x in g) for g in groups)


class TestDuplicates(unittest.TestCase):
    def test_masks_are_cached_per_k_not_per_hash(self):
        """缓存的是掩码（只与 k 有关），不是邻居集合（随指纹变化）。

        后者在 k=3 时单条 697 个值，8192 条会涨到 200MB 以上。
        """
        DUP._flip_masks.cache_clear()
        for k in (0, 1, 2, 3):
            DUP._flip_masks(k)
        self.assertEqual(len(DUP._flip_masks(0)), 1)
        self.assertEqual(len(DUP._flip_masks(1)), 17)     # 1 + C(16,1)
        self.assertEqual(len(DUP._flip_masks(2)), 137)    # + C(16,2)
        self.assertEqual(len(DUP._flip_masks(3)), 697)    # + C(16,3)
        self.assertLessEqual(DUP._flip_masks.cache_info().currsize, 4)

    def test_neighbourhood_matches_hamming(self):
        for k in (0, 1, 2, 3):
            got = set(DUP._close_band_values(0xABCD, k))
            want = {v for v in range(1 << 16)
                    if bin(v ^ 0xABCD).count("1") <= k} if k == 0 else None
            if want is not None:
                self.assertEqual(got, want)
            else:
                for v in got:
                    self.assertLessEqual(bin(v ^ 0xABCD).count("1"), k)

    def test_groups_match_brute_force_across_thresholds(self):
        rng = random.Random(20261115)
        for threshold in (0, 2, 4, 6, 8, 10, 12):
            base = rng.getrandbits(64)
            items = [_Fake(base if rng.random() < 0.3 else rng.getrandbits(64), f"i{i}")
                     for i in range(120)]
            self.assertEqual(
                _signature(DUP.find_groups(items, threshold)),
                _signature(_brute(items, threshold)),
                f"threshold={threshold} 与暴力法不一致")

    def test_all_distinct_gives_no_groups(self):
        rng = random.Random(5)
        items = [_Fake(rng.getrandbits(64), f"i{i}") for i in range(300)]
        self.assertEqual(DUP.find_groups(items, 4), [])

    def test_cancellation_returns_empty(self):
        rng = random.Random(9)
        items = [_Fake(rng.getrandbits(64), f"i{i}") for i in range(2000)]
        self.assertEqual(DUP.find_groups(items, 4, is_cancelled=lambda: True), [])

    def test_threshold_beyond_supported_range_is_clamped(self):
        """k 被截断时同步夹回 threshold，否则鸽巢前提失效会漏组。"""
        rng = random.Random(13)
        base = rng.getrandbits(64)
        items = [_Fake(base, "a"), _Fake(base ^ 0b111, "b")]
        # 距离 3，阈值 20 与阈值 12 都应把它们并成一组
        self.assertEqual(_signature(DUP.find_groups(items, 20)),
                         _signature(DUP.find_groups(items, 12)))


class TestFavoritesRel(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "lib"
        (self.root / "sub").mkdir(parents=True)
        self.store = FavoritesStore(self.root)

    def test_inside_root(self):
        self.assertEqual(self.store._rel(self.root / "a.jpg"), "a.jpg")
        self.assertEqual(self.store._rel(self.root / "sub" / "b.jpg"), "sub/b.jpg")

    def test_outside_root_kept_absolute(self):
        outside = self.tmp / "elsewhere.jpg"
        self.assertEqual(self.store._rel(outside), outside.as_posix())

    def test_sibling_with_same_prefix_is_not_inside(self):
        """lib2 不能被判成 lib 的子路径（前缀比较最容易在这里出错）。

        判据是返回值仍为绝对路径，而不是被削成 "x.jpg"。
        """
        sibling = self.tmp / "lib2" / "x.jpg"
        got = self.store._rel(sibling)
        self.assertNotEqual(got, "x.jpg", "lib2 被误判为 lib 内部路径")
        self.assertEqual(got, sibling.as_posix())

    def test_contains_and_toggle(self):
        self.assertFalse(self.store.contains(self.root / "a.jpg"))
        self.assertTrue(self.store.toggle(self.root / "a.jpg"))
        self.assertTrue(self.store.contains(self.root / "a.jpg"))
        self.assertFalse(self.store.toggle(self.root / "a.jpg"))

    def test_rel_does_not_hit_filesystem_per_image(self):
        """换算走字符串前缀比较，不调 realpath。

        调 resolve() 时本机实测 1.92ms/次，千张库单次筛选要 2.9 秒。
        """
        store = FavoritesStore(self.root)
        import time
        t0 = time.perf_counter()
        for i in range(500):
            store._rel(self.root / f"img{i}.jpg")
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.5, f"500 张换算耗时 {elapsed:.3f}s，疑似又走了 realpath")


class TestSettingsFields(unittest.TestCase):
    def test_every_field_key_equals_its_name(self):
        """键名由字段名派生，只有一处定义。

        旧实现里键名在 getter 与 setter 各写一遍，改名漏改一侧会「读旧键
        写新键」，静默不一致，而且两个键还是加密存储的。
        """
        from src.core.settings import AppSettings
        fields = AppSettings.fields()
        # 不钉死总数（加设置项不该改测试），只钉住不可缺失的关键项
        must_have = {
            "default_open_dir", "default_save_dir", "view_mode", "sort_mode",
            "thumb_size", "dup_threshold", "window_geo", "oss_endpoint",
            "oss_bucket", "oss_ak_id", "oss_ak_secret", "upload_threads",
            "upload_skip_dups", "share_days", "scan_parallel", "auto_load_last",
            "server_base", "server_secret", "server_enabled",
            "skipped_version", "check_updates", "theme",
        }
        missing = must_have - set(fields)
        self.assertFalse(missing, f"设置项缺失：{sorted(missing)}")
        for name, f in fields.items():
            self.assertEqual(f.name, name)

    def test_protected_fields_are_marked(self):
        from src.core.settings import AppSettings
        fields = AppSettings.fields()
        protected = {n for n, f in fields.items() if f.protect}
        self.assertEqual(protected, {"oss_ak_secret", "server_secret"})

    def test_theme_field(self):
        from src.core.settings import AppSettings
        f = AppSettings.fields()["theme"]
        self.assertEqual(f.default, "dark")
        self.assertEqual(f.normalize("  LIGHT  "), "light")

    def test_clamped_fields(self):
        from src.core.settings import AppSettings
        fields = AppSettings.fields()
        self.assertEqual((fields["upload_threads"].lo, fields["upload_threads"].hi), (1, 8))
        self.assertEqual((fields["share_days"].lo, fields["share_days"].hi), (1, 7))
        self.assertEqual((fields["scan_parallel"].lo, fields["scan_parallel"].hi), (1, 16))




class TestNetGuard(unittest.TestCase):
    """本地模式是默认状态，也是最容易被后续改动破坏的一处。"""

    def setUp(self):
        from src.core import netguard
        self.ng = netguard
        self.ng.reset_stats()
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "egress.log"
        self._p1 = mock.patch.object(netguard, "log_path", lambda: self.log)
        self._p1.start()

    def tearDown(self):
        self._p1.stop()
        self._tmp.cleanup()

    def _local(self, on: bool):
        return mock.patch.object(self.ng, "is_local_only", lambda: on)

    def test_default_blocks_all_scopes(self):
        with self._local(True):
            for scope in ("update", "server", "oss"):
                with self.assertRaises(self.ng.OfflineError, msg=scope):
                    self.ng.require(scope, "https://example.com/x")
            st = self.ng.stats()
            for scope in ("update", "server", "oss"):
                self.assertEqual(st[scope]["blocked"], 1)
                self.assertEqual(st[scope]["allowed"], 0)

    def test_blocked_message_is_user_facing(self):
        with self._local(True):
            with self.assertRaises(self.ng.OfflineError) as ctx:
                self.ng.require("oss", "oss-cn-hangzhou.aliyuncs.com")
        msg = str(ctx.exception)
        self.assertIn("本地模式", msg)
        self.assertIn("对象存储", msg)

    def test_online_allows_and_counts(self):
        with self._local(False):
            self.ng.require("server", "https://example.com/api")
        self.assertEqual(self.ng.stats()["server"]["allowed"], 1)
        self.assertEqual(self.ng.stats()["server"]["blocked"], 0)

    def test_log_records_host_only(self):
        with self._local(True):
            with self.assertRaises(self.ng.OfflineError):
                self.ng.require("server",
                                "https://img.example.com/api/shares?limit=5&oss_key=qx/h/abc.jpg")
        line = self.log.read_text("utf-8").strip().splitlines()[-1]
        rec = json.loads(line)
        self.assertEqual(rec["host"], "img.example.com")
        self.assertTrue(rec["blocked"])
        self.assertEqual(rec["scope"], "server")
        # 路径与查询串不得进日志：那里可能带着图片名
        self.assertNotIn("oss_key", line)
        self.assertNotIn("abc.jpg", line)

    def test_blocked_never_reaches_transport(self):
        """拦截必须在发请求之前：用假 urlopen 断言一次都没被调用。"""
        import urllib.request
        calls = []
        with mock.patch.object(urllib.request, "urlopen",
                               lambda *a, **k: calls.append(a)):
            with self._local(True):
                from src.core.share_server import ShareServer
                srv = ShareServer("https://img.example.com", "secret")
                ok, msg = srv.list_shares(limit=1)
                ok_h, msg_h = srv.health()
                self.assertFalse(ok_h, "health 也必须被拦")
                self.assertIn("本地模式", msg_h)
                from src.core.updater import check_latest
                info, err = check_latest()
        self.assertFalse(ok)
        self.assertIn("本地模式", msg)
        self.assertIsNone(info)
        self.assertIn("本地模式", err)
        self.assertEqual(calls, [], "本地模式下不应有任何 urlopen 调用")

    def test_unknown_scope_rejected(self):
        with self.assertRaises(ValueError):
            self.ng.require("ftp", "example.com")


class TestCloudKeyPrivacy(unittest.TestCase):
    """云端 key 不该携带目录名与文件名。"""

    def test_hash_key_hides_names(self):
        from src.core.oss_service import OssIndex
        key = OssIndex.make_key("2024/旅行/三亚/DSC_0001.JPG")
        self.assertNotIn("旅行", key)
        self.assertNotIn("三亚", key)
        self.assertNotIn("DSC_0001", key)
        self.assertTrue(key.startswith("qx/h/"))
        self.assertTrue(key.endswith(".jpg"), "扩展名保留，否则取图时类型判错")

    def test_hash_key_stable_across_calls(self):
        from src.core.oss_service import OssIndex
        a = OssIndex.make_key("a/b.jpg")
        b = OssIndex.make_key("a/b.jpg")
        self.assertEqual(a, b)

    def test_hash_key_differs_by_path(self):
        from src.core.oss_service import OssIndex
        self.assertNotEqual(OssIndex.make_key("a/b.jpg"),
                            OssIndex.make_key("a/c.jpg"))

    def test_path_mode_keeps_structure(self):
        from src.core.oss_service import OssIndex
        self.assertEqual(OssIndex.make_key("2024/旅行/a.jpg", "path"),
                         "qx/2024/旅行/a.jpg")

    def test_default_mode_is_hash(self):
        from src.core.settings import AppSettings
        self.assertEqual(AppSettings.fields()["oss_key_mode"].default, "hash")

    def test_remote_key_hides_path(self):
        from src.core.favorites import remote_key
        k = remote_key("2024/旅行/三亚/DSC_0001.JPG")
        self.assertEqual(len(k), 24)
        self.assertNotIn("旅行", k)
        self.assertNotIn("/", k)

    def test_local_only_default_on(self):
        from src.core.settings import AppSettings
        self.assertIs(AppSettings.fields()["local_only"].default, True)


class TestFavoritesCursor(unittest.TestCase):
    """游标必须带 key：updated_at 不唯一，只给时间会跳过同毫秒的边界记录。"""

    def _srv(self):
        from src.core.share_server import ShareServer
        srv = ShareServer("https://x.test", "secret")
        seen = {}

        def fake(method, target, payload=None, timeout=None):
            seen["target"] = target
            # 线上真实字段名，故意用 snake_case：契约就在这一层
            return True, {"items": [], "next_cursor": 1000, "next_key": "a/b.jpg"}

        srv._request = fake
        return srv, seen

    def test_after_key_is_sent(self):
        srv, seen = self._srv()
        ok, (items, cursor, key) = srv.pull_favorites(after=1000, after_key="a/b.jpg")
        self.assertTrue(ok)
        self.assertIn("after=1000", seen["target"])
        self.assertIn("after_key=a%2Fb.jpg", seen["target"])
        self.assertEqual((cursor, key), (1000, "a/b.jpg"))

    def test_without_key_only_after(self):
        srv, seen = self._srv()
        srv.pull_favorites(after=1000)
        self.assertEqual(seen["target"], "/api/favorites?after=1000")

    def test_pull_all_passes_key_forward(self):
        from src.core.share_server import ShareServer
        srv = ShareServer("https://x.test", "secret")
        calls = []

        def fake(method, target, payload=None, timeout=None):
            calls.append(target)
            if len(calls) == 1:
                return True, {"items": [{"key": "a", "favorite": True, "updated_at": 1}],
                              "next_cursor": 1, "next_key": "a"}
            return True, {"items": [{"key": "b", "favorite": False, "updated_at": 1}],
                          "next_cursor": None, "next_key": None}

        srv._request = fake
        ok, items = srv.pull_all_favorites()
        self.assertTrue(ok)
        self.assertEqual([i["key"] for i in items], ["a", "b"])
        self.assertIn("after_key=a", calls[1])


class TestThemePalettes(unittest.TestCase):
    def test_palettes_have_identical_keys(self):
        """两套调色板键必须一致，否则某个主题下会取到空色值。"""
        from src.ui import theme

        self.assertEqual(set(theme.PALETTES["dark"]), set(theme.PALETTES["light"]))

    def test_every_palette_key_is_a_module_name(self):
        from src.ui import theme

        for name in theme.PALETTES["dark"]:
            self.assertTrue(hasattr(theme, name), f"theme 里没有 {name}")

    def test_apply_palette_switches_module_values(self):
        """自绘代码读的是 theme.X，切换后必须拿到新值。"""
        from src.ui import theme

        try:
            theme.apply_palette("dark")
            dark_bg = theme.BG_APP
            theme.apply_palette("light")
            self.assertNotEqual(theme.BG_APP, dark_bg)
            self.assertEqual(theme.BG_APP, theme.PALETTES["light"]["BG_APP"])
            # QSS 占位符表要跟着更新，否则样式表还是旧色
            self.assertEqual(theme.QSS_VARS["BG_APP"], theme.BG_APP)
        finally:
            theme.apply_palette("dark")

    def test_unknown_palette_falls_back_to_default(self):
        from src.ui import theme

        try:
            theme.apply_palette("no-such-theme")
            self.assertEqual(theme.current_palette(), theme.DEFAULT_PALETTE)
        finally:
            theme.apply_palette("dark")

    def test_views_read_theme_at_paint_time(self):
        """视图必须 `theme.X`，不能 `from .theme import X`。

        后者在导入时把字符串绑死，换主题不生效 —— 这正是加浅色主题时
        在三个视图文件里发现的问题。
        """
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "src" / "ui"
        bad = []
        for f in ("grid_view.py", "wall_view.py", "viewer.py"):
            text = (root / f).read_text("utf-8")
            if re.search(r"^from \.theme import ", text, re.M):
                bad.append(f)
        self.assertFalse(bad, f"这些文件仍在导入时绑定色值：{bad}")


class TestWheelSteps(unittest.TestCase):
    def test_angle_delta_is_steps(self):
        from src.ui.input import WHEEL_UNIT, wheel_steps

        class Ev:
            def __init__(self, a, p=0):
                self._a, self._p = a, p

            def angleDelta(self):
                from PySide6.QtCore import QPoint
                return QPoint(0, self._a)

            def pixelDelta(self):
                from PySide6.QtCore import QPoint
                return QPoint(0, self._p)

        self.assertAlmostEqual(wheel_steps(Ev(int(WHEEL_UNIT))), 1.0)
        self.assertAlmostEqual(wheel_steps(Ev(-int(WHEEL_UNIT))), -1.0)

    def test_pixel_delta_falls_back_to_pixels(self):
        from src.ui.input import PIXEL_RATIO, WHEEL_UNIT, wheel_steps

        class Ev:
            def __init__(self, p):
                self._p = p

            def angleDelta(self):
                from PySide6.QtCore import QPoint
                return QPoint(0, 0)

            def pixelDelta(self):
                from PySide6.QtCore import QPoint
                return QPoint(0, self._p)

        self.assertAlmostEqual(wheel_steps(Ev(40)), 40 * PIXEL_RATIO / WHEEL_UNIT)


class TestFormats(unittest.TestCase):
    def test_single_source(self):
        """新增格式只改一处。两处各写一份会「本地上传得了、在线库看不到」。"""
        from src.core import oss_service, scanner

        self.assertIs(scanner.IMAGE_EXTS, IMAGE_EXTS)
        self.assertIs(oss_service.IMAGE_EXTS, IMAGE_EXTS)

    def test_lowercase_with_dot(self):
        for ext in IMAGE_EXTS:
            self.assertTrue(ext.startswith("."))
            self.assertEqual(ext, ext.lower())


class TestRelFromKey(unittest.TestCase):
    def test_strips_prefix(self):
        from src.core.oss_service import PREFIX, rel_from_key

        self.assertEqual(rel_from_key(PREFIX + "a/b.jpg"), "a/b.jpg")

    def test_rejects_foreign_prefix(self):
        from src.core.oss_service import rel_from_key

        with self.assertRaises(ValueError):
            rel_from_key("notqx/a.jpg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
