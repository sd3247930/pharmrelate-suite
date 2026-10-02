# pharmrelate-ocr（离线 OCR，UTS 插件骨架）

图库标签照片 → 文本块（含 bounding box）。**只做识别，不碰业务数据**。

> ⚠️ 本目录是 2026-10-02 交付的**源码骨架**，未在本机编译过（本机没有 DCloud 离线打包 SDK）。
> 编译与真机验证由业务方在 HBuilderX 完成。

## 1. 依赖与限制

| 项 | 值 |
| --- | --- |
| Maven 依赖 | `com.google.mlkit:text-recognition:16.0.1`（bundled 版本，模型随 APK，**不依赖 Google Play 服务**，断网可用） |
| minSdkVersion | 21（与 `manifest.json` 一致，**无需提升**） |
| 不引入 | 中文模型（`text-recognition-chinese`）、`play-services-mlkit-*`（避免体积翻倍） |
| 预期体积增量 | ≈ +4 MB |

## 2. 三处名称必须严格一致（否则真机报「基座不包含原生插件」）

1. 目录名：`uni_modules/pharmrelate-ocr/`
2. 本包 `package.json` 的 `id`：`pharmrelate-ocr`
3. JS 侧引用：`services/ocr.js` 里 `requireNativePlugin('pharmrelate-ocr')` 与
   `import('@/uni_modules/pharmrelate-ocr')`

## 3. 对外接口

```ts
recognizeImage({ imagePath }): Promise<{
  success: boolean
  blocks: [{ text, left, top, right, bottom }]
  rawText: string
  code?: string      // OCR_NO_PATH / OCR_DECODE_FAIL / OCR_FAILED
  message?: string
}>
```

JS 侧调用链（已在 `services/ocr.js` 实现，插件不存在时自动降级）：

```
scan.vue 选图 → services/ocr.recognizeImage(path)
  ├─ nativeplugins 实例可用 → 直接调用
  ├─ UTS 模块可加载      → 直接调用
  └─ 都没有              → { success:false, code:'OCR_PLUGIN_MISSING' } → 页面切手动录入
→ services/particleInput.parseOcrParticleCandidates(blocks)   （纯函数，已单测）
→ 候选列表人工确认 → localBatch.fillParticleCodesIntoEmptySlots()
```

## 4. 打包步骤（业务方执行）

1. HBuilderX 打开工程，确认 `manifest.json` 版本；
2. **发行 → 原生App-自定义调试基座**（或直接云打包正式版）——必须重做基座，标准基座不含本插件；
3. 签名指向 `private\签名证书\pharmrelate-multi-capture.keystore`（别名 `pharmrelate`）；
4. 装到真机后：扫码页 → 粒子相位 → 「🖼 从图库选图辅助录入」→ 选一张标签照片，
   识别成功应出现候选列表；失败/无插件时应看到「无 OCR 插件」，下面是手动录入框。

## 5. 真机 PoC 要测的三项指标

| 指标 | 目标 | 测法 |
| --- | --- | --- |
| 完整识别率 | ≥90% | 用 `private\图片\17~20-条形码*.jpg`，逐张比"识别出的码数 / 实际码数" |
| 错误识别率 | ≤5% | 识别出的码里有多少不在标准答案里（错码比漏码更危险） |
| 单图耗时 | ≤3 秒 | 选图后到候选列表出现的耗时（脚本会记录） |

素材标准答案可用 zxing-cpp 解出（每张图里的真实码串），脚本 `device-ocr-poc.mjs` 会用它算指标。

## 6. 已知风险

1. **同一行被拆成多个 block** → JS 层已按 bounding box 重排（`OCR_ROW_TOLERANCE = 24px`），
   真实照片的行距若比容差大/小，需要按 PoC 结果调这个值；
2. **ML Kit 是自然文本模型**，对"细长纯数字串"可能把相邻标签数字连读或漏读 → PoC 决定是否转 PaddleOCR；
3. 本 UTS 源码未经编译验证，首次编译若报类型/import 问题，按报错微调（ML Kit 的 Kotlin 类名见上）。
