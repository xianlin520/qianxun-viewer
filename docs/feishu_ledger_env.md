## 五、开发环境与路径

2026-11-19 起项目在 `E:\AiAgentWork\QianxunWork\qianxun-viewer`，旧位置 `E:\QoderWork\qianxun-viewer` 已删除。

- **虚拟环境**：位置变了必须重建。`pip.exe`、`pyinstaller.exe`、`activate.bat` 这些启动器把解释器绝对路径写死在文件里，直接挪目录会指向旧路径。重建后按 `requirements.lock` 装回 31 个包，版本与迁移前一致。
- **打包**：`bash scripts/pack.sh`，自己定位项目根，一次出单文件版与目录版，并同步 `dist/QianXunViewer.exe`。项目再换位置不用改脚本。
- **测试**：`./.venv/Scripts/python.exe -m unittest discover -s tests`（纯逻辑 47 条）、`./.venv/Scripts/python.exe tests/smoke_app.py`（窗口冒烟 10 项）、`cd server && node --test tests/boundary.test.js`（服务端 38 条）。
- **快捷方式**：`E:\AiAgentWork\APP\千寻影集.lnk` 指向 `dist\QianXunViewer.exe`，迁移后已改指新位置并读回核对。
- **用户配置**：仍在 `%APPDATA%\QianXun\QianXunViewer.ini` 与 `%LOCALAPPDATA%\QianXunViewer\`，不随项目走，迁移后无需重填。
- **本仓库剩余引用**：`docs/REVIEW_HANDOFF.md`、`docs/feishu_project_doc.md` 里的绝对路径已改成新位置；`build/` 是 PyInstaller 中间产物，内含大量旧路径，已清空待重建。

迁移后核对：客户端 47 条、服务端 38 条、冒烟 10 项全过，版本一致性 1.7.2，新路径 exe 离屏启动存活、退出后出网日志无新增。
