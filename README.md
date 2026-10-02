# 籽关通 (PharmRelate Multi)

跨平台三级包装（箱 → 罐 → 粒子）关联管理系统。

<p align="right">
  <a href="https://sd3247930.github.io/pharmrelate-suite/?install=1"><strong>📲 安装</strong></a>
</p>

Android（手机）直接打开 <https://sd3247930.github.io/pharmrelate-suite/>，
点右上角 **「📲 安装」** 就能下载独立 APK：桌面有独立图标、打开无地址栏、断网可用。
上面右上角的「📲 安装」直达安装面板。

**当前状态（2026-10-01）**

| 端 | 状态 |
| --- | --- |
| Windows 主控机 | 一期单机闭环**已完成**：基准冻结 → 工程骨架/设计系统 → 数据持久化与批次状态机 → 扫码采集 → 预览与导出 → 验收 |
| Android 采集端（uni-app） | **v1.4.5 已完成**：本地驱动 · 引导式 · 离线可用；多箱包装结构；**箱号扫一维条形码 / 罐号扫方形二维码**（20 位追溯码 + 前缀校验、连字符自动清洗）；**批量连续扫码启动链重构**（一次 create / 每识别一枚重新 start / 三层去重（瞬时防抖 2.5s）/ 重启盲区按结果分档 200·120·60ms / 提示音可关 / 切 Tab 即释放摄像头）；**槽位手动补录与批量录入**（13 位自动补前缀、空输入不关窗、重复码拦截、溢出明示未写入）；**图库选图本机自动识别条码**（解码迁到 renderjs 视图层 + zxing-wasm，免插件、纯离线：9 码标签页 9/9 · 349ms，24 码 22/24；不够数再补可降级 OCR，都没有则如实降级手输，12 秒硬超时兜底）；**候选列表逐条删除**（删除即变灰+删除线并同步数据层，被删的码绝不写入槽位，可一键重新识别找回）；**批次基础信息四字段**（生产日期/标识日期/有效期，标识日期只存本机）；本机 XML 生成与 HTML 导出 |
| 手机网页版 / APK 分发 | **已上线**：GitHub Pages 分发站 + 固定资产名 APK 直链（首次发布 `v1.3.5`），一条命令发版（`scripts\publish-apk.ps1`） |

一条命令跑完全部检查（后端 + 前端 + 桌面壳 + Android 静态检查）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

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

完整决策与理由见内部决策记录（`docs/` 已于 2026-09-28 移出公开仓库，不再随代码分发）。

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
web/                       手机端分发站（Pages 发布的目录：安装入口 + 直下 APK）
.github/workflows/         Pages 发布工作流（把 web/ 原样发上去）
android/                   Android 采集端（uni-app / HBuilderX）
  pages/                   扫码采集 · 任务状态 · 连接设置（三 Tab）
  services/localBatch.js   ★ 本地数据层（多箱结构 / 状态机 / 槽位 / 撤销 / 核对 / 老数据迁移）
  services/xmlGenerator.js ★ 本机 XML 生成（与后端 xml_builder.py 字节级一致）
  services/numberRecognizer.js  追溯码视觉识别契约层（可插拔 Provider + 人工确认降级）
  utils/batchBarcodeScanner.js  ★ 批量连续扫码启动链（create/append/start 循环 · 状态机 · 三层去重 · 盲区分档）
  services/particleInput.js ★ 粒子码手动录入解析层（13 位补前缀 · 20 位原样 · 批量分隔符 · 去重分类）
  services/ocr.js           ★ 离线 OCR 可降级桥接（nativeplugins / UTS 两形态，无插件自动降级手输）
  uni_modules/pharmrelate-ocr/  UTS OCR 插件骨架（ML Kit text-recognition 16.0.1 bundled，未编译）
  tests/                   Node 单测（数据层 260 + XML 57 + 识别契约 66 + 扫码启动链 101 + 手动录入 63 + 槽位补录 59 + OCR 候选 50 = 656）
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
| 1箱3罐.xml | 1,285 | `43c19388b2280fd2aba7bbdeac85a1fa27aa69e464f0266d9718cfdcadc8a464` |
| 一箱一罐.xml | 39,109 | `ee1e6302936965061783bbf0aaa302a276a6e69e7831419aacdb57c96ec6a967` |

单独复核：

```powershell
cd backend
.\.venv\Scripts\python.exe tools\compare_golden.py --details
```

## 阶段 2：数据持久化与批次状态机（已完成）

### 本地库

默认位置 `%LOCALAPPDATA%\PharmRelate Multi\pharmrelate.db`（可用 `PHARMRELATE_DATA_DIR` 覆盖）。
**不放安装目录**——安装目录通常无写权限，且卸载/升级容易把它清掉。

查看当前库内容：

```powershell
cd backend
.\.venv\Scripts\python.exe tools\db_status.py
```

表结构：`batch`（基础信息 + 固定参数快照 + 状态 + 提前结束签名 + SyncMeta）、
`code`（全部条码，`UNIQUE (batch_id, cur_code)` 保证同批次全局唯一）、
`oplog` / `audit_log`（二期预留）、`meta`（schema 版本）。

固定参数在创建批次时快照落库，而不是导出时现算，这样历史批次的导出结果可复现。

### 状态机

```
草稿 → 采集中 → 待核对 → 已核对 → 已导出 → 已锁定 → 已归档
  └────────── 任意状态（除已归档/已作废）由管理员作废 ──────────┘
```

非法流转返回 409 并列出允许的目标状态。解锁、锁定、作废必须填写原因。
权威在后端，前端只读状态、只发流转请求；只读状态下任何写入都被拒绝。

### 重复批号三选一

服务端返回已有批次的状态与进度，以及三条出路：打开已有批次 / 创建新版本（批号由服务端算，
如 `20260901-V2`）/ 取消并返回修改。

### 提前结束

签名形式：操作人下拉选择 + 备注文本（另加必填原因）。
实际罐数与实际粒子数由服务端按库内数据填写，不接受前端传入。

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
[通过] 后端单元测试（基准 + API + 状态机 + 持久化）  83 项
[通过] 后端端到端冒烟（真实进程与端口）
[通过] 黄金基准字节级比对
[通过] 前端单元测试（路由 + 条码规则 + 状态徽章）    41 项
[通过] 前端类型检查与构建
[通过] 桌面壳冒烟（Electron 拉起 Python 服务）
```

## Android 采集端（uni-app / HBuilderX）

工程实体在 `<ANDROID_PROJECT_DIR>`，
仓库内 `android/` 是指向它的 junction（同一份文件，git 正常跟踪）。

### 怎么跑

1. HBuilderX → 文件 → 打开目录 → 选该工程目录 → 登录 DCloud 账号；
2. 运行(R) → 运行到手机或模拟器(N) → 运行到 Android App 基座；
3. 手机上：设置 → 填批号/生产日期/有效期 → 保存草稿 → 配「N 箱 × 每箱 M 罐 × 每罐 K 粒」
   → 保存结构，进入采集 → 扫码页按向导采集 → 状态页核对。

**不需要起后端也能走完整流程**（本地驱动、离线可用）；设置页的「服务地址」只作二期同步预研用。

### 能力一览

| 能力 | 说明 |
| --- | --- |
| 多箱包装结构 | `boxes[] → cans[] → particles[]`；箱 1~5、每箱罐数各自独立 1~5、每罐 1~2500、单批 ≤12500；v1.3.0 单箱老数据自动迁移 |
| 引导式采集 | 相位 `箱 → 罐 → 粒子 → 本罐核对 → 本箱核对 → 整体核对`，不能跳步；箱/罐/粒子统一 20 位追溯码，**箱号只扫一维条形码、罐号只扫方形二维码**、粒子只扫条形码 |
| 分层查重 | 箱号全批唯一 / 罐号本箱唯一 / 粒子码全批唯一 —— 三者必须分作用域，否则「箱 1 的罐 1」与「箱 2 的罐 1」会互相冲突 |
| 三条采集通道 | ① 摄像头扫码（箱号=条形码 / 罐号=二维码）② 拍照识别 ③ 手动输入；手动面板默认折叠、点开才聚焦 |
| 本机 XML | 按后端 `xml_builder.py` 的字节级规则本机生成，状态页原样预览（长文本自动折行），并导出 `.html`（`Relation_{批号}_{时间}.html`） |
| 离线降级 | 断网只提示「当前为离线模式，数据将保存在本机」，三页无红色阻断 |
| 识别契约层 | `numberRecognizer.js` 输出 `{success, number, confidence, sourceType, needsConfirmation, candidates}`；当前无端侧 OCR，默认 Provider 严格失败 → 降级人工读数（**不猜测、不补位**） |

### 测试

```powershell
cd android
node tests\localBatch.test.mjs           # 本地数据层 250 项
node tests\xmlGenerator.test.mjs         # XML 生成器 57 项（含与后端基准逐字节比对）
node tests\numberRecognizer.test.mjs     # 识别契约层 66 项
node tests\batchBarcodeScanner.test.mjs  # 批量连续扫码启动链 101 项（假 plus 驱动，PC 上就能验）
node tests\particleInput.test.mjs        # 手动录入解析层 63 项（前缀规则/分隔符/去重分类）
node tests\slotFill.test.mjs             # 槽位补录与批量录入 59 项（部分溢出/撤销/去重）
node tests\ocrCandidates.test.mjs        # OCR 候选解析 50 项（bbox 重排/去重分类/降级桥接）
```

真机端到端脚本与截图证据在 `private\测试输出\`（该目录不入库，可重跑生成）。

## 后续阶段

一期 Windows 单机闭环与 Android 采集端均已完成。二期方向：多端同步（SyncMeta / oplog 已预留）、
粒子多码拍照识别、离线补发与多端互斥锁、账号与权限。

内部阶段记录（`docs/`，已于 2026-09-28 移出公开仓库）不再随代码分发；
Android 端设计说明见 [android/README.md](android/README.md)。

## 数据脱敏与仓库卫生规范

本仓库是**公开**仓库，代码、基准与文档里**一律不得出现真实生产数据**。
2026-09-29 做过一次全量脱敏（含历史重写），规则固化如下。

### 不入库的东西

| 类别 | 处理 |
| --- | --- |
| 内部资料（需求文档、决策记录、阶段记录） | 放 `docs/`，已移出仓库并加入 `.gitignore`，只在本机保留 |
| 现场实物照片、标签照片、测试证据 | 放 `private/`，同样已移出仓库并忽略 |
| 签名证书与口令 | `private/签名证书/`，绝不入库 |
| APK 等二进制产物 | `private/构建产物/`；对外只走 GitHub Release |

### 脱敏后的固定值

基准与代码里的业务标识全部是**虚构值**，与真实产品无关：

| 项 | 虚构值 |
| --- | --- |
| 许可证 `License` | `1001123` |
| 产品编码 `productCode` | `9999999` |
| 子类型 `subTypeNo` | `9500000001` |
| 车间 `workshop` | `一号车间` |
| 生产线 `lineName` | `一号生产线` |
| 负责人 `lineManager` | `操作员甲`（名单 `操作员甲/乙/丙/丁`） |
| 追溯码 | 前缀保留（箱 `8021761` / 罐 `8021762` / 粒子 `8206233`），序列号统一以 **9** 打头，如 `80217619000000001003` |

真实序列号一律以 `0` 打头，**看到以 9 打头的序列号就是脱敏值**，别当成现场数据。

### 新增代码时的自查

1. 不提交任何现场照片、真实条码、真实车间/人员名、真实许可证号；
2. 源码里不写本机绝对路径 —— 用相对路径、环境变量或参数（例如
   `scripts/publish-apk.ps1` 的 `-HbuilderApkDir` / `PHARMRELATE_HBUILDER_APK_DIR`、
   `ANDROID_SDK_BUILD_TOOLS`）；
3. 测试里不要硬编码「照片解出来的具体条码」，改成断言结构（前缀、长度、数量、冲突行为）；
4. 提交前跑 `powershell -ExecutionPolicy Bypass -File scripts\check.ps1`。

### 本地跑真图用例

现场照片不在仓库里，依赖它的识别与摄像头用例会 **skip**（pytest 汇总里能看到 skipped 计数，
不是静默通过）。本地要跑真图用例，把照片放回 `private\条形码.jpg`，或设置：

```powershell
$env:PHARMRELATE_PHOTO = "<本机标签照片路径>"
```
