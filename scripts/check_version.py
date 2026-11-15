# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。

"""版本号一致性校验。

版本号原先散在四处，只靠人记着一起改：
    src/meta.py 的 VERSION
    docs/CHANGELOG.md 顶部的最新条目
    README.md 的徽标行
    docs/ARCHITECTURE.md 抬头

跑法：
    .venv\\Scripts\\python.exe scripts/check_version.py

不一致时以退出码 1 结束，方便挂到打包前或 CI 上。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text("utf-8")


def collect() -> dict[str, str]:
    found: dict[str, str] = {}

    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', _read("src/meta.py"), re.M)
    if m:
        found["src/meta.py"] = m.group(1)

    m = re.search(r"^##\s*\[([0-9][^\]]*)\]", _read("docs/CHANGELOG.md"), re.M)
    if m:
        found["docs/CHANGELOG.md"] = m.group(1)

    m = re.search(r"版本\s*v([0-9][0-9.]*)", _read("README.md"))
    if m:
        found["README.md"] = m.group(1)

    m = re.search(r"Album\s+v([0-9][0-9.]*)", _read("docs/ARCHITECTURE.md"))
    if m:
        found["docs/ARCHITECTURE.md"] = m.group(1)

    return found


def main() -> int:
    found = collect()
    for path, ver in found.items():
        print(f"  {path:<26} {ver}")

    if not found:
        print("没有找到任何版本号，检查正则是否与文件格式匹配")
        return 1

    values = set(found.values())
    if len(values) != 1:
        print(f"\n版本号不一致：{sorted(values)}")
        return 1
    print(f"\n一致：{values.pop()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
