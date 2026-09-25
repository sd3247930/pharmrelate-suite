# 籽关通 (PharmRelate Multi)

跨平台三级包装（箱 → 罐 → 粒子）关联管理系统。

当前处于**一期：Windows 端单机闭环**，已完成阶段 0（基准冻结）与阶段 1（工程骨架与设计系统）。

## 拍板结论（2026-09-25 确认）

| 项 | 结论 |
| --- | --- |
| D1 技术栈 | C 分层方案：Python FastAPI 本地服务 + Vue 3 前端，Electron 桌面壳（Tauri 2 备选） |
| D2 一期范围 | 仅 Windows 单机闭环；多端协同 / 云同步 / 审计 / 权限 / 加密推二期 |
| 扫码输入 | USB 摄像头连续帧多码 + 条码枪 HID 兜底 + 手动输入兜底 |
| XML 基准 | `backend/tests/golden/` 下两个真实 XML 为字节级黄金基准；PRD 内联样例视为笔误 |
| 固定参数 | `cascade="1:5:2500"` 等全部为不可编辑字面量，**不随实际结构变化** |
| 导出命名 | `Relation_{batchNo}_{yyyyMMddHHmmss}.xml` / `.html` |
| Windows 最低版本 | Windows 10 1909+ |
| 单文件 exe | 不强制，允许安装包 |
| 摄像头 | 先用本机 USB 摄像头，暂不配条码枪 |
| 提前结束签名 | 操作人下拉选择 + 备注文本 |

已采纳的补充规则：条码层级前缀校验、追溯码双段交叉校验。

一期虽不实现，但必须预留：`SyncMeta` 字段、`oplog` 表结构、设备/用户 ID 占位、
批次状态机中的 `exported / locked / archived / void` 状态。

完整决策与理由见 [docs/00-决策记录.md](docs/00-决策记录.md)。

## 目录结构

```
backend/                   Python 本地服务（FastAPI）
  app/domain/              业务模型、固定参数、校验规则（纯数据，无外部依赖）
  app/services/            XML 生成 / 解析 / 基准访问
  app/api/                 路由、统一错误格式、依赖注入
  app/repositories/        数据访问层（阶段 1 为内存实现）
  tests/golden/            字节级黄金基准 —— 请勿修改
  tests/fixtures/          独立手写锚点
  tools/                   基准比对 CLI、端到端冒烟测试
frontend/                  Vue 3 + Vite + TypeScript + Pinia 前端
  src/components/          App* 基础组件
  src/views/               5 个采集流程页面
  src/styles/tokens.css    设计令牌（唯一样式来源）
desktop/                   桌面壳（Electron 主壳 + Tauri 备选实现）
scripts/                   一键开发与一键检查脚本
docs/                      决策记录与阶段记录
private/                   需求文档与原始样例（只读输入区）
```

## 快速开始

首次准备：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd ..\frontend; npm install
cd ..\desktop;  npm install
```

日常开发（后端以作业方式后台运行，前端在前台，Ctrl+C 一并结束）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# 浏览器访问 http://localhost:5173
```

跑完全部检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

> 脚本含中文，已带 UTF-8 BOM，Windows PowerShell 5.1 与 PowerShell 7 均可直接运行。

## 阶段 0：冻结基准（已完成）

目标：`dataModel -> xmlString` 纯函数生成的 XML，与两个真实基准**字节级一致**。

| 基准文件 | 字节 | SHA-256（重建 = 原始） |
| --- | --- | --- |
| 1箱3罐.xml | 1,285 | `560b9d34b1bb608fb265df6c536fdfbd9a5ce9307cff04b33fb8cfd749164e11` |
| 一箱一罐.xml | 39,109 | `9e8c1409cd6ea3c67ae28f4bb9dccb858ab77b27febff8035fecc5d514f26d99` |

单独复核：

```powershell
cd backend
.\.venv\Scripts\python.exe tools\compare_golden.py --details
```

### 反推并锁死的字节级规则

1. 无 BOM、UTF-8、纯 LF、文件末尾恰好一个换行。
2. 第 1 行 = `<?xml ...?><Document ...>`，XML 声明紧接根节点，无换行。
3. 无缩进，每个 `<Code/>` 独占一行。
4. `Document` 属性顺序：`xmlns:xsi` → `xsi:noNamespaceSchemaLocation` → `License`。
5. `Relation` 属性顺序：`productCode` → `subTypeNo` → `cascade` → `packageSpec` → `comment`。
6. `Batch` 属性顺序：`batchNo` → `madeDate` → `validateDate` → `workshop` → `lineName` → `lineManager`。
7. `Code` 属性顺序：`curCode` → `packLayer` → `parentCode` → `flag`。
8. `cascade` 为固定字面量，不按实际罐数/粒子数计算。
9. 粒子顺序 = 采集原始顺序，禁止排序。

### 实测反推的条码规则

所有条码均为定长 20 位 ASCII 数字，层级由前缀唯一决定：

| 层级 | packLayer | 前缀 |
| --- | --- | --- |
| 箱 | 3 | `8021761` |
| 罐 | 2 | `8021762` |
| 粒子 | 1 | `8206233` |

照片实测的追溯码标签 = 药品标识码（7 位）+ 序列号（13 位），
用于条码解码值与 OCR 文本的交叉校验。

## 阶段 1：工程骨架与设计系统（已完成）

后端 FastAPI 骨架（健康检查 / 基准访问 / XML 预览 / 批次 CRUD 占位），
前端 5 个路由 + 设计令牌 + `App*` 组件，Electron 桌面壳自动拉起后端。

一条命令跑完全部检查，当前 6 项全部通过：

```
[通过] 后端单元测试（阶段 0 基准 + API 契约）      39 项
[通过] 后端端到端冒烟（真实进程与端口）
[通过] 黄金基准字节级比对
[通过] 前端单元测试（路由 + 条码规则）             12 项
[通过] 前端类型检查与构建
[通过] 桌面壳冒烟（Electron 拉起 Python 服务）
```

## 后续阶段

阶段 2 批次与包装结构 → 阶段 3 扫码采集（最高优先级）→ 阶段 4 预览与导出 → 阶段 5 验收。

详细进展见 [docs/01-阶段记录.md](docs/01-阶段记录.md)。
