# 桌面壳

本目录同时容纳两条桌面壳实现，它们共用同一套约定：

- 启动时拉起 Python 本地服务（`backend/app/main.py`）
- **动态分配端口**（车间可能同时开浏览器版或第二个实例，写死端口会互相抢占）
- 把实际 API 地址交给前端（Electron 走预加载桥，Tauri 走 `api_base_url` 命令）
- 退出时回收子进程，不留孤儿进程占端口

后端目录解析顺序（两条壳一致）：

1. 环境变量 `PHARMRELATE_BACKEND_DIR` / `PHARMRELATE_PYTHON`
2. 可执行文件同级的 `backend/`（打包态）
3. 源码仓库中的 `backend/`（开发态）

## Electron（当前使用）

```powershell
cd desktop
npm run dev      # 开发态：连接 http://localhost:5173
npm run smoke    # 冒烟：拉后端、校验关键接口，然后退出（可自动化验证）
```

## Tauri 2（备选，源码完整但本机无法构建）

`src-tauri/` 下的实现是完整的（sidecar 管理 + `api_base_url` 命令 + 退出回收），
但在本机 cargo 反复报错：

```
could not execute process ...\build-script-build (never executed)
Caused by: 另一个程序正在使用此文件，进程无法访问。 (os error 32)
```

换 `CARGO_TARGET_DIR` 到 `%LOCALAPPDATA%` 后仍然出现，判定为本机实时防护
在扫描新生成的构建脚本可执行文件，属环境问题。详见 `docs/00-决策记录.md` 的 D-006。

环境修复后可这样验证：

```powershell
cd desktop
npm run tauri        # tauri dev
npm run tauri:build  # 出安装包
```
