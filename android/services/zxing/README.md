# 内联的条码解码引擎（zxing-wasm）

| 项 | 值 |
| --- | --- |
| 来源 | npm `zxing-wasm@3.1.4`（`dist/es/reader/index.js`、`dist/es/share.js`、`dist/reader/zxing_reader.wasm`） |
| 许可 | MIT（上游 LICENSE 随 npm 包分发；本项目只内联 reader 部分） |
| wasm 大小 | 931 KB（SHA-256 `e8af31edb56d0522f4de74495839385ef019ba8bc90d38e5ecb2f18795d86fb2`） |
| 改动 | 仅一处：`reader.js` 里的 `from "../share.js"` 改为 `from "./share.js"`（内联后目录层级不同） |

## 为什么内联而不是装 npm 依赖

本工程是 HBuilderX 工程（没有 `package.json` / `node_modules`），
而图库识别必须在**标准基座**上也能跑（自定义基座要云打包，业务方明确不用）。
内联这两个 JS + 一个 wasm 后：

1. 不需要任何原生插件、不需要自定义基座；
2. wasm 用 `plus.io` 读成 base64 → `ArrayBuffer` → 注入 `wasmBinary`，
   **全程不 fetch**（WebView 里 `fetch('file://...')` 是被禁的）；
3. 只解码一维码（本项目粒子码是 Code 128），比 ML Kit OCR 读印刷数字更准（条码自带校验位）。

## 与 ML Kit OCR 的关系

两条引擎并存，页面按顺序尝试，谁先出结果就用谁：

```
选图 → ① zxing-wasm 条码解码（无插件依赖，任何基座可用）
      → ② ML Kit OCR（仅自定义基座具备；读印刷数字，作为兜底）
      → ③ 多行手动录入（永远可用）
```

三者最终都汇入同一条候选列表 → 人工确认 → `fillParticleCodesIntoEmptySlots()`。
