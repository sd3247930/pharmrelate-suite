# 籽关通 Android 采集端（uni-app）· v1.4.5

> 路线：HBuilderX + uni-app（**不是 Capacitor**）
> 状态：**多箱包装结构 · 本地驱动 · 引导式 · 离线可用 · 箱号扫条码 / 罐号扫二维码**
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
`uni.scanCode` 只认指定码制，所以这种场景永远扫不出来，必须有别的通道。

于是步骤 1（箱号）与步骤 2.1（罐号）都提供三条通道，且按同一个状态机推进：

| 顺序 | 通道 | 做法 | 适用场景 |
| --- | --- | --- | --- |
| ① | 打开摄像头扫码 | 箱号 `scanType:['barCode']` / 罐号 `scanType:['qrCode']` / 粒子 `['barCode']` | 正常条形码 / 方形二维码 |
| ② | 拍照识别 | `uni.chooseImage` 拍照 → 浮层大图（可放大/旋转）→ 照着照片手输 | 码破损、屏幕反光、只有纯数字文本 |
| ③ | 手动输入 | 折叠面板 + 输入框，点开才聚焦 | 完全没有码，或操作员已经知道号码 |

三条通道最终都走 `considerSingle()` → `applyCodes()`：清洗、校验、查重、错层、相位推进只有一份实现，
手动输入与拍照识别都不会绕开既有规则。

### 自动识别：现在的真实状态（v1.3.4 收口）

2026-09-28 在荣耀 ANDROID_DEVICE + HBuilderX 标准基座上实测过两轮
（`Android-v1.3.1-箱号采集-20260928\阶段0-能力实测结论.md`、`Android-v1.3.4-识别契约层-20260928\阶段0-识别能力实测结论.md`）：

- `plus` 的 49 个命名空间里**没有任何 ocr / ai / ml / vision / infer**（`speech` 是语音，不是图像 OCR）；
- `plus.barcode` 只有 `Barcode / create / getBarcodeById / scan` 和码制常量，**没有 `scanImage`**；
  `scan` 传文件路径一律立即 `fail: code=8`，不接受「图片文件」这种入参；
- `uni.createInferenceSession`（端侧 ONNX 推理）工程里没有模型可用，也没有 OCR 原生插件。

结论：在「不改后端」+「识别在手机本地」+「离线可用」三条约束下，**当前基座做不了「拍照自动提取数字」**。
于是 v1.3.4 把这件事做成**契约层 + 可插拔 Provider**（详见下面「追溯码视觉识别契约层」一节），
默认走「拍清楚 → 肉眼看 → 手输」的降级；照片只放在页面内存里，**用完即弃、不落本机**。

### 追溯码视觉识别契约层（v1.3.4 建立，v1.4.0 改口径）

`services/numberRecognizer.js` 只管「看见了什么数字」，**业务校验一行都不碰**——这是文档强调的
「识别与业务校验必须分离」：

```json
{ "success": false, "number": "", "confidence": 0.0, "sourceType": "unknown",
  "needsConfirmation": true, "candidates": [] }
```

| 分层 | 负责什么 | 在哪 |
| --- | --- | --- |
| 识别层 | 输出「看见的数字」+ 置信度 + 候选；不做上限、不查重、不补位 | `services/numberRecognizer.js` |
| 业务层 | 20 位长度 + 前缀（箱 8021761 / 罐 8021762 / 粒子 8206233）、连字符清洗、分层查重、相位推进 | `services/localBatch.js` + `pages/scan/scan.vue` |

**自拟识别规范**（原《Android 摄像头数字识别提示词》未提供，规则落进模块注释，供将来的真实 Provider 参照）：

1. 只认真正的数字：忽略 Word 段落标记 `↵`、回车/空格、下划线、光标残留、表格边框、条形码线条、
   **分段连字符**（`8021762-9000000001003` 中间那个 `-`），以及手机状态栏（时间/电量/信号）
   和电脑屏幕的工具栏/标尺/任务栏；
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

### 手动输入的校验口径（v1.4.0：箱 / 罐 / 粒子同一套 20 位规则）

**箱号、罐号、粒子码统一是 20 位追溯码**，层级只由前缀决定 —— 箱 `8021761`、罐 `8021762`、粒子 `8206233`。
v1.3.2 的「箱/罐 = 短号 1~9999」口径已**彻底作废**（现场实物证明是标准 20 位追溯码）。

| 层级 | 规则 | 说明 |
| --- | --- | --- |
| 箱号 | 20 位纯数字 + 前缀 `8021761`，落库前剥连字符 | `1`、`1a`、19 位、错前缀一律拒绝 |
| 罐号 | 20 位纯数字 + 前缀 `8021762`，落库前剥连字符 | 标签印的是 `8021762-9000000001003`，清洗后通过 |
| 粒子码 | 20 位 ASCII 数字 + 前缀 `8206233` | **粒子规则一个字没动** |

- 不满足就弹「箱号格式不对 / **箱号必须为 20 位数字，且前缀为 8021761**」（罐号同理换前缀），
  **不擅自补齐、不做任何猜测**；
- 误把粒子条码当箱号/罐号输入时，给专门提示：「这是粒子条码，箱号需要 20 位追溯码（前缀 8021761）。」；
- 手动输入与扫码、拍照识别走**同一个** `considerSingle()` 收口，规则不会因为改成手输而放宽；
- 校验用数据层的 `cleanLayerCode(value, layer)` / `validateLayerCode(value, layer)` /
  `describeCodeIssue(value, layer)`（都有单测），格式过了才交给 `applyCodes`；
- 输入框 placeholder：「请输入 20 位箱号（前缀 8021761）」/「请输入 20 位罐号（前缀 8021762）」；
- 输入面板**默认折叠**，只有点「③ ⌨ 手动输入箱号」时才展开并聚焦 —— 页面初始不会弹输入法。

### 查重是分层作用域的（v1.3.2 起，v1.4.0 沿用）

`1~9999` 时代短号天然会在不同层级重复出现，所以查重必须分作用域；
改成 20 位追溯码后，不同箱的罐号前缀相同、尾号仍可能相同，这条规则继续沿用：

| 层级 | 作用域 | 例子 |
| --- | --- | --- |
| 箱号 | **全批唯一** | 一批里两箱不能是同一个箱号 |
| 罐号 | **本箱内唯一** | 箱 1 罐 1 与箱 2 罐 1 可以是同一个罐号 |
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

## 三之三、扫码规则：箱号只支持条形码 / 罐号只支持二维码（v1.4.0）

现场实物（`private\图片\15-箱码.jpg`、`16-罐码.jpg`）把两件事钉死了：

| 层级 | 载体 | 标签印的内容 | 落库值 |
| --- | --- | --- | --- |
| 箱号 | **一维条形码**（Code 128） | 药品标示码 `8021761` + 序列号 `9000000001002` | `80217619000000001002`（20 位） |
| 罐号 | **方形二维码**（QR） | `8021762-9000000001003` | `80217629000000001003`（20 位，**连字符自动清洗**） |
| 粒子 | 一维条形码 | — | 20 位 + 前缀 `8206233` |

规则与边界：

- 扫码时按层级限制码制：箱号 `scanType:['barCode']`、罐号 `scanType:['qrCode']`、粒子 `['barCode']`；
- **`scanType` 在部分国产 ROM 的基座上会被忽略**（基座可能直接返回扫到的任意码），
  所以「扫错类型」的最终拦截**以业务层为准**：20 位纯数字 + 前缀必须匹配，不匹配就弹格式错误；
  一期**不引入自定义扫码插件**（超出范围）；
- `cleanLayerCode(value, layer)` 对箱/罐剥掉连字符后再校验；清洗**幂等**，
  对本身就不带连字符的 20 位内容调用无副作用；粒子码（layer 1）原样不动；
- 清洗发生在**校验与确认弹窗之前**，保证「弹窗显示什么，库里就存什么」；
- 历史批次里已经存过的短号箱号（如 `1`）**保持原样不迁移**，只在核对/导出时按原值带出。

---

## 三之四、批量连续扫码 · 虚拟箱 · 去重（并入 v1.4.0）

### 3.4.0 批次基础信息：四个字段与日期口径（v1.4.3）

设置页「批次基础信息」从上到下固定为：

| 字段 | 绑定 | 是否导出 | 说明 |
| --- | --- | --- | --- |
| 批号（必填） | `batchNo` | ✅ | 例如 20260927 |
| **生产日期（必填）** | `produceDate` | ✅ → XML `madeDate` | **属性名一个字没动**（黄金基准字节级冻结） |
| **标识日期（必填）** | `identityDate` | ❌ **只存本机** | 2026-10-02 新增；XML 只有 `madeDate`/`validateDate` 两个日期位，装不下第三个 |
| 有效期（必填，需大于标识日期） | `expireDate` | ✅ → XML `validateDate` | 选标识日期时自动 = 标识日期 + 60 天 |

- 界面文案：原「标示日期」按业务拍板改为**「标识日期」**（示 → 识）；原 `produceDate` 显示为「生产日期」。
- **老批次兼容**：v1.4.3 之前建的批次没有 `identityDate`，打开设置页**不报错**、能照常保存；
  只有**新建批次**才强制填生产日期与标识日期（`validateBaseInfo(input, { requireIdentityDate })`）。
- 有效期比较锚点：填了标识日期就比标识日期（新口径，错误码 `EXPIRE_NOT_AFTER_IDENTITY`），
  老批次没有标识日期则回退成与生产日期比（`EXPIRE_NOT_AFTER_PRODUCE`）—— 老数据行为不变。
- 四个控件用同一套 `.field-label` + `.input code`（日期用 `picker` + `.picker-value`），
  真机实测高度/字号/圆角/边框四项完全一致。

### 3.4.1 批量连续扫码（`plus.barcode`）—— 启动链收在 `utils/batchBarcodeScanner.js`

粒子环节的「**批量连续扫码**」用 `plus.barcode` 常驻原生控件连续取景。为什么不能沿用
`uni.scanCode`：它是「一次调一个码」的系统扫码界面，扫一页几十个竖向条码要反复开合。

**这一版为什么重写启动链**：旧实现只 `start()` 一次，`onmarked` 回来之后**从不重新
`start()`** —— 第一枚码扫完扫码头就停了，「连续扫码」实际只能扫一枚。现在按官方语义
（HBuilderX 内置 `plus.d.ts` + html5plus barcode 文档）重写：

| 环节 | 现在的做法 |
| --- | --- |
| 挂载 | `plus.barcode.create(id, filters, styles, autoDecodeCharset)` **不会自动显示**，必须再 `Webview.append(barcode)` 才挂得上；两步都在 `utils/batchBarcodeScanner.js`，页面不直接碰 `plus.barcode` |
| 连续 | `start → onmarked → 业务处理 → 按结果等 60/120/200ms → start → …`，由 `scheduleNextScan()` 统一调度。**Barcode 只 create 一次、append 一次，之后反复 start**；`finally` 保证业务失败（格式错 / 重复 / 跨罐报警）也不停摄像头 |
| 停止 | `cancel()` 停摄像头（之后可再 `start()`）、`close()` 释放控件（之后对象不可用）；四个出口统一走 `cancel + close`：① 点「完成扫码」② 切 Tab（`onHide`）③ 离开页面（`onUnload`）④ 相位离开粒子采集（`reload()`） |
| 状态机 | `idle / starting / scanning / processing / stopping / error`，状态直接显示在面板上；狂点按钮只会被 `ALREADY_RUNNING` 挡回，**不会创建第二个控件** |
| 布局 | 原生控件按页面「留位卡片」`#batch-scan-slot` 的**实测矩形**挂载（`position:'static'`，随页面滚动），不覆盖下方按钮，按钮照常可点 |
| 异常 | 初始化失败不改业务模式：卡片里显示原因 + 「🔄 重新启动扫码」（内部 `stop → create → append → start`，不复用已 close 的对象），`onerror` 全程记日志 |
| 权限 | 起扫码前先申请 CAMERA，被拒时给「去系统设置」引导（与单码扫码共用 `ensureCamera()`） |
| 码制 | **只配 `CODE128`** —— 阶段 D 用 zxing-cpp 解码实拍标签取证：`15-箱码` / `17·18·19-条形码` 全是 Code 128，`16-罐码` 是二维码（罐号走 `uni.scanCode`）。换码制只改 `DEFAULT_FILTER_NAMES` 一行 |
| 去重 | 三层：瞬时防抖 2.5 秒（扫码器层，静默）→ 本罐会话去重（短震 + Toast）→ 跨罐/跨箱报警（长震 + 弹窗）。详见 §3.4.3 |
| 盲区 | **每一枚码都会让摄像头停一下再重启**，这段空窗期就是漏扫的来源。所以按结果分档：入库 200ms / 业务拒绝 120ms / 瞬时忽略 60ms（`RESTART_DELAY_*_MS`），能少等的绝不多等 |
| 提示音 | 面板上有「🔔 提示音开 / 🔕 提示音关」按钮，随时可关（只留震动），设置落盘、下一轮识别即生效 |
| 版式 | 提示音按钮与「扫描中」徽标同款几何（同高 23.7px、同圆角 999px、同 12px 字号、同 2px 10px 内边距），实测上下差 0px；注意别再用 `button.ghost`（它的 `margin-top:16rpx` 会把按钮顶歪） |
| 日志 | 全程 `[BatchScan]` 前缀：`creating barcode / barcode created / barcode appended / barcode started / marked / restart scanning / destroyed` |

面板常驻一行**五维运行统计**：
`识别 N 枚 · 自动重启 N 次 · 同码瞬时忽略 N 次 · 业务重复 N 次 · 异常 N 次`，
有非法字符或其它拒绝时再补两项，另外带平均每枚间隔。现场一眼能判断「摄像头还在不在跑」，
收工时还会把整轮统计（含**逐枚耗时 `intervalMs` 数组**）落盘到
`pharmrelate.batchscan.lastRun` —— HBuilderX 基座的 console 在电脑上读不到，
真机压测的数据只能靠这条路径带出来。

**降级口径（没变）**：`plus.barcode` 起不来时界面明确提示，并保留「单次扫码一个」与
「手动输入」两条通道。**本项目没有 OCR 引擎**（实测：`plus.barcode` 无 `scanImage`、
`plus` 无任何 ocr/ai/ml/vision 命名空间），所以降级只能是「拍照 → 人眼读数 → 手动输入」，
**不存在「在照片上点击识别」这种能力**。

### 3.4.2 虚拟箱（箱数 = 0）

设置页的「纸箱数」下拉是 `[0,1,2,3,4,5]`。选 **0** 表示**本次作业不扫箱号**——
业务上它可能是「这批货没有纸箱，只有罐」，也可能是「有箱但不扫」，
两种情况**统一处理**：数据层自动生成 1 个虚拟箱。

| 项 | 值 |
| --- | --- |
| 虚拟箱号 | `80217619999999999999`（9 打头，一眼可辨是程序生成的） |
| 落库形态 | `boxes: [{ boxCode: 虚拟箱号, virtual: true, reviewConfirmed: true, cans: [...] }]` |
| 向导 | 箱号已写好 → **直接跳过拍箱号**，从罐号开始 |
| 箱核对 | `reviewConfirmed` 预置 true，不再多问一次 |
| XML | 仍然产出 `packLayer="3"` 节点，罐的 `parentCode` 指向虚拟箱 —— **绝不会导出空文件** |

之所以必须造这个虚拟箱：`xmlGenerator.exportNodes()` 对**箱号为空**的箱是整箱跳过的
（连同它的罐与粒子），不补虚拟节点的话「0 箱」导出的 XML 会一条记录都没有。
另外 `80217610000000000000` 这个号**不能用**——它被后端 parentCode 完整性测试当作反例夹具占用了。

设置页选 0 时会显式提示操作员：「本次不扫描箱号，系统会自动生成虚拟箱节点」；
扫码页的槽位列表里那一箱也会标成「箱 1（虚拟箱）」。

### 3.4.3 去重规则（折中方案）

连续扫码每次收到码都会过**三层闸**，**区分「镜头里的重复」与「真重复 / 扫错罐」**，
三层反馈强度刻意不同（2026-09-30 压测后定稿）：

| 层 | 情形 | 处理 |
| --- | --- | --- |
| 1 · 瞬时防抖（扫码器层，`INSTANT_DEBOUNCE_MS = 2500`） | 同一条码在 2.5 秒内被重复解码（码还在镜头里） | **完全静默**：不震动、不 Toast、不写库；只累加 `rejectReasons.instantIgnore` |
| 2 · 本罐去重（页面层 `sessionScanned` Set） | 本次会话内已经扫过的码 | **短震动** `vibrateShort({type:'light'})` + Toast「本次已扫过，重复码忽略」，不写库 |
| 3 · 跨罐 / 跨箱（数据层 `applyCodes`） | 该码在本批次的别的罐/箱里已存在 | 长震动 + **弹窗要求核对**（可能是扫到了别的罐的标签） |
| 附带 | 含非数字字符（字母 O 混入等） | **报警拒绝**，绝不 `\D` 全剔 |

> 窗口为什么是 2500ms：54 枚标签压测跑了 196 次识别，其中 80 次是「1.2 秒内同码重复」、
> 62 次是「超过 1.2 秒后同码又进业务层」——那 62 次全是同一枚标签在镜头里多停了一会儿。
> 放宽到 2.5 秒把这类噪声吸收在扫码器层，第 2、3 层继续兜底，**合法新码一枚都不会少**。

会话集合用 `Set`，挂在组件实例上（不进 `data`，不需要 Vue 建响应式）。
换箱 / 换罐 / 换相位会清空它——否则跨罐的真码会被误判成「会话内重复」而静默吞掉。

### 3.4.4 漏扫提示与「本罐先结束」

### 3.4.4b 手动补录 · 批量录入 · 图库辅助（v1.4.2）

现场三类"没扫上"的情况都靠人工兜底：漏扫、标签破损、别人发来的标签照片。

**① 槽位弹窗升级为「填 / 改」通用**（`pages/scan/scan.vue` + `services/particleInput.js`）

| 行为 | 口径 |
| --- | --- |
| 空槽位 | 弹窗标题标「补录」，按钮是「填入」→ 调 `fillSlot()` 写进**指定槽位** |
| 已填槽位 | 按钮是「替换」→ 调 `replaceSlot()`（原逻辑） |
| 输入 13 位序列号 | 自动补前缀 `8206233` 成完整 20 位（`normalizeParticleCode`） |
| 输入完整 20 位 | 前缀正确则**原样**写入，绝不重复加前缀；前缀错误直接拦 |
| 输入 27 位（前缀敲两遍） | 去掉多余那一遍前缀后按 20 位校验（可审计的确定性规则，不做猜测） |
| 空输入 / 含字母 / 长度不对 | Toast + **弹窗保持打开**（旧实现无条件关窗，操作员以为没反应） |
| 重复码 | `findUsage` 全批次查重 → Toast 说明「已被使用于箱 X 罐 Y / 槽位 Z」，不覆盖 |

**② 批量手动录入**（`fillParticleCodesIntoEmptySlots()`，与将来的 OCR 共用同一条入口）

- 输入框改为多行 `textarea`，支持空格 / 换行 / Tab / 中英文逗号 / 中英文分号 / 顿号分隔；
- 一次可粘贴 6 个以上序列号，13 位自动补前缀；
- 去重三层：输入内重复、与本罐已有码重复、跨罐重复（都汇总成一句话，不连弹几十个 Toast）；
- **溢出策略改为「能填的先填」**：超出的码明确列出「超出计划 N 枚未写入」，并把未写入的码**留在输入框里**供复制；
  扫码通道仍保持原有的「整帧拒绝」策略（防误读帧写成半截数据）；
- 计划粒子数**不会**被批量录入撑大。

**③ 图库辅助录入（v1.4.2 人工读数；v1.4.3 可降级 OCR；v1.4.4 起本机自动识别条码）**

- 「拍照识别」的 `sourceType` 从 `['camera']` 扩到 `['camera','album']`：箱号/罐号可以直接选图库照片；
- 粒子相位的手动输入卡里新增「🖼 从图库选图辅助录入」，弹「拍摄 / 从相册选择」面板，
  选图后进大图浮层（放大 / 缩小 / 旋转 / 复位），**下面就是同一个多行批量录入框**；
- **v1.4.4 起**：选图后本机会**自动解码标签上的 Code 128 条码**（renderjs 视图层 +
  zxing-wasm，纯离线、不装插件），结果进候选列表，操作员确认后才写槽位（见 ⑤）；
  端侧 OCR 仍然没有（无原生插件、无模型），条码没解出来的部分照旧手动录入。
  照片只在页面内存里、用完即弃。

**⑤ 本机条码自动识别（v1.4.4：renderjs 视图层 + zxing-wasm，免插件）**

链路：`图库选图 → 服务层读成 data URL → renderjs 视图层解码 → 候选列表 → 人工确认 → fillParticleCodesIntoEmptySlots()`

为什么在视图层：`readBarcodes()` 在 **DCloud JSCore 服务层永不返回**（实测 12MP / 3.4MP / 800px 全卡 >35 秒），
因为服务层没有 `Blob` / `Image` / `canvas` / `createImageBitmap`；同一套算法在 Node 侧 171ms 出结果。
renderjs 是完整浏览器环境，换过去以后真机 9 码标签页 349ms 全中。

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 视图层解码器 | `pages/scan/scan.vue` 的 `<script module="imageDecoder" lang="renderjs">` | dataURL → `createImageBitmap`（顺带 EXIF 归一）→ canvas 取像素 → `readBarcodes()` → `$ownerInstance.callMethod('onDecodeResult', …)` |
| 服务层支撑 | `services/imageCodeDecoder.js` | 图片读 data URL（带"先复制进沙箱"兜底）、wasm 读 base64（单例缓存）、`buildDigitRoi()` 纯函数、开关与超时常量 |
| 引擎 | `static/zxing/zxing_reader.wasm`（931KB）+ `services/zxing/reader.js` | zxing-wasm 3.1.4（MIT）；wasm 用 `setZXingModuleOverrides({ wasmBinary })` 注入，**不 fetch** |
| 业务 | `pages/scan/scan.vue` | `expectedCount = 当前罐剩余空槽位`；够数立即停、不调 OCR；全流程只出候选，绝不直接写槽位 |

三条兜底（都不会卡界面）：条码够数 → 直接用；不够 → 试 ML Kit OCR（标准基座没有就跳过，不算失败）；
都没有 → 如实说明原因 + 手动录入。**硬超时 12 秒**（`DECODER_TIMEOUT_MS`），5 秒软超时先改文案让人可以提前手输。

`IMAGE_CODE_DECODER_ENABLED` 是总开关，置 `false` 即整体退回纯手动录入。
真机验收见 `private/测试输出/Android-v1.4.4-免插件条码解码-20261002/真机测试报告-renderjs条码解码.md`。

**④ 离线 OCR（v1.4.3：可降级桥接 + UTS 插件骨架）**

链路：`图库选图 → 离线 OCR（可选）→ 候选列表人工确认 → 同一个批量写入出口`。

| 层 | 文件 | 说明 |
| --- | --- | --- |
| 桥接 | `services/ocr.js` | 先试 nativeplugins 实例、再试 UTS 模块；**都没有 → `OCR_PLUGIN_MISSING`**，页面切手动录入，不报错、不阻断 |
| 解析（纯函数，已单测） | `services/particleInput.js` → `parseOcrParticleCandidates()` | 抽数字 → **按 bounding box 重排**（ML Kit 已知顺序错乱）→ `normalizeParticleCode()` → 分类 `{valid, duplicateInInput, duplicateInCurrentBatch, invalid}` |
| 写入 | `localBatch.fillParticleCodesIntoEmptySlots()` | **OCR 绝不直接写槽位**，必须操作员确认后走这个唯一出口 |
| 插件 | `uni_modules/pharmrelate-ocr/` | UTS 骨架 + `com.google.mlkit:text-recognition:16.0.1`（bundled，离线，+≈4MB），**源码未编译** |

真机实测（标准基座＝无插件）：状态徽标显示「无 OCR 插件」，多行手动录入照常可用 ✔。
选图后的 `imagePath` 形态：**`file://` + 应用私有目录真实路径**
（uni-app 会把选中的图压缩复制到 `.../doc/uniapp_temp/compressed/<时间戳>_<原名>.jpg`），
**不是 `content://`** —— 插件里的 `toUri()` 因此按 file 路径处理（见 UTS 源码注释）。

三条采集通道（单次扫码 / 批量连续扫码 / 拍照识别）全部保留，人工入口只增不减。

- 粒子相位顶部有**高亮警告条**：`⚠️ 可能漏扫：当前已扫 X 个，还差 Y 个未扫描`；
- 新增「**本罐先结束**」按钮：没扫满时弹二次确认，确认后由 `forceEndCan()` 收尾。

为什么需要这个按钮：`deriveWizard()` 只有在**已扫满**之后才推出 `CAN_REVIEW` 相位，
所以「没扫满想收尾」原本根本走不到「本罐确认无误」那个按钮上，只能靠「结束整批」绕。
配套地，`deriveWizard()` 改成 `filled < planned && !can.confirmed` 才回粒子相位——
已确认的罐不再要求扫满，缺漏交给整体核对如实显示（与提前结束整批同一口径）。

### 3.4.5 日期与下拉

- 界面标签「生产日期」→「**标示日期**」，自动有效期由 **+30 天改为 +60 天**；
  **XML 属性名 `madeDate` 一个字没动**（黄金基准是字节级冻结的）；
- 手动改过有效期后不会被自动计算覆盖；
- 「纸箱数」「罐数」由步进器改成 `picker` 下拉（箱 `[0..5]`、罐 `[1..5]`）。

---

## 四、本地数据层设计（`services/localBatch.js`）

纯 ESM，**不 import 任何模块**（`uni` 通过可注入的 storage adapter 访问），
因此同一份代码能直接被 Node 单测加载。

| 分组 | 关键导出 | 说明 |
| --- | --- | --- |
| 常量 | `BARCODE_LENGTH`、`CODE_PREFIXES`、`CASCADE`、`FIXED_PARAMS`、`MAX_BOXES`、`MIN_BOXES`、`MIN_STRUCTURE_GROUPS`、`VIRTUAL_BOX_CODE` | 箱/罐/粒子**统一 20 位 + 前缀**（箱 `8021761` / 罐 `8021762` / 粒子 `8206233`），层级只看前缀；`cascade="1:5:2500"` 固定字面量；`MIN_BOXES = 0`（0 = 不扫箱号 → 虚拟箱），`MIN_STRUCTURE_GROUPS = 1`（数据结构里至少 1 组罐）；13 项系统固定参数 |
| 存储 | `setStorageAdapter` `loadBatches` `saveBatch` `getActiveBatch` `listBatches` `removeBatch` `clearAll` | `uni.setStorageSync` 封装，可注入内存实现做单测；读时自动迁移老数据 |
| 迁移 | `migrateBatch` | v1.3.0 单箱 → v1.3.1 多箱，幂等 |
| 校验 | `classifyCode` `cleanLayerCode` `extractDigits` `validateLayerCode` `describeCodeIssue` `validateBaseInfo` `validateStructure` `particleTotal` `planCounts` `planSummary` `progress` | 分层校验（箱/罐/粒子统一 20 位 + 前缀，箱/罐先剥连字符再判）；`extractDigits` 返回 `{code, illegal}` —— **只清已知分隔符，残留非数字字符交调用方报警**；结构校验吃「箱 → 罐」二维数组，`{virtualBox:true}` 时只允许 1 组罐；每罐 1~2500、**单批 ≤12500 硬上限** |
| 批次 | `createDraft` `updateBaseInfo` `buildBoxes` `saveStructure` `transition` | 状态机 `草稿 → 采集中 → 待核对 → 已核对`，非法流转拒绝；`buildBoxes/saveStructure` 接受 `{virtualBox}`（选 0 箱时预填虚拟箱号 + `reviewConfirmed`） |
| 向导 | `deriveWizard` `findCan` `findUsage` `applyCodes` `confirmCanReview` `confirmBoxReview` `forceEndCan` `finishRemaining` `registerEarlyEnd` | 相位见 §2.2；错层/重复/溢出拦截；`findUsage` 是**分层作用域**查重（箱全批唯一 / 罐本箱唯一 / 粒子全批唯一）；`forceEndCan` 让「没扫满也能收尾」（见 §3.4.4） |
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
├── utils/
│   └── batchBarcodeScanner.js  ★ 批量连续扫码启动链（create/append/start 循环、状态机、瞬时防抖、释放）
├── services/particleInput.js   ★ 粒子码手动录入解析层（13 位补前缀 / 20 位原样 / 双前缀剥离 / 批量分隔符）
├── tests/
│   ├── localBatch.test.mjs          本地数据层单测
│   ├── batchBarcodeScanner.test.mjs 扫码启动链单测（假 plus 驱动，PC 上就能验状态机与重启）
│   ├── particleInput.test.mjs       手动录入解析层单测（前缀规则 / 分隔符 / 去重分类）
│   ├── slotFill.test.mjs            槽位补录与批量录入单测（fillSlot / 部分溢出 / 撤销）
│   ├── numberRecognizer.test.mjs    识别契约层单测
│   └── xmlGenerator.test.mjs        XML 生成器单测（与后端黄金基准字节级比对）
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
# 单测共 656 项：本地数据层 260 + 识别契约层 66 + XML 生成器 57 + 扫码启动链 101
#              + 手动录入解析 63 + 槽位补录/批量录入 59 + OCR 候选 50
# （Node 直跑，无需 HBuilderX；扫码启动链用假 plus + 假定时器驱动，真机只验摄像头行为）
cd "<ANDROID_PROJECT_DIR>"
node tests/localBatch.test.mjs
node tests/batchBarcodeScanner.test.mjs
node tests/particleInput.test.mjs
node tests/slotFill.test.mjs
node tests/ocrCandidates.test.mjs
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
- [x] 格式校验：非法（长度不对 / 含字母 / 错前缀）→ 弹「箱号必须为 20 位数字，且前缀为 8021761」
- [x] 合法输入 → 自动收起输入区 → 相位推进 `box → can`（或 `can → particle`）
- [x] 拍照识别：调系统相机拍照 → 浮层大图（放大/缩小/旋转/复位）→ 照着照片手输；照片用完即弃不落本机
- [x] 原扫码流程不受影响（正常条码仍可直接扫出并推进）
- [x] 单测 195 项全过（含 `validateLayerCode` 的合法/短号/错前缀/含字母/空串用例）
- [x] 真机 15 项断言全过（含相机调起、照片确认浮层、非法格式拦截、推进到步骤 2）

### 分层查重与短号历史兼容（2026-09-28 增补，v1.4.0 沿用）

- [x] 分层查重：箱号全批唯一、罐号本箱内唯一、粒子码全批唯一
- [x] 粒子规则一个字没动（20 位 + 前缀 8206233）
- [x] 历史批次里已存的短号箱号（如 `1`）**保持原样、不报错、不迁移**

### 箱号条码 / 罐号二维码识别回归与 UI 适配（v1.4.0）

**推翻性变更**：现场实物（`15-箱码.jpg` 一维条形码、`16-罐码.jpg` 方形二维码）证实箱/罐都是
标准 20 位追溯码，v1.3.2 的「短号 1~9999」口径**彻底作废**。

- [x] 扫码按层级限制码制：箱号 `scanType:['barCode']`、罐号 `scanType:['qrCode']`、粒子 `['barCode']`
      （`scanCode(scanType, callback)` 参数化，不再写死条形码）
- [x] 新增 `cleanLayerCode(value, layer)`：箱/罐先 `replace(/-/g,'')`，粒子不动；清洗幂等
- [x] **清洗顺序**：`considerSingle()` 入口先清洗 → 再校验 → 再弹确认框，
      保证「弹窗显示什么，库里就存什么」；`commitLayerCode()` 与 `applyCodes()` 再兜一层
- [x] 删除 `MAX_NATURAL` / `NATURAL_PATTERN` / `isNaturalCode()`，箱/罐回归 20 位 + 前缀校验
- [x] 确认弹窗带前缀：「这是第 X 箱的箱号吗？(8021761...)」/「这是箱 X 罐 Y 号吗？(8021762...)」
- [x] 清空全部「短号 / 上限 9999」遗留文案（界面提示、底部说明、向导 prompt、代码注释）
- [x] 20 位长码折行：`App.vue` 的 `.code`、`scan.vue` 的槽位箱号/罐号行、`status.vue` 的逐箱明细箱号行
      都加 `word-break: break-all`，窄屏不被裁切或挤压
- [x] `numberRecognizer.js` 同步口径：`sanitizeDigits()` 剔除**夹在数字之间**的分段连字符
      （行首负号保留，`-1` 仍按「不猜测」判失败）；文件头规范改为 20 位追溯码
- [x] 手动输入 placeholder：「请输入 20 位箱号（前缀 8021761）」/「请输入 20 位罐号（前缀 8021762）」
- [x] 单测 341 项全过（localBatch 225 + numberRecognizer 66 + xmlGenerator 50），含连字符清洗用例
- [x] `check.ps1` 回归全过（后端与电脑端一行未改）
- [ ] 真机验证：扫箱号条形码 / 扫罐号二维码并清洗 / 错误前缀拦截 / 长码折行 —— 待现场取证

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

### 追溯码视觉识别契约层与降级（v1.3.4 增补，v1.4.0 改口径）

- [x] 新增 `services/numberRecognizer.js`：契约 `{success, number, confidence, sourceType, needsConfirmation, candidates}`
- [x] 默认 Provider `manualConfirmProvider` 严格 `success:false`（本机无识别引擎，绝不猜测）
- [x] `normalizeResult` 严格净化：`1↵ → 1`、剔除空格/下划线/光标/零宽字符/**分段连字符**；
      `I23`/`O0`/`1.5`/`-1` 一律判失败（行首负号保留，不会被当成排版噪声吃掉）
- [x] 置信度阈值 0.70；`< 0.70` 或失败 → `needsConfirmation = true`
- [x] 多候选 `candidates` 保留，业务层 `length > 1` → 震动 + 多码报警、阻止推进
- [x] 拍照通道接契约层：成功→带置信度的确认框；失败→明确降级提示（浮层可滚动，提示不会被顶出屏幕）
- [x] 手动输入 placeholder 改为「请输入 20 位箱号（前缀 8021761）」
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

### 批量连续扫码 · 虚拟箱 · 去重（并入 v1.4.0）

- [x] 粒子环节新增「批量连续扫码」（`plus.barcode.create` + `onmarked`）
- [x] 资源释放四条出口齐全：完成扫码 / `onHide`（切 Tab）/ `onUnload` / 相位离开粒子采集
- [x] 降级路径明确：`plus.barcode` 起不来时提示并保留「单次扫码一个」与手动输入；
      **不承诺「照片上点击识别」**（本机无 OCR 引擎）
- [x] 箱数下拉 `[0..5]`；选 0 生成虚拟箱 `80217619999999999999`
      （预填箱号 + `reviewConfirmed=true`，向导跳过拍箱号）
- [x] 虚拟箱导出仍有 `packLayer="3"` 节点、罐的 `parentCode` 指向虚拟箱、**XML 非空**
      （单测锁定：3 个 Code 节点、0 个跳过）
- [x] 去重折中方案：会话内重复 → 震动 + Toast 静默忽略；跨罐/跨箱 → 报警 + 弹窗核对
- [x] `extractDigits()` 严格化：只清已知分隔符，残留非数字字符报警，**绝不做 `\D` 全剔**
- [x] 箱号确认弹窗文案改为「这是箱号吗？(8021761...)」，[不正确] 自动重新调起摄像头
- [x] 漏扫高亮警告条 + 「本罐先结束」二次确认（`forceEndCan()`）
- [x] `deriveWizard()`：已确认的罐不再要求扫满（`filled < planned && !can.confirmed`）
- [x] 界面「生产日期」→「标示日期」，自动有效期 +30 → **+60 天**；**XML 属性 `madeDate` 未动**
- [x] 箱数/罐数由步进器改为 `picker` 下拉
- [x] 单测 373 项全过（localBatch 250 + numberRecognizer 66 + xmlGenerator 57）
- [x] `check.ps1 -Full` 13/13 全过（后端与电脑端一行未改）
- [x] 真机验证：虚拟箱导出 XML / 漏扫警告（v1.3.1 起逐版取证）
- [ ] 真机验证：批量连续扫码连续扫 ≥20 枚（见下一节，待现场取证）

### 批量连续扫码启动链重构（2026-09-30）

- [x] 启动链收进 `utils/batchBarcodeScanner.js`：页面只注入「权限 / Webview / 业务处理 / 状态回调」
- [x] 修复「只扫一枚」：`onmarked` 处理完统一 `scheduleNextScan()` 重新 `start()`；
      **一次 create、一次 append、多次 start**
- [x] 删除无效参数 `start({ conceal: true })`（官方 `BarcodeOptions` 只有 `conserve/filename/vibrate/sound`）
- [x] 六个状态：`idle / starting / scanning / processing / stopping / error`，重入按 `ALREADY_RUNNING` 挡回
- [x] 瞬时防抖（同码停镜头不刷屏）→ 与「本罐去重 / 跨罐报警」组成三层去重；
      窗口 1.2 秒 → **2.5 秒**（`INSTANT_DEBOUNCE_MS`，2026-09-30 压测后拍板）
- [x] 业务校验失败不停摄像头（`finally` 里恢复下一轮识别）
- [x] 页面留位卡片 `#batch-scan-slot` + 实测矩形挂载：原生控件不再吃掉按钮的触摸事件
- [x] 「🔄 重新启动扫码」入口 + 面板常驻运行统计（识别 / 自动重启 / 瞬时重复）
- [x] 相机权限前置（被拒给「去系统设置」引导），`onerror` 全程日志
- [x] 码制按实据收窄为 `CODE128`（zxing-cpp 解码实拍标签取证，见 §3.4.1）
- [x] 单测 467 项全过（扫码启动链 94 项：状态机 / 重启 / 防抖 2.5s / 重入 / 释放 / 权限异常 /
      五维统计四桶归类 / 逐枚耗时 / 收工落盘）
- [x] 真机链路自检通过（`private/测试输出/Android-v1.4.1-批量连续扫码-20260930/`）：
      启动后相机被本应用占用、狂点按钮不炸、完成扫码即释放、切 Tab（onHide）即释放、再次进入能重启
- [x] 真机人肉连续扫码（2026-09-30 现场）：**一个会话连扫 54 枚真标签**，
      `onmarked` 196 次 / 自动重启 196 次（1:1，零失败）/ 瞬时重复 80 次 /
      54 枚全部唯一入库、格式全对、无一枚重复写库；无 ERROR、无崩溃；
      证据：`private/测试输出/Android-v1.4.1-批量连续扫码-20260930/压测报告-54枚.md`
- [x] 压测暴露的两个问题当场修掉：重复码反馈由长震动改短震动；统计行扩为
      `识别 / 自动重启 / 同码瞬时忽略 / 业务重复 / 异常` 五项
- [x] 漏扫主因修复：重启盲区按结果分档（入库 200ms / 业务拒绝 120ms / 瞬时忽略 60ms）
- [x] 扫码提示音可取消：面板按钮开关 + 落盘，震动反馈保留
- [x] 统计行补「扫错层 N 次」（`WRONG_LAYER`：把箱码/罐码扫进了粒子环节）
- [x] `rejectReasons` 按四个桶归类：`instantIgnore / businessDuplicate / invalidChar / unknown`
      （原始原因码另存 `rejectReasonCodes`，诊断用）
- [x] 逐枚耗时采集：记录每枚**成功入库**的时间戳，收工时连同 `intervalMs` 数组落盘
      `pharmrelate.batchscan.lastRun`，压测脚本用 `--read-only` 直接读出来出报告
- [ ] 防抖放宽到 2.5 秒后的真机复跑（54 枚标签，目标：业务重复 <10 次、无丢码、平均间隔 ≤5 秒）

### OCR 候选列表删除修复 + 视图层状态同步（v1.4.5，2026-10-02）

**症状**：图库识别出候选后点「删除」看着没反应 —— 行还在、还是绿色「有效」。

**根因**：纯显示层 bug。`ocrListRows` 这个 computed 只从 `ocrCandidates` 派生、**没读 `ocrDeleted`**；
而 `ocrFillableCodes` 读了。所以"计数会从 9 变 8、列表却纹丝不动"。数据层一直是对的，
被删的码本来就不会写进槽位（真机取证：按钮 `（9）→（8）`，槽位里没有被删的码）。

- [x] 抽纯函数到 `services/particleInput.js`：`buildOcrCandidateRows(parsed, deletedMap)` +
      `selectFillableOcrCodes(rows)`；页面只负责调用（业务规则留在 JS 服务层）
- [x] `ocrListRows` 改为 `buildOcrCandidateRows(this.ocrCandidates, this.ocrDeleted)` ← **修复核心**
- [x] `ocrFillableCodes` 改为 `selectFillableOcrCodes(this.ocrListRows)`（与视图同源）
- [x] `removeOcrCandidate` 保持不可变替换 + 补**幂等保护**（已删过的直接 return）
- [x] 已删除条目**保留在列表**（可追溯，删错用「重新识别」找回）：行底 `#fafafa`、
      序号与码文字 `#909399` + `line-through`、徽标换 `badge-deleted`（`App.vue` 新增）、
      按钮变「已删除」且 disabled
- [x] 状态行追加「已手动删除 N 条（不计入填入，可用「重新识别」找回）」，复位后自动消失
- [x] `submitOcrCandidates()` 入口再过滤一次 `deleted`（双保险）；为空 Toast「没有可填入的有效码」
- [x] 「重新识别 / 清空识别结果」会把删除态一起复位
- [x] 单测新增 `tests/ocrCandidateRows.test.mjs`（46 项）：删 1 条 / 删重复项 / 删光 / 幂等 /
      清空复位 / key 不串行 / 空入参不抛错。全量 **746 项全过**；`check-uniapp.ps1` 通过
- [x] 真机 26 项断言全过（荣耀 BKQ-AN90）：删除后第 1 行立刻变灰 + 删除线 + 按钮 disabled、
      计数 9→8、确认填入后被删码未写入槽位、连点幂等无异常、全删后按钮 disabled
- [x] 证据：`private/测试输出/Android-v1.4.5-OCR候选删除修复-20261002/修复说明-OCR候选删除.md`
      （4 张截图 + `device-delete-check.mjs` 复现脚本）

### 条码解码迁移至 renderjs 视图层（v1.4.4，2026-10-02）

- [x] 解码本体从服务层搬到 **renderjs 视图层**：`scan.vue` 内联 `module="imageDecoder"` + `<view class="decoder-bridge" :change:prop>`，
      结果经 `$ownerInstance.callMethod('onDecodeResult', …)` 回服务层（业务链路一行没改）
- [x] wasm 注入仍是"服务层 `plus.io` 读 base64 → `setZXingModuleOverrides({ wasmBinary })`"，**不 fetch**；
      打包后 `prepareZXingModule` 具名导入取不到，改为靠 `readBarcodes()` 首次调用惰性初始化
- [x] 删除 `services/zxing/jpegDecoder.js`（视图层用 `createImageBitmap` 解图，不再需要纯 JS JPEG 解码）
- [x] R2 分段计时落盘 `pharmrelate.batchscan.lastDecode`：
      `loadImageMs / imageDecodeMs / barcodeDecodeMs / wasmInitMs / wasmReuse / parseMs / ocrMs / totalMs` + debug（宽高/朝向/像素/均值）
- [x] R3 `expectedCount = currentCanPlanned − currentCanScanned`：为 0 直接跳过自动识别（提示"当前罐已满"），够数不调 OCR
- [x] R4 `buildDigitRoi()` 纯函数（条码框 → 下方数字 ROI）+ 单测；ML Kit 运行时部分标注**待自定义基座真机验证**
- [x] R5 `mergeAdjacentDigitBlocks()`：同行 + 相邻 + 合并后恰好 13/20 位才接受，保留 `mergedFrom`，**不猜字符、不补零**
- [x] R6 EXIF 归一走 `createImageBitmap(blob, { imageOrientation: 'from-image' })`；真机竖拍 3072×4096 实测 `oriented:true`
- [x] R7 状态机 `decoding / success / partial / timeout / unavailable`；5s 软超时改文案、12s 硬超时兜底；任何异常都落到"候选 + 手动补录"
- [x] `DECODER_MAX_SIDE` 定 4096：2400px 时 9 码标签页只能解 8 枚，原分辨率全中；条码解码本体只要 9~56ms，性能不是瓶颈
- [x] 单测 **700 项全过**（新增 imageDecoder 22 项：ROI / 候选归一 / EXIF 归一）；`scripts/check-uniapp.ps1` 通过
- [x] 真机验收（荣耀 BKQ-AN90 / Android 16 / 标准基座）**T1~T13 全过**：
      9 码标签页 **9/9（349ms，端到端 578ms）**、24 码 **22/24（344ms）**、6 码 **6/6（352ms）**、
      倾斜 8° 5 枚、反光 7 枚（含 1 枚合成过曝伪码，见报告 §4）、远距离 5 枚；
      识别率 100%（T5）/ 91.7%（T6），错误识别率 1.7%（≤5% 达标）
- [x] 异常与降级实测：损坏图片 690ms 出「解码失败」+ 手动录入可用；
      **故障注入**把硬超时临时改 250ms → 命中「自动识别超时」分支且不卡界面（改回 12000 后复跑 T1~T4 全通）
- [x] 离线实测：WebView 置离线（`navigator.onLine=false`）后仍 9/9，全程 **0 条 http(s) 请求**
- [x] 生命周期实测：选图后切 Tab 往返，两页正常、未捕获异常 0 条
- [ ] 物理飞行模式真机复跑（本机是 ADB-over-Wi-Fi，开飞行模式会断掉唯一调试链路；建议 USB 连接下补）
- [x] 证据：`private/测试输出/Android-v1.4.4-免插件条码解码-20261002/真机测试报告-renderjs条码解码.md`
      （含 T1~T13 表格、分段耗时、12 张截图、`device-*.mjs` 复现脚本）

### 批次基础信息四字段 + 图库离线 OCR 可降级（v1.4.3，2026-10-02）

- [x] 设置页字段顺序固定为：批号 → **生产日期** → **标识日期** → 有效期（四个控件几何实测一致）
- [x] 文案「标示日期」→「标识日期」；`produceDate` 显示为「生产日期」，**XML `madeDate` 属性名未动**
- [x] 新增本机字段 `identityDate`（标识日期），**只存不导出**；有效期自动 = 标识日期 + 60 天
- [x] 老批次（无 `identityDate`）打开设置页不报错、可照常保存；只有新批次强制填两个日期
- [x] 新增 `services/ocr.js` 可降级桥接：无插件 → `OCR_PLUGIN_MISSING` → 手动录入（真机实测 ✔）
- [x] 新增 `parseOcrParticleCandidates()`：bbox 重排 + 标准化 + 三层分类（`tests/ocrCandidates.test.mjs` 50 项）
- [x] 新增 `uni_modules/pharmrelate-ocr/` UTS 插件骨架（ML Kit 16.0.1 bundled，minSdk 21 无需提升）
- [x] 真机实测 imagePath = `file://…/doc/uniapp_temp/compressed/…jpg`（**不是 content://**）
- [x] 单测 **656 项全过**（新增 ocrCandidates 50 项、localBatch 基础信息 10 项）
- [x] UTS 插件**未编译**（本机无 DCloud 离线 SDK），编译与真机 PoC 由业务方打包后执行

### 手动补录 · 批量录入 · 图库辅助（v1.4.2，2026-10-02）

- [x] 槽位弹窗升级为「填 / 改」通用：空槽位走 `fillSlot()`，已填槽位走 `replaceSlot()`
- [x] 13 位序列号自动补前缀 `8206233`；20 位码原样写入（不重复加前缀）；双前缀可剥离
- [x] 空输入 / 含字母 / 长度不对：Toast + **弹窗保持打开**（不再无条件关窗）
- [x] 重复码走 `findUsage` 全批查重，提示「已被使用于箱 X 罐 Y / 槽位 Z」，不覆盖原槽位
- [x] 批量录入改多行 `textarea`，支持空格/换行/Tab/中英文逗号分号/顿号，一次可粘 6+ 个
- [x] 批量溢出改为「能填的先填」+「超出计划 N 枚未写入」明示，未写入的码留在输入框里
- [x] 扫码通道的「整帧拒绝」策略保持不变（两套策略各管一条通道，边界写清楚）
- [x] 计划粒子数不会被批量录入撑大（单测锁定）
- [x] 拍照识别 `sourceType` 扩为 `['camera','album']`；粒子相位新增「🖼 从图库选图辅助录入」
- [x] 图库浮层：大图 + 放大/缩小/旋转/复位 + 同一个多行录入框；**不承诺自动识别**（本机无端侧 OCR）
- [x] 单测 596 项全过（新增 `particleInput.test.mjs` 63 项、`slotFill.test.mjs` 59 项）
- [x] 真机实测（荣耀 BKQ-AN90）7 项全过：图库选择面板、空槽补录、13 位补前缀、
      空输入不关窗、20 位原样、重复码拦截、批量粘贴填满 6 槽、罐满提示
      证据：`private/测试输出/Android-v1.4.2-手动补录与批量录入-20261002/`
