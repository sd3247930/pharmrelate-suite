/**
 * 图库识别「服务层支撑」单测（R4 ROI 纯函数 + base64 工具 + 常量）。
 *
 * 解码本体在 renderjs 视图层（浏览器环境），本机无法单测；
 * 但"条码框 → 数字 ROI"的算法、base64 解码、超时/尺寸常量都是纯逻辑，必须锁住。
 *
 * 运行：node tests/imageDecoder.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
const svc = await import(
	toDataUrl(readFileSync(resolve(here, '..', 'services', 'imageCodeDecoder.js'), 'utf8'))
)

let passed = 0
const failures = []
const check = (ok, label, extra = '') => {
	if (ok) {
		passed += 1
		console.log(`[ OK ] ${label}${extra ? '  ' + extra : ''}`)
	} else {
		failures.push(label)
		console.log(`[FAIL] ${label}${extra ? '  ' + extra : ''}`)
	}
}
const equal = (actual, expected, label) =>
	check(actual === expected, label, `期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`)
const section = (title) => console.log(`\n==== ${title} ====`)

// ---------------------------------------------------------------------------
section('常量：超时与工作图尺寸')
// ---------------------------------------------------------------------------

equal(svc.DECODER_TIMEOUT_MS, 12000, '硬超时 = 12 秒（不允许卡界面）')
equal(svc.DECODER_SOFT_TIMEOUT_MS, 5000, '软超时 = 5 秒（允许提前确认）')
equal(svc.IMAGE_CODE_DECODER_ENABLED, true, 'renderjs 解码链路已启用（真机验收通过）')
check(svc.DECODER_MAX_SIDE >= 3072, '工作图上限 ≥3072：不牺牲识别率', String(svc.DECODER_MAX_SIDE))
equal(svc.DECODER_WASM_URL, '_www/static/zxing/zxing_reader.wasm', 'wasm 从应用内置资源读，不走网络')

// ---------------------------------------------------------------------------
section('R4：条码框 → 下方数字 ROI')
// ---------------------------------------------------------------------------

{
	const roi = svc.buildDigitRoi({ left: 100, top: 200, right: 500, bottom: 260 })
	equal(roi.left, 68, '左右各按宽度的 8% 外扩（margin = 400×0.08 = 32）')
	equal(roi.right, 532, '右侧同样外扩')
	equal(roi.top, 260, 'ROI 从条码下沿开始（数字印在条码下方）')
	equal(roi.bottom, 302, '向下扩展条码高度的 70%（60×0.7 = 42）')

	const tight = svc.buildDigitRoi({ left: 100, top: 200, right: 500, bottom: 260 }, { marginRatio: 0, heightRatio: 1 })
	equal(tight.left, 100, 'marginRatio=0 时不外扩')
	equal(tight.bottom, 320, 'heightRatio=1 时向下扩展一个条码高度')

	const clamped = svc.buildDigitRoi(
		{ left: 10, top: 10, right: 100, bottom: 40 },
		{ imageWidth: 120, imageHeight: 80, marginRatio: 0.5, heightRatio: 2 }
	)
	equal(clamped.left, 0, '左边越界 → 夹到 0')
	equal(clamped.right, 120, '右边越界 → 夹到图片宽度')
	equal(clamped.bottom, 80, '下边越界 → 夹到图片高度')

	equal(svc.buildDigitRoi(null), null, '没有条码框 → null（调用方据此退回整图识别）')
	equal(svc.buildDigitRoi({ left: 1, top: 1, right: 1, bottom: 1 }), null, '零面积框 → null')
	equal(svc.buildDigitRoi({ left: 'a', top: 1, right: 2, bottom: 3 }), null, '非数字坐标 → null')
}

// ---------------------------------------------------------------------------
section('base64 工具（服务层读 wasm / 图片用）')
// ---------------------------------------------------------------------------

{
	equal(Buffer.from(svc.base64ToBytes('YWJj')).toString(), 'abc', '普通 base64 解码正确')
	equal(Array.from(svc.base64ToBytes('QQ==')).join(','), '65', '带 padding 的单字节正确')
	equal(svc.base64ToBytes('data:application/octet-stream;base64,YWJj').length, 3, 'data URL 前缀被剥掉')

	const wasm = readFileSync(resolve(here, '..', 'static', 'zxing', 'zxing_reader.wasm'))
	const decoded = svc.base64ToBytes(wasm.toString('base64'))
	equal(decoded.length, wasm.length, `wasm 解码字节数一致（${wasm.length}）`)
	check(Buffer.compare(Buffer.from(decoded), wasm) === 0, 'wasm 解码内容与文件逐字节一致')
}

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`图库识别服务层支撑单测全部通过（${passed} 项）。`)
process.exit(0)
