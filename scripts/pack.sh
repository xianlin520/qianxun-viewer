#!/usr/bin/env bash
# 千寻影集 QianXun Album
# 版权所有 (C) 羡林i (Y_XianLin)，保留所有权利。
#
# 打包脚本：先出单文件版，再出目录版，最后把快捷方式指向的 dist/QianXunViewer.exe
# 同步成新版本。
#
# 用法（任意目录下都可以）：
#   bash scripts/pack.sh
#
# 脚本自己定位项目根，不写死路径，项目挪位置不用改这里。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=./.venv/Scripts/python.exe
PIC=./.venv/Scripts/pyinstaller.exe

if [ ! -x "$PY" ]; then
  echo "找不到虚拟环境：$ROOT/.venv" >&2
  echo "先建环境：python -m venv .venv && ./.venv/Scripts/python.exe -m pip install -r requirements.lock" >&2
  exit 1
fi

VER=$("$PY" -c "import sys;sys.path.insert(0,'.');from src.meta import VERSION;print(VERSION)")
echo "===== 版本 $VER ====="
"$PY" scripts/check_version.py

rm -rf dist-build

echo "===== 1/2 onefile ====="
QX_ONEFILE=1 "$PIC" --noconfirm --distpath dist-build --workpath build QianXunViewer.spec 2>&1 | tail -3
cp dist-build/QianXunViewer.exe "dist/QianXunViewer-v$VER.exe"
ls -l "dist/QianXunViewer-v$VER.exe"

echo "===== 2/2 onedir ====="
"$PIC" --noconfirm --distpath dist-build --workpath build QianXunViewer.spec 2>&1 | tail -3
"$PY" - "$VER" <<'PY'
import sys, zipfile, pathlib
ver = sys.argv[1]
src = pathlib.Path("dist-build/QianXunViewer")
out = pathlib.Path(f"dist/QianXunViewer-v{ver}-win64.zip")
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(src.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(src.parent))
print("zip:", out, f"{out.stat().st_size/1e6:.1f} MB")
PY

echo "===== 尝试更新快捷方式指向的 dist/QianXunViewer.exe ====="
if cp "dist/QianXunViewer-v$VER.exe" dist/QianXunViewer.exe 2>/dev/null; then
  echo "已更新（程序当时未在运行）"
else
  echo "被占用，未更新。关闭程序后从 dist/QianXunViewer-v$VER.exe 复制即可"
fi

echo "===== 完成 ====="
ls -l "dist/QianXunViewer-v$VER.exe" "dist/QianXunViewer-v$VER-win64.zip"
