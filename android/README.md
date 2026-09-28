# 籽关通 Android 采集端（uni-app）· v1.3.1

> 路线：HBuilderX + uni-app（**不是 Capacitor**）
> 状态：**多箱包装结构 · 本地驱动 · 引导式 · 离线可用**
> 位置：`<ANDROID_PROJECT_DIR>`
> （主仓库内 `android\` 是指向该目录的 junction，两处始终是同一份文件）

---

## 〇、工程放在哪

本工程的实际文件放在 HBuilderX 项目目录：

```
<ANDROID_PROJECT_DIR>
```

主仓库里的 `android\` 是一个 **目录 junction**，指向上面的目录。这样：

- HBuilderX 打开的是普通本地目录，没有链接兼容问题；
- 主仓库的 git 仍然跟踪同一批文件，`docs/`、`scripts/check-uniapp.ps1` 的引用不用改；
- 在 HBuilderX 里编辑 = 编辑仓库内的文件，提交历史不断。

**注意**：junction 不入 git。新克隆仓库的机器上 `android\` 会缺失，
需要把该目录复制回去，或在新机器上重新建 junction —— 详见
`docs/52-Android工程位置与迁移记录.md`。

---

## 一、v1.3.1 改了什么

在 v1.3.0「本地驱动、引导式、离线可用」的基础上，本轮解决两件事：

| 问题 | 结论 | 处理 |
| --- | --- | --- |
| 真机点扫码没进摄像头，反而弹出输入法菜单 | **不是没调摄像头**：空批次时页面上没有扫码按钮，唯一可聚焦元素是「手动输入」输入框，操作员把它当成了扫码框 | 扫码做成页面主按钮并**强制 `onlyFromCamera + scanType:['barCode']`**；调用前动态申请相机权限；手动输入**默认折叠** |
| 纸箱数固定为 1、单箱扁平结构，多箱包装做不了 | 数据模型级问题 | 数据层升级为 `boxes[] → cans[] → particles[]`，向导加「箱」层循环，设置页支持 1~5 箱且每箱罐数各自独立 |

---

## 二、多箱数据结构与流转

### 2.1 结构（`schemaVersion = 2`）

```json
{
  "localId": "LB-xxxx-xxxx", "deviceId": "and-xxxx", "offline": true, "status": "collecting",
  "batchNo": "20260927", "produceDate": "2026-09-27", "expireDate": "2026-10-27",
  "boxes": [
    {
      "boxIndex": 1, "boxCode": "1", "reviewConfirmed": true,
      "cans": [
        {
          "canIndex": 1, "canCode": "1",
          "plannedParticleCount": 2, "confirmed": true,
          "particles": ["8206233...", "8206233..."]
        }
      ]
    }
  ],
  "history": { "undo": [], "redo": [] },
  "earlyEnd": null, "finishRequested": false, "createdAt": "...", "updatedAt": "..."
}
```

`particles` 就是槽位数组：**下标 = 采集顺序**，空串 = 还没扫。数组长度 = 该罐计划粒子数。
计划本身不再单独存一份（v1.3.0 的 `plannedParticleCounts` 已废弃），
一律从 `boxes[].cans[].plannedParticleCount` 推导，避免两处对不上。

### 2.2 向导相位（不落盘，全部由数据推导）

```
box → can → particle → can_review → box_review ─┬─(还有下一箱)→ box（第 N+1 箱）
                                                └─(最后一箱)───→ review
```

- `box`：拍第 X 箱的箱号（提示带「第 X 箱 / 共 Y 箱」）
- `can`：拍本箱的罐号
- `particle`：逐个扫粒子（C2：本期不做多码拍照）
- `can_review`：本罐核对（确认无误 / 还没好）
- `box_review`：**本箱罐全部确认后**问「本箱完成，是否继续拍下一箱？」
  - 还有下一箱 → 确认本箱完成，回到 `box` 拍下一箱的箱号
  - 最后一箱 → 问「最后一箱已完成，是否进入整体核对？」→ `review`
  - 选择「结束并核对」→ `finishRemaining()`：**从当前箱当前罐起剩余全部不再拍**（整批终止），
    缺漏在核对里如实显示，必须到状态页办提前结束签名才能置为已核对
- `review`：整体核对，按箱/罐/粒子分别报计划 vs 实际

### 2.3 双坐标寻址

多箱之后，罐不再有全局序号，所有槽位操作用「**箱 index + 罐 index**」双坐标：

```js
replaceSlot(batch, boxIndex, canIndex, slotIndex, newCode)   // 都是 0 起
deleteSlot(batch, boxIndex, canIndex, slotIndex)
```

撤销栈里的每条操作也记 `boxIndex/canIndex`，所以撤销第 2 箱的操作不会误动第 1 箱。

### 2.4 v1.3.0 老数据自动迁移

`loadBatches()` 读到没有 `boxes` 字段的 v1.3.0 单箱数据时，自动迁移并回写存储：

- `box.code` → `boxes[0].boxCode`
- `cans[].code` → `cans[].canCode`，`cans[].slots` → `cans[].particles`
- `plannedParticleCounts` → 各罐的 `plannedParticleCount`
- 撤销记录补 `boxIndex: 0`
- `boxes[0].reviewConfirmed = true`（单箱老数据不再多问一次「是否继续下一箱」）

迁移是幂等的：已经是 v2 的数据原样返回，不会重复改写。

---

## 三、国内安卓机型的摄像头适配要点

真机（荣耀 ANDROID_DEVICE / Android 16）上踩过的坑与对策：

1. **只认条形码，不进相册**：`uni.scanCode({ onlyFromCamera: true, scanType: ['barCode'] })`。
   不传 `onlyFromCamera` 时，部分 ROM 会给「扫码 / 相册」两选项；放开 `qrCode` 还容易误扫。
2. **扫码前先动态申请相机权限**：`ensureCamera()` 用 `plus.android.requestPermissions(['android.permission.CAMERA'])`。
   基座（io.dcloud.HBuilder）如果被拒过相机权限，`uni.scanCode` 只会失败，不会自己弹申请框。
3. **被拒要有出口**：`cameraDenied()` 弹「去系统设置开权限」，`openAppSettings()` 用
   `Settings.ACTION_APPLICATION_DETAILS_SETTINGS` + 包名直达本应用的权限页。
4. **失败要分类**：`fail` 回调区分「用户取消（静默）」「权限被拒（给引导）」「其他错误（显示 errMsg）」，
   不再笼统地只说一句「扫码失败」。
5. **别把输入框当扫码口**：扫码按钮是页面上最显眼的主按钮（📷 打开摄像头…）；
   「手动输入」默认折叠，点一下才展开，从根上避免长按/点击输入框调出输入法选择菜单。

`manifest.json` 需要 `Barcode` 模块与 `android.permission.CAMERA`（本工程已声明）。

---

## 三之二、箱号 / 罐号为什么要三条采集通道

现场实测（`private\07-拍摄箱号.jpg`）：操作员举着手机对着**电脑屏幕上的 Word 文档**拍，
取景框里只有一枚纯数字「1」——**这不是条码，也不是识别率问题，是码制不匹配**。
`uni.scanCode` 只认 `barCode`，所以这种场景永远扫不出来，必须有别的通道。

于是步骤 1（箱号）与步骤 2.1（罐号）都提供三条通道，且按同一个状态机推进：

| 顺序 | 通道 | 做法 | 适用场景 |
| --- | --- | --- | --- |
| ① | 打开摄像头扫码 | `uni.scanCode({ onlyFromCamera:true, scanType:['barCode'] })` | 正常条码 |
| ② | 拍照识别 | `uni.chooseImage` 拍照 → 浮层大图（可放大/旋转）→ 照着照片手输 | 条码破损、屏幕反光、只有纯数字文本 |
| ③ | 手动输入 | 折叠面板 + 输入框，点开才聚焦 | 完全没有条码，或操作员已经知道号码 |

三条通道最终都走 `applyCodes()`：查重、错层、相位推进只有一份实现，手动输入不会绕开既有规则。

### 自动识别：现在的真实状态（v1.3.4 收口）

2026-09-28 在荣耀 ANDROID_DEVICE + HBuilderX 标准基座上实测过两轮
（`Android-v1.3.1-箱号采集-20260928\阶段0-能力实测结论.md`、`Android-v1.3.4-识别契约层-20260928\阶段0-识别能力实测结论.md`）：

- `plus` 的 49 个命名空间里**没有任何 ocr / ai / ml / vision / infer**（`speech` 是语音，不是图像 OCR）；
- `plus.barcode` 只有 `Barcode / create / getBarcodeById / scan` 和码制常量，**没有 `scanImage`**；
  `scan` 传文件路径一律立即 `fail: code=8`，不接受「图片文件」这种入参；
- `uni.createInferenceSession`（端侧 ONNX 推理）工程里没有模型可用，也没有 OCR 原生插件。

结论：在「不改后端」+「识别在手机本地」+「离线可用」三条约束下，**当前基座做不了「拍照自动提取数字」**。
于是 v1.3.4 把这件事做成**契约层 + 可插拔 Provider**（详见下面「自然数视觉识别契约层」一节），
默认走「拍清楚 → 肉眼看 → 手输」的降级；照片只放在页面内存里，**用完即弃、不落本机**。

### 自然数视觉识别契约层（v1.3.4）

`services/numberRecognizer.js` 只管「看见了什么数字」，**业务校验一行都不碰**——这是文档强调的
「识别与业务校验必须分离」：

```json
{ "success": false, "number": "", "confidence": 0.0, "sourceType": "unknown",
  "needsConfirmation": true, "candidates": [] }
```

| 分层 | 负责什么 | 在哪 |
| --- | --- | --- |
| 识别层 | 输出「看见的数字」+ 置信度 + 候选；不做上限、不查重、不补位 | `services/numberRecognizer.js` |
| 业务层 | 自然数 1~9999、分层查重、相位推进 | `services/localBatch.js` + `pages/scan/scan.vue` |

**自拟识别规范**（原《Android 摄像头数字识别提示词》未提供，规则落进模块注释，供将来的真实 Provider 参照）：

1. 只认真正的数字：忽略 Word 段落标记 `↵`、回车/空格、下划线、光标残留、表格边框、条形码线条，
   以及手机状态栏（时间/电量/信号）和电脑屏幕的工具栏/标尺/任务栏；
2. 字母不转数字：`I23` **不会**被当成 `123`，`normalizeResult` 见到非数字直接判失败；
3. **禁止补位**：不补零、不补全 20 位、不推测被挡住的数字 —— 宁可 `success:false`；
4. `confidence < 0.70` → `needsConfirmation = true`；不确定就 `success:false`；
5. 一张图读到多个号码 → 全部进 `candidates`，由**业务层**决定是否触发多码报警。

**插拔真实识别**：`setProvider(fn)` / `getProviderName()`。将来接入云侧视觉 API 或端侧模型时，
只要 Provider 返回上面的契约，界面与业务层一行都不用改；当前默认 Provider 是
`manualConfirmProvider`（严格 `success:false`，绝不猜测）。

> 验收影响：原需求里「拍一张写着 `1↵` 的照片 → 自动识别为 `1` 且 `success:true`」这条，
> 当前基座**跑不通**（没有识别引擎）；契约层单测里已用**假 Provider** 验证了这条链路
> （`tests/numberRecognizer.test.mjs`：`1↵ → 1`、置信度 0.93 → 不需要人工确认），
> 真机自动识别待 Provider 到位后补测。

### 手动输入的校验口径（v1.3.2 起：分层校验）

**箱号 / 罐号是自然数，不是 20 位条码**——这条曾经搞错，现场录「1」会被
「箱号必须为 20 位数字，且前缀为 8021761」挡住（见 `private\08-罐号格式.jpg`、`09-箱号格式.jpg`）。

| 层级 | 规则 | 说明 |
| --- | --- | --- |
| 箱号 / 罐号 | `/^\d+$/` 且值在 **1~9999**，允许前导零（`01` 合法） | `0`、`-1`、`1.5`、`1a`、`10000`、空串一律拒绝 |
| 粒子码 | 20 位 ASCII 数字 + 前缀 `8206233` | **粒子规则一个字没动** |

- 不满足就弹「箱号格式不对 / **箱号必须是 1~9999 之间的自然数（如 1、2、3），不能含字母、小数或符号。**」，
  **不擅自补齐**；
- 误把粒子条码当箱号/罐号输入时，给专门提示：「这是粒子条码，箱号只需要自然数（1~9999）。」；
- 校验用数据层的 `validateLayerCode(value, layer)` / `describeCodeIssue(value, layer)`（都有单测），
  格式过了才交给 `applyCodes`；
- 输入面板**默认折叠**，只有点「③ ⌨ 手动输入箱号」时才展开并聚焦 —— 页面初始不会弹输入法。

### 查重是分层作用域的（v1.3.2）

自然数天然会在不同层级重复出现，所以查重必须分作用域，否则「箱 1 + 罐 1」会被判成重复、直接录不进去：

| 层级 | 作用域 | 例子 |
| --- | --- | --- |
| 箱号 | **全批唯一** | 一批里两箱不能都叫「1」 |
| 罐号 | **本箱内唯一** | 箱 1 的罐 1 与箱 2 的罐 1 都是合法的「1」 |
| 粒子码 | **全批唯一** | 20 位条码物理唯一 |

实现见 `findUsage(batch, code, layer, context)`：显式传层级 + 作用域上下文
（`excludeBoxIndex` / `boxIndex` / `excludeCanIndex`），调用点见 `applyCodes` 与 `considerSingle`。

### 真机上验证扫码时容易踩的坑（2026-09-28 实测，荣耀 ANDROID_DEVICE / Android 16）

1. **取景界面不是独立 Activity**。它盖在 App 自己的窗口上，所以
   `dumpsys window | grep mCurrentFocus` 一直显示 `PandoraEntryActivity`，
   `uiautomator dump` 也仍能读到被压在下层的 App 文本。
   判断「摄像头是否真的起来」要用 camera service：
   `adb shell dumpsys media.camera | grep io.dcloud.HBuilder`（看 `CONNECT device 0 client …`），
   或看 `Active Camera Clients` 是否为空。
2. **取景界面没关掉就没法截业务页**。它一旦留在屏幕上，后续 `screencap` 拍到的全是相机画面。
   取完证要按一次 BACK 关掉它，再截业务界面。
3. **别用 localStorage 造数据**。App 端的 `uni` 存储有服务层缓存，直接写 webview 的
   `localStorage` 不会生效，测试只能走 UI（或在 H5 上跑）。
4. **截图要用二进制输出**。`execFileSync(adb, ['exec-out','screencap','-p'], { encoding:'utf8' })`
   会把 PNG 解坏，必须不带 encoding 取 Buffer。

---

## 四、本地数据层设计（`services/localBatch.js`）

纯 ESM，**不 import 任何模块**（`uni` 通过可注入的 storage adapter 访问），
因此同一份代码能直接被 Node 单测加载。

| 分组 | 关键导出 | 说明 |
| --- | --- | --- |
| 常量 | `BARCODE_LENGTH`、`CODE_PREFIXES`、`MAX_NATURAL`、`NATURAL_PATTERN`、`CASCADE`、`FIXED_PARAMS`、`MAX_BOXES` | 箱/罐 = 自然数 1~9999；粒子码 20 位 + 前缀（`CODE_PREFIXES[1] = 8206233`，3/2 只留给 `classifyCode` 认老条码）；`cascade="1:5:2500"` 固定字面量；箱 1~5；13 项系统固定参数 |
| 存储 | `setStorageAdapter` `loadBatches` `saveBatch` `getActiveBatch` `listBatches` `removeBatch` `clearAll` | `uni.setStorageSync` 封装，可注入内存实现做单测；读时自动迁移老数据 |
| 迁移 | `migrateBatch` | v1.3.0 单箱 → v1.3.1 多箱，幂等 |
| 校验 | `classifyCode` `isNaturalCode` `validateLayerCode` `describeCodeIssue` `validateBaseInfo` `validateStructure` `particleTotal` `planCounts` `planSummary` `progress` | 分层校验（箱/罐自然数 1~9999、粒子 20 位）；结构校验吃「箱 → 罐」二维数组；箱 1~5、每箱罐独立 1~5、每罐 1~2500、**单批 ≤12500 硬上限** |
| 批次 | `createDraft` `updateBaseInfo` `buildBoxes` `saveStructure` `transition` | 状态机 `草稿 → 采集中 → 待核对 → 已核对`，非法流转拒绝 |
| 向导 | `deriveWizard` `findCan` `findUsage` `applyCodes` `confirmCanReview` `confirmBoxReview` `finishRemaining` `registerEarlyEnd` | 相位见 §2.2；错层/重复/溢出拦截；`findUsage` 是**分层作用域**查重（箱全批唯一 / 罐本箱唯一 / 粒子全批唯一） |
| 槽位 | `replaceSlot` `deleteSlot` `undo` `redo` `historyState` | 双坐标寻址；撤销栈上限 50 步，超出丢最旧 |
| 核对 | `review` | 5 项检查（罐数一致、粒子总数一致、总数≤12500、每罐≤2500、箱号/罐号/粒子码未缺漏）+ `perBox` + `perCan` |

**粒子顺序 = 采集原始顺序，任何操作都不排序。**

---

## 五、目录

```
android/
├── manifest.json          应用配置、Android 权限
├── pages.json             三页路由 + 底部 tabBar
├── App.vue / main.js      入口
├── pages/
│   ├── scan/scan.vue      多箱引导式向导 + 摄像头扫码主按钮 + 槽位编辑 + 折叠的手动输入
│   ├── status/status.vue  多箱整体核对（箱/罐/粒子）+ 逐箱逐罐明细 + 提前结束
│   └── settings/settings.vue  批次基础信息、多箱包装结构 + 统计面板、本地批次管理
├── services/
│   ├── localBatch.js      ★ 本地数据层（多箱结构/状态机/槽位/撤销/核对/迁移）
│   ├── api.js             二期同步用的 /api/scan/* 客户端（本期不阻塞）
│   ├── ws.js              uni.connectSocket 封装（二期）
│   └── store.js           服务地址、设备指纹
├── tests/localBatch.test.mjs  本地数据层单测（183 项）
└── unpackage/             构建产物（已 gitignore）
```

---

## 六、跑起来

### 6.1 只跑离线流程（不需要起后端）

1. HBuilderX → 文件 → 打开目录 → 选本目录
2. 登录 DCloud 账号（运行到 App 基座必须登录）
3. 运行(R) → 运行到手机或模拟器(N) → 运行到Android App基座(D)
4. 手机上：设置 → 填批号/生产日期/有效期 → 保存草稿 → 配「N 箱，每箱 M 罐，每罐 K 粒」
   → 保存结构，进入采集 → 扫码页点 📷 主按钮按向导扫 → 状态页核对

飞行模式下同样可用（数据全部落在本机）。

### 6.2 想顺手看看主控机在不在（可选）

```powershell
powershell -ExecutionPolicy Bypass -File scripts\serve-lan.ps1
```

设置页「服务地址」填 `http://<脚本打印的局域网IP>:17800` → 测试连接。
**连不上只提示离线模式，不影响任何采集操作。**
（注意：这个服务会占用 17800 端口，跑 `scripts\check.ps1` 之前要先停掉，否则后端 e2e 冒烟会因端口冲突失败。）

---

## 七、测试与验收证据

```powershell
# 本地数据层单测（183 项，Node 直跑，无需 HBuilderX）
cd "<ANDROID_PROJECT_DIR>"
node tests/localBatch.test.mjs
```

H5 / 真机端到端脚本与截图在
`<REPO_ROOT>\private\测试输出\Android-v1.3.1-多箱扫码-20260927\`：

| 文件 | 内容 |
| --- | --- |
| `h5-multibox-flow.e2e.mjs` | H5（=无后端环境）多箱全流程：2 箱 × 2 罐 × 2 粒 |
| `device-multibox-flow.mjs` | 真机多箱全流程 + 摄像头调起取证（`--manual` 可只跑流程） |
| `真机-01`~`真机-07` 截图 | 设置页多箱配置、扫码向导、摄像头调起、整体核对、状态页核对 |

---

## 八、本版边界（别去找）

### 本机 XML 生成与 HTML 导出（v1.3.3，正式推翻一期 C3）

一期约束 C3 曾写「手机端不产出 XML，数据仅固化在本地」。**v1.3.3 起正式推翻**：
手机端在本机生成 XML，用于「状态页原样预览 + 导出 .html」，
但**仍不同步、不改后端与电脑端**；二期同步后仍以主控机生成的 XML 为准。

**生成规则与后端完全同源**：实现照抄 `backend/app/services/xml_builder.py`，
并用 `backend/tests/golden/1箱3罐.xml` 做**逐字节**单测比对（`tests/xmlGenerator.test.mjs`）。

| 规则 | 内容 |
| --- | --- |
| 编码/换行 | 无 BOM、UTF-8、纯 LF、**末尾恰好一个换行** |
| 第 1 行 | `<?xml version="1.0" encoding="utf-8"?><Document …>`（声明与根节点同一行） |
| 缩进 | **严禁任何缩进**，每个 `<Code/>` 独占一行 |
| 属性顺序 | Document：`xmlns:xsi → xsi:noNamespaceSchemaLocation → License`；Relation：`productCode → subTypeNo → cascade → packageSpec → comment`；Batch：`batchNo → madeDate → validateDate → workshop → lineName → lineManager`；Code：`curCode → packLayer → parentCode → flag` |
| 节点顺序 | 箱 → 罐1 → 罐1 的粒子（原序）→ 罐2 → 罐2 的粒子 → … |
| 层级/父子 | 箱 `packLayer="3"` 无 `parentCode`；罐 `2`（parent=箱号）；粒子 `1`（parent=罐号）；`flag="2"` |
| 数据映射 | `batchNo→batchNo`、`produceDate→madeDate`、`expireDate→validateDate`；固定值全部取自 `FIXED_PARAMS` |
| 粒子顺序 | 严格按采集原始顺序，**严禁排序** |
| 未采集节点 | **跳过**（箱号空→整箱跳过；罐号空→整罐跳过；空槽位跳过），界面提示「已跳过 N 个未采集槽位」 |

**HTML 导出说明**（`services/xmlGenerator.js` 的 `renderHtml` + 状态页的导出按钮）：

- 文件名 `Relation_{批号}_{yyyyMMddHHmmss}.html`，时间取设备本地时间；
- 内容为 `<pre>` 包裹的 XML，其中 `& < >` 做了 HTML 实体转义 —— 不转义的话浏览器会把
  `<Code …>` 当 HTML 标签渲染掉，反而看不到原文；
- 落盘路径：`uni.saveFile` 优先（落到 `_doc/uniapp_save/`）；
  **实测坑**：`uni.saveFile` 会把文件名改成随机号（如 `17905503685290.html`），
  与「文件名严格按规范」冲突，所以落盘后再用 `plus.io` 的 `moveTo` 改回规范名；
  若 `saveFile` 失败则降级 `uni.shareWithSystem` 拉起系统分享；两条都失败会弹可操作提示，不静默。

---

| 项 | 说明 |
| --- | --- |
| XML 产出 | **v1.3.3 起改为：手机端在本机生成 XML（仅本地预览 + 导出 .html），仍不同步、不改后端**；二期同步后仍以主控机生成的 XML 为准 |
| 粒子多码拍照 | 离线不具备多码识别能力，本期逐个扫码 |
| 离线补发 / 多端互斥锁 | 二期 |
| 账号登录 | 一期单机无账号体系 |
| mDNS 自动发现 | 现在靠手填地址 |

---

## 九、验收清单（v1.3.1）

- [x] 单批上限 12500 硬上限（方案 A），超限高亮并禁止进入采集中
- [x] 每箱罐数各自独立；箱数 1~5
- [x] 提前结束 = 从当前箱当前罐起整批终止，需原因 + 操作人，计入核对
- [x] 扫码只认条形码（`scanType: ['barCode']` + `onlyFromCamera: true`）
- [x] 相机权限动态申请 + 被拒给「去系统设置」引导 + 失败分类提示
- [x] 手动输入默认折叠，扫码是页面主按钮
- [x] 多箱数据结构 + 向导箱循环 + 双坐标槽位/撤销
- [x] v1.3.0 单箱数据自动迁移（幂等）
- [x] 单测 ≥100 项（实际 183 项全过）
- [x] H5 多箱 e2e 全过
- [x] 不改后端与电脑端（`scripts/check.ps1` 回归全过）

### 箱号采集流程优化（2026-09-28 增补）

- [x] 步骤 1（箱号）与步骤 2.1（罐号）都有三条通道：扫码 / 拍照识别 / 手动输入
- [x] 手动输入默认折叠、点开才聚焦，页面初始不弹输入法
- [x] 格式校验：非法（含字母/小数/符号、超 9999）→ 弹「箱号必须是 1~9999 之间的自然数」
- [x] 合法输入 → 自动收起输入区 → 相位推进 `box → can`（或 `can → particle`）
- [x] 拍照识别：调系统相机拍照 → 浮层大图（放大/缩小/旋转/复位）→ 照着照片手输；照片用完即弃不落本机
- [x] 原扫码流程不受影响（正常条码仍可直接扫出并推进）
- [x] 单测 195 项全过（含 `validateLayerCode` 的合法/短号/错前缀/含字母/空串用例）
- [x] 真机 15 项断言全过（含相机调起、照片确认浮层、非法格式拦截、推进到步骤 2）

### 箱/罐号自然数校验与分层查重（2026-09-28 增补）

- [x] 箱号 / 罐号改成自然数校验（1~9999，允许前导零），**不再要求 20 位**
- [x] 输入「1」→ 弹「这是第 1 箱的箱号吗？」→ [是] → 推进到罐号步骤
- [x] 罐号「1」→ 弹「这是箱 1 罐 1 号吗？」→ [是] → 推进到粒子步骤
- [x] 多号码（`1 2`）→ 震动 + 红色报警条，阻止推进且不进确认框
- [x] `1a` / `10000` → 弹「箱号必须是 1~9999 之间的自然数…」
- [x] 分层查重：箱号全批唯一、罐号本箱内唯一、粒子码全批唯一
- [x] 粒子规则一个字没动（20 位 + 前缀 8206233）
- [x] 单测 223 项全过；H5 e2e 58 项全过；真机 20 项全过；`check.ps1` 回归全过

### 本机 XML 生成 / 原样预览 / 导出 .html（v1.3.3 增补）

- [x] 新增 `services/xmlGenerator.js`（纯 ESM；固定值取自 `FIXED_PARAMS`）
- [x] 与 `backend/tests/golden/1箱3罐.xml` **逐字节一致**（单测 50 项全过）
- [x] 无 BOM、纯 LF、末尾一个换行、声明与 `<Document>` 同行、无缩进、属性顺序固定
- [x] 状态页预览从 JSON 换成**本机生成的 XML**（原样显示，不做任何格式化）
- [x] 「导出为 .html」：文件名 `Relation_{批号}_{yyyyMMddHHmmss}.html`，`uni.saveFile` 主 + `uni.shareWithSystem` 降级
- [x] 未采集节点跳过，界面提示「已跳过 N 个未采集槽位」
- [x] H5 e2e 67 项全过（含「H5 下导出给明确提示」）；真机 18 项全过（含 adb 拉回文件核对字节与内容）
- [x] 浏览器打开导出的 HTML，XML 标签完整可见（`&lt;`转义生效）
- [x] `check.ps1` 回归 11 项全过（后端与电脑端一行未改）

### 自然数视觉识别契约层与降级（v1.3.4 增补）

- [x] 新增 `services/numberRecognizer.js`：契约 `{success, number, confidence, sourceType, needsConfirmation, candidates}`
- [x] 默认 Provider `manualConfirmProvider` 严格 `success:false`（本机无识别引擎，绝不猜测）
- [x] `normalizeResult` 严格净化：`1↵ → 1`、剔除空格/下划线/光标/零宽字符；`I23`/`O0`/`1.5`/`-1` 一律判失败
- [x] 置信度阈值 0.70；`< 0.70` 或失败 → `needsConfirmation = true`
- [x] 多候选 `candidates` 保留，业务层 `length > 1` → 震动 + 多码报警、阻止推进
- [x] 拍照通道接契约层：成功→带置信度的确认框；失败→明确降级提示（浮层可滚动，提示不会被顶出屏幕）
- [x] 手动输入 placeholder 改为「请输入/拍摄箱号（自然数，如 1、2、3）」
- [x] 单测 59 项全过；H5 e2e 70 项全过；真机 19 项全过（含「粒子 20 位不受影响」）
- [x] `check.ps1` 回归 11 项全过（后端与电脑端一行未改）

### 状态页长文本折行与 HTML 打开入口（v1.3.5 增补）

**长文本折行策略**（真机 `11-本地固化数据预览内容换行调整.jpg` 暴露的问题：XML 长属性行、20 位条码被右侧硬裁）：

- 根因是 `.preview-text` 用了 `white-space: pre` —— 保留换行但禁止折行，超宽内容只能被裁；
- 统一改成 `white-space: pre-wrap` + `word-break: break-all` + `word-wrap: break-word`：
  保留原有换行符，同时让长行自动折行，20 位条码不再撑破容器；
- 预览区高度 `400rpx → 720rpx`，只保留纵向滚动（`scroll-y`），**不加横向滚动**；
- 「最近导出」从单行字符串换成结构化记录 `{ name, size, by, path }`，
  用 `<view>` 分组展示「文件名 / 大小与方式 / 完整路径」，每行都加 `break-all`，
  长路径不再省略；
- **内容一字不改**：折行只是展示层行为，底层 XML 字符串与复制出来的内容都是原样。

**HTML 打开方式（Android 沙箱说明）**：

- 导出的 HTML 落在应用私有外部目录 `…/Android/data/io.dcloud.HBuilder/apps/HBuilder/doc/uniapp_save/`，
  Android 11+ 下**外部应用默认读不到这个路径**，必须靠系统 Intent 的临时授权；
- 阶段 0 真机实测三条路径（见 `private\测试输出\Android-v1.3.5-长文本与打开入口-20260928\阶段0-打开能力实测结论.md`）：

| 路径 | 结果 | 结论 |
| --- | --- | --- |
| `plus.runtime.openFile(path)` | 弹出系统「打开方式」选择器（`HwResolverActivity`），列表里有「HTML 查看器」 | **主路径**（内部走 DCloud FileProvider + 临时授权） |
| `uni.openDocument({fileType:'html', showMenu:true})` | 同样弹出选择器 | 降级路径（html 不在官方支持列表，但实测可用） |
| 自建 `Intent.createChooser` + `file://` | 也能弹出选择器 | 不用：`file://` 在 Android 7+ 外部应用读不到，点了也打不开 |

- 选择「HTML 查看器」后实测能打开并完整显示 XML（标签没有被吞）；
- 文件不存在/已被清理 → Toast「文件不存在或已被删除」；没有可打开的应用 → 弹可操作提示，不静默；
- 小坑：部分 ROM 的「打开方式」选择器会**吞掉第一次点击**，操作员再点一次即可（真机脚本里做了重试）。
