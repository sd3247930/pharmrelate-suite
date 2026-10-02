/**
 * OCR 候选解析单测（阶段 2）。
 *
 * 覆盖：单/多码、多 block、bbox 乱序重排（ML Kit 已知问题）、无关文字、
 *      长度与前缀非法、输入内重复、批次内重复（isUsed 注入）、空数组、
 *      以及"解析 → 批量写入"的部分溢出联调；最后单独验 OCR 桥接的降级路径。
 *
 * 加载方式与其它单测一致：源码读出来按 ESM 从 data: URL 加载。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/ocrCandidates.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
const load = (name) => import(toDataUrl(readFileSync(resolve(here, '..', 'services', name), 'utf8')))
/**
 * 同一个 data: URL 会被 Node 的 ESM 缓存复用（内容一样 URL 就一样），
 * 而 `services/ocr.js` 内部会缓存"插件查没查到"的结果 —— 所以测多个场景时
 * 必须在源码尾部加个唯一标记，让每次都是**全新的模块实例**。
 */
const loadFresh = (name, tag) =>
	import(toDataUrl(readFileSync(resolve(here, '..', 'services', name), 'utf8') + `\n// variant:${tag}`))

const pi = await load('particleInput.js')

let passed = 0
const failures = []

function check(ok, label, extra = '') {
	if (ok) {
		passed += 1
		console.log(`[ OK ] ${label}${extra ? '  ' + extra : ''}`)
	} else {
		failures.push(label)
		console.log(`[FAIL] ${label}${extra ? '  ' + extra : ''}`)
	}
}

function equal(actual, expected, label) {
	check(actual === expected, label, `期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}`)
}

function section(title) {
	console.log(`\n==== ${title} ====`)
}

const PREFIX = '8206233'
const short = (n) => String(n).padStart(13, '0')
const full = (n) => PREFIX + short(n)
/** 造一个带坐标的 OCR block（y 递增 = 从上到下）。 */
const block = (text, top, left = 10) => ({ text, left, top, right: left + 200, bottom: top + 40 })

// ---------------------------------------------------------------------------
section('parseOcrParticleCandidates：基础解析')
// ---------------------------------------------------------------------------

{
	const one = pi.parseOcrParticleCandidates([block(short(1), 100)])
	equal(one.valid.length, 1, '单个 13 位 → 1 条有效')
	equal(one.valid[0].code, full(1), '13 位自动补前缀')
	equal(one.invalid.length, 0, '没有无效项')

	const oneFull = pi.parseOcrParticleCandidates([block(full(2), 100)])
	equal(oneFull.valid.length, 1, '单个 20 位 → 1 条有效')
	equal(oneFull.valid[0].code, full(2), '20 位原样保留')
	equal(oneFull.valid[0].mode, 'full', '标记为 full')

	const multiInBlock = pi.parseOcrParticleCandidates([block(`${short(3)} ${short(4)}`, 100)])
	equal(multiInBlock.valid.length, 2, '一个 block 里两个数字 → 2 条有效')
	equal(multiInBlock.valid[0].code, full(3), '按出现顺序取第 1 条')
	equal(multiInBlock.valid[1].code, full(4), '按出现顺序取第 2 条')

	equal(pi.parseOcrParticleCandidates([]).valid.length, 0, '空数组 → 0 条有效')
	equal(pi.parseOcrParticleCandidates(null).valid.length, 0, 'null 输入不炸')
	equal(pi.parseOcrParticleCandidates([{ text: '' }]).blockCount, 0, '空文本 block 被忽略')
}

// ---------------------------------------------------------------------------
section('parseOcrParticleCandidates：bbox 排序（ML Kit 顺序错乱兜底）')
// ---------------------------------------------------------------------------

{
	// 故意把顺序打乱：先给第 3 行，再第 1 行，再第 2 行
	const shuffled = pi.parseOcrParticleCandidates([
		block(short(3), 300),
		block(short(1), 100),
		block(short(2), 200)
	])
	equal(shuffled.valid.map((item) => item.code).join(','), `${full(1)},${full(2)},${full(3)}`, '按 top 从上到下重排')

	// 同一行被拆成多个 block：left 决定先后
	const sameRow = pi.parseOcrParticleCandidates([
		block(short(2), 100, 500),
		block(short(1), 104, 100)
	])
	equal(sameRow.valid.map((item) => item.code).join(','), `${full(1)},${full(2)}`, '同一行内按 left 从左到右重排')

	// 不同行但 top 差小于容差 → 视为同一行（容差内按 left）
	const tinyGap = pi.parseOcrParticleCandidates([
		block(short(2), 110, 400),
		block(short(1), 100, 100)
	])
	equal(tinyGap.valid.map((item) => item.code).join(','), `${full(1)},${full(2)}`, 'top 差在容差内按同一行处理')

	// 没有坐标 → 保持原顺序，不瞎排
	const noBox = pi.parseOcrParticleCandidates([{ text: short(9) }, { text: short(8) }])
	equal(noBox.valid.map((item) => item.code).join(','), `${full(9)},${full(8)}`, '缺坐标时保持原顺序')
}

// ---------------------------------------------------------------------------
section('parseOcrParticleCandidates：无关文字与非法项')
// ---------------------------------------------------------------------------

{
	const noisy = pi.parseOcrParticleCandidates([
		block('药品追溯码', 50),
		block(short(5), 100),
		block('Code 128', 150),
		block('批次 A-2026', 200)
	])
	equal(noisy.valid.length, 1, '无关文字里只挑出 1 个有效码')
	equal(noisy.valid[0].code, full(5), '有效码正确')
	// '128' 与 '2026' 是数字但长度不对 → 记进 invalid（不静默丢）
	equal(noisy.invalid.length, 2, '长度不对的数字记进 invalid', JSON.stringify(noisy.invalid.map((i) => i.input)))

	const lengths = pi.parseOcrParticleCandidates([
		block('8'.repeat(12), 10),
		block('8'.repeat(14), 20),
		block('8'.repeat(19), 30)
	])
	equal(lengths.invalid.length, 3, '12 / 14 / 19 位都判无效')
	check(lengths.invalid.every((item) => item.reason === 'INVALID_LENGTH'), '原因都是 INVALID_LENGTH')

	const wrongPrefix = pi.parseOcrParticleCandidates([block('8021761' + short(6), 10)])
	equal(wrongPrefix.valid.length, 0, '错误前缀不通过')
	equal(wrongPrefix.invalid[0].reason, 'WRONG_PREFIX', '原因 = WRONG_PREFIX')
	equal(wrongPrefix.duplicateInCurrentBatch.length, 0, '错误前缀不会进"批次内重复"')
}

// ---------------------------------------------------------------------------
section('parseOcrParticleCandidates：两层去重')
// ---------------------------------------------------------------------------

{
	const dupInput = pi.parseOcrParticleCandidates([block(short(7), 10), block(short(7), 60)])
	equal(dupInput.valid.length, 1, '同一枚码出现两次 → 有效 1 条')
	equal(dupInput.duplicateInInput.length, 1, '第二次记为"本次重复"')
	equal(dupInput.duplicateInInput[0].code, full(7), '重复项指向标准化码')

	// 跨罐/批次内重复：交给注入的 isUsed（页面传 findUsage）
	const used = { [full(8)]: { where: '箱 1 罐 2 / 槽位 3' } }
	const dupBatch = pi.parseOcrParticleCandidates([block(short(8), 10), block(short(9), 60)], {
		isUsed: (code) => used[code] || null
	})
	equal(dupBatch.valid.length, 1, '批次内已存在的码不进 valid')
	equal(dupBatch.valid[0].code, full(9), '剩下的有效码正确')
	equal(dupBatch.duplicateInCurrentBatch.length, 1, '记进"批次内重复"')
	equal(dupBatch.duplicateInCurrentBatch[0].where, '箱 1 罐 2 / 槽位 3', '带上它在哪里的位置信息')

	// 输入内重复优先于"批次内重复"（同一枚码第二次出现只报一次）
	const both = pi.parseOcrParticleCandidates([block(short(8), 10), block(short(8), 60)], {
		isUsed: (code) => used[code] || null
	})
	equal(both.duplicateInCurrentBatch.length, 1, '第一次出现命中批次内重复')
	equal(both.duplicateInInput.length, 1, '第二次出现另外记一条"本次重复"（两个原因都摆给操作员看）')
	equal(both.valid.length, 0, '这枚码不会进入 valid')
}

// ---------------------------------------------------------------------------
section('解析 → 批量写入联调（溢出由写入层处理）')
// ---------------------------------------------------------------------------

{
	const lb = await load('localBatch.js')
	const storage = {
		get: () => '',
		set: () => {},
		remove: () => {}
	}
	lb.setStorageAdapter(storage)

	const created = lb.createDraft({
		batchNo: 'T-OCR',
		produceDate: '2026-10-02',
		expireDate: '2026-12-01',
		deviceId: 'and-test'
	})
	let batch = lb.saveStructure(created, [[6]]).batch
	batch = lb.applyCodes(batch, ['8021761' + short(1)]).batch
	batch = lb.applyCodes(batch, ['8021762' + short(1)]).batch

	// 一页 8 个码，但只有 6 个空槽
	const blocks = [11, 12, 13, 14, 15, 16, 17, 18].map((n, index) => block(short(n), index * 50))
	const parsed = pi.parseOcrParticleCandidates(blocks)
	equal(parsed.valid.length, 8, 'OCR 解析出 8 个有效码')

	const written = lb.fillParticleCodesIntoEmptySlots(batch, parsed.valid.map((item) => item.code))
	equal(written.result.written.length, 6, '只有 6 个空槽 → 写入 6 枚')
	equal(written.result.overflow.length, 2, '其余 2 枚进"未写入"')
	equal(written.result.overflow[0], full(17), '未写入的是第 7 个')
	check(written.event.message.includes('未写入'), '事件文案明确写出未写入', written.event.message)
}

// ---------------------------------------------------------------------------
section('免插件条码解码 → 候选（barcodeResultsToBlocks + parse）')
// ---------------------------------------------------------------------------

{
	// zxing-wasm 返回的是 position 四角，适配层把它折算成 bbox
	const blocks = pi.barcodeResultsToBlocks([
		{ text: full(3), left: 300, top: 500, right: 700, bottom: 560 },
		{ text: full(1), left: 100, top: 100, right: 500, bottom: 160 },
		{ text: '', left: 0, top: 0, right: 0, bottom: 0 },
		{ text: full(2), left: 200, top: 300, right: 600, bottom: 360 },
		{ text: full(4) } // 没有坐标
	])
	equal(blocks.length, 4, '空文本被过滤，其余 4 条保留')
	equal(blocks[0].left, 300, '坐标按原样带过来')
	check(!Number.isFinite(blocks[3].left), '缺坐标的保持缺失（不补 0，避免被当成左上角）')

	const parsed = pi.parseOcrParticleCandidates(blocks)
	equal(parsed.valid.length, 4, '4 个条码全部有效')
	equal(
		parsed.valid.map((item) => item.code).join(','),
		[full(1), full(2), full(3), full(4)].join(','),
		'有坐标的按 top 从上到下重排，缺坐标的排在最后'
	)
	equal(
		parsed.valid.map((item) => item.code).slice(0, 3).join(','),
		`${full(1)},${full(2)},${full(3)}`,
		'前三枚顺序正确（解码顺序本来就是乱的）'
	)

	// 条码里混进别的前缀（例如箱码）→ 进 invalid，不写入
	const mixed = pi.parseOcrParticleCandidates(pi.barcodeResultsToBlocks([
		{ text: '8021761' + short(1), left: 10, top: 10 },
		{ text: short(5), left: 10, top: 100 }
	]))
	equal(mixed.valid.length, 1, '箱码不会被当成粒子码')
	equal(mixed.invalid.length, 1, '箱码记入 invalid')

	// 解码结果里同一枚码重复（同一标签被读两次）
	const dup = pi.parseOcrParticleCandidates(pi.barcodeResultsToBlocks([
		{ text: full(6), left: 10, top: 10 },
		{ text: full(6), left: 10, top: 90 }
	]))
	equal(dup.valid.length, 1, '同码只留一条')
	equal(dup.duplicateInInput.length, 1, '另一条记为"本次重复"')
}

// ---------------------------------------------------------------------------
section('R5 相邻数字块拼接（ML Kit 把一串数字拆成多块）')
// ---------------------------------------------------------------------------

{
	// 典型形态：20 位被拆成 "8206233" + 13 位
	const split = [
		{ text: '8206233', left: 100, top: 100, right: 300, bottom: 140 },
		{ text: short(1234567890123).slice(0, 13), left: 310, top: 102, right: 700, bottom: 142 }
	]
	const merged = pi.mergeAdjacentDigitBlocks(split)
	equal(merged.merged.length, 1, '同一行、X 相邻、合并后正好 20 位 → 合并成功')
	equal(merged.merged[0].text, `${'8206233'}${short(1234567890123).slice(0, 13)}`, '合并结果 = 两段直接相接')
	equal(merged.merged[0].mergedFrom.length, 2, '保留 mergedFrom 便于追溯')
	equal(merged.consumedIndexes.length, 2, '两个碎片都标记为已消费')

	// 合并后不是一个合法长度 → 不合并（禁止硬凑）
	const badLength = pi.mergeAdjacentDigitBlocks([
		{ text: '82062', left: 100, top: 100, right: 200, bottom: 140 },
		{ text: '33', left: 205, top: 100, right: 260, bottom: 140 }
	])
	equal(badLength.merged.length, 0, '合并后只有 7 位 → 不合并（不猜、不补）')

	// 不同行 → 不合并
	const otherRow = pi.mergeAdjacentDigitBlocks([
		{ text: '8206233', left: 100, top: 100, right: 300, bottom: 140 },
		{ text: short(1234567890123).slice(0, 13), left: 310, top: 400, right: 700, bottom: 440 }
	])
	equal(otherRow.merged.length, 0, '不在同一行 → 不合并')

	// X 离得太远 → 不合并
	const farApart = pi.mergeAdjacentDigitBlocks([
		{ text: '8206233', left: 100, top: 100, right: 300, bottom: 140 },
		{ text: short(1234567890123).slice(0, 13), left: 900, top: 100, right: 1300, bottom: 140 }
	])
	equal(farApart.merged.length, 0, '水平间隙过大 → 不合并')

	// 通过 parse 入口验证：碎片不再出现在 invalid 里，而是变成一条有效码
	const parsed = pi.parseOcrParticleCandidates(split)
	equal(parsed.valid.length, 1, '走 parse：拼回来的码进入 valid')
	equal(parsed.valid[0].code, `${'8206233'}${short(1234567890123).slice(0, 13)}`, '标准化结果正确')
	equal(parsed.valid[0].mergedFrom.length, 2, 'valid 项带 mergedFrom 追溯')
	equal(parsed.invalid.length, 0, '被吃掉的碎片不再算无效（UI 更干净）')
	equal(parsed.mergedCount, 1, '统计里能看出发生了一次拼接')
}

// ---------------------------------------------------------------------------
section('OCR 桥接的降级路径（services/ocr.js）')
// ---------------------------------------------------------------------------

{
	// 场景 1：基座里没有插件（当前标准基座就是这样）
	delete globalThis.uni
	const ocrNoPlugin = await loadFresh('ocr.js', 'no-plugin')
	const missing = await ocrNoPlugin.recognizeImage('/storage/emulated/0/a.jpg')
	equal(missing.success, false, '没有插件 → success=false')
	equal(missing.code, 'OCR_PLUGIN_MISSING', '错误码 = OCR_PLUGIN_MISSING（页面据此降级手输）')
	check(missing.message.includes('手动录入'), '提示里告诉操作员可以手动录入', missing.message)
	equal(ocrNoPlugin.isOcrAvailable(), false, 'isOcrAvailable() = false')

	const noPath = await ocrNoPlugin.recognizeImage('')
	equal(noPath.code, 'OCR_NO_IMAGE', '空路径 → OCR_NO_IMAGE')

	// 场景 2：插件存在且成功返回
	const fakeOk = {
		recognizeImage: (options, callback) => {
			callback({ success: true, blocks: [{ text: short(1), left: 1, top: 2, right: 3, bottom: 4 }], rawText: short(1) })
		}
	}
	globalThis.uni = { requireNativePlugin: (name) => (name === 'pharmrelate-ocr' ? fakeOk : null) }
	const ocrWithPlugin = await loadFresh('ocr.js', 'with-plugin')
	equal(ocrWithPlugin.isOcrAvailable(), true, '有插件时 isOcrAvailable() = true')
	const ok = await ocrWithPlugin.recognizeImage('/storage/emulated/0/a.jpg')
	equal(ok.success, true, '插件回调成功 → success=true')
	equal(ok.blocks.length, 1, 'blocks 透传')
	equal(ok.rawText, short(1), 'rawText 透传')

	// 场景 3：插件抛错 → 归一化成失败结构，不往外抛
	globalThis.uni = {
		requireNativePlugin: () => ({
			recognizeImage: () => {
				throw new Error('boom')
			}
		})
	}
	const ocrThrows = await loadFresh('ocr.js', 'plugin-throws')
	const failed = await ocrThrows.recognizeImage('/storage/emulated/0/a.jpg')
	equal(failed.success, false, '插件抛错 → success=false（不炸页面）')
	equal(failed.code, 'OCR_CALL_FAILED', '错误码 = OCR_CALL_FAILED')

	delete globalThis.uni
}

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`OCR 候选解析单测全部通过（${passed} 项）。`)
process.exit(0)
