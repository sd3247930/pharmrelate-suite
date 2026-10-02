/**
 * OCR 候选行构造 / 删除过滤单测（删除功能修复）。
 *
 * 覆盖（对齐任务文档「阶段 1」）：
 *   1. 基础摊平：四类结果 → 列表行，index 连续、key 稳定
 *   2. 删除 1 条 → 行还在（保留口径）但可填数 -1
 *   3. 删除重复项 / 无效项 → 不影响可填数
 *   4. 删光有效码 → 可填数组为空（按钮 disabled 的判据）
 *   5. 同行连删两次 → 结果一致（幂等）
 *   6. 清空复位（deletedMap 置空）→ 可填数恢复
 *   7. 行 key 不串行：同一枚码"删了再识别"仍能正确判断
 *
 * 加载方式与其它单测一致：源码读出来按 ESM 从 data: URL 加载。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/ocrCandidateRows.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
const load = (name) => import(toDataUrl(readFileSync(resolve(here, '..', 'services', name), 'utf8')))

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
const block = (text, top, left = 10) => ({ text, left, top, right: left + 200, bottom: top + 40 })

/** 造一份"有有效 + 重复 + 无效"的解析结果（模拟真机 9 码那张图的形状）。 */
const buildParsed = () => {
	const codes = [1, 2, 3, 4, 5, 6]
	const blocks = codes.map((n, i) => block(short(n), 100 + i * 60))
	// 第 7 个块与第 1 个块同码 → 本次重复；再塞两个非法输入
	blocks.push(block(short(1), 500))
	blocks.push(block('123', 560))
	// 注意：纯字母块不含数字，parseOcrParticleCandidates 直接跳过（不算无效项），
	// 所以这里用"含数字但前缀不对"的输入来造无效项
	blocks.push(block('55555555555555555555', 620))
	return pi.parseOcrParticleCandidates(blocks)
}

const rowOf = (rows, code) => rows.find((r) => r.code === code)

// ---------------------------------------------------------------------------
section('任务 1：buildOcrCandidateRows 基础摊平')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	equal(parsed.valid.length, 6, '解析出 6 条有效')
	equal(parsed.duplicateInInput.length, 1, '解析出 1 条本次重复')
	equal(parsed.invalid.length, 2, '解析出 2 条无效（123 / ABCDEFG）')

	const rows = pi.buildOcrCandidateRows(parsed, {})
	equal(rows.length, 9, '四类一起摊平成 9 行')
	equal(rows[0].kind, 'valid', '前 6 行是有效')
	equal(rows[6].kind, 'dup-input', '第 7 行是本次重复')
	equal(rows[7].kind, 'invalid', '第 8 行是无效')
	equal(rows[8].kind, 'invalid', '第 9 行是无效')
	equal(rows.map((r) => r.index).join(','), '1,2,3,4,5,6,7,8,9', 'index 从 1 连续')
	equal(rows[0].deleted, false, '默认未删除')
	equal(rows[0].status, '有效', '默认状态是「有效」')
	equal(rows[0].badge, 'badge-ok', '默认徽标是绿色')

	// 空输入 / 空解析结果不能炸
	equal(pi.buildOcrCandidateRows(null, {}).length, 0, '解析结果为 null → 0 行')
	equal(pi.buildOcrCandidateRows(parsed, null).length, 9, 'deletedMap 为 null 按未删除处理')
}

// ---------------------------------------------------------------------------
section('任务 2：删除 1 条 → 行保留但可填数 -1')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const rows = pi.buildOcrCandidateRows(parsed, {})
	equal(pi.selectFillableOcrCodes(rows).length, 6, '删除前可填 6 枚')

	const target = rowOf(rows, full(1))
	const deleted = { [target.key]: true }
	const rows2 = pi.buildOcrCandidateRows(parsed, deleted)

	equal(pi.selectFillableOcrCodes(rows2).length, 5, '删 1 条 → 可填数 -1（6→5）')
	equal(rows2.length, 9, '保留口径：行数不变（仍 9 行，可追溯）')
	const after = rowOf(rows2, full(1))
	equal(after.deleted, true, '被删的行 deleted=true')
	equal(after.status, pi.OCR_ROW_DELETED_STATUS, '被删的行状态是「已删除」')
	equal(after.status, '已删除', '状态文案就是「已删除」')
	equal(after.badge, pi.OCR_ROW_DELETED_BADGE, '被删的行徽标换成 badge-deleted（灰色）')
	equal(after.badge, 'badge-deleted', '徽标名就是 badge-deleted')
	equal(after.index, 1, '序号保持原位（不重排，便于对照截图）')
	check(!pi.selectFillableOcrCodes(rows2).includes(full(1)), '被删的码不在可填列表里')
	check(pi.selectFillableOcrCodes(rows2).includes(full(2)), '其它有效码不受影响')
}

// ---------------------------------------------------------------------------
section('任务 3：删除重复项 / 无效项 → 不影响可填数')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const base = pi.buildOcrCandidateRows(parsed, {})
	const baseFillable = pi.selectFillableOcrCodes(base).length

	const rows = pi.buildOcrCandidateRows(parsed, {})
	const dupRow = rows.find((r) => r.kind === 'dup-input')
	const invRow = rows.find((r) => r.kind === 'invalid')
	const deleted = { [dupRow.key]: true, [invRow.key]: true }
	const rows2 = pi.buildOcrCandidateRows(parsed, deleted)

	equal(pi.selectFillableOcrCodes(rows2).length, baseFillable, '删重复/无效项不改可填数')
	// 注意：dupRow.code 与某条有效码相同，必须按 key 定位（不能按 code 找，会命中有效那一行）
	equal(rows2.find((r) => r.key === dupRow.key).status, '已删除', '重复行也能标记已删除')
	equal(rowOf(rows2, dupRow.code).status, '有效', '同码的有效行不受重复行删除影响')
	equal(rows2.find((r) => r.key === invRow.key).deleted, true, '无效行也能标记已删除')
}

// ---------------------------------------------------------------------------
section('任务 4：删光有效码 → 可填数组为空（按钮 disabled）')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const rows = pi.buildOcrCandidateRows(parsed, {})
	const deleted = {}
	rows.filter((r) => r.kind === 'valid').forEach((r) => {
		deleted[r.key] = true
	})
	const rows2 = pi.buildOcrCandidateRows(parsed, deleted)

	equal(pi.selectFillableOcrCodes(rows2).length, 0, '删光有效码 → 可填 0 枚')
	equal(rows2.length, 9, '行还在（灰色 9 行）')
	equal(rows2.filter((r) => r.deleted).length, 6, '6 行标记为已删除')

	// 与页面上的判据一致：!ocrFillableCodes.length → 按钮 disabled
	check(!pi.selectFillableOcrCodes(rows2).length, '按钮 disabled 的判据成立')
	equal(pi.selectFillableOcrCodes([]).length, 0, '空列表也返回空数组（不抛错）')
	equal(pi.selectFillableOcrCodes(null).length, 0, 'null 入参返回空数组（不抛错）')
}

// ---------------------------------------------------------------------------
section('幂等：同行连删两次结果一致')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const rows0 = pi.buildOcrCandidateRows(parsed, {})
	const target = rowOf(rows0, full(3))

	// 页面里 removeOcrCandidate 的写法：已删除直接 return，否则不可变替换
	const removeOnce = (map, row) => {
		if (!row || !row.key) return map
		if (map[row.key]) return map
		return Object.assign({}, map, { [row.key]: true })
	}
	const once = removeOnce({}, target)
	const twice = removeOnce(once, target)
	check(once === twice, '第二次点击直接返回同一个引用（不重复触发）')

	const rowsOnce = pi.buildOcrCandidateRows(parsed, once)
	const rowsTwice = pi.buildOcrCandidateRows(parsed, twice)
	equal(
		JSON.stringify(pi.selectFillableOcrCodes(rowsOnce)),
		JSON.stringify(pi.selectFillableOcrCodes(rowsTwice)),
		'连删两次的可填列表完全一致'
	)
	equal(pi.selectFillableOcrCodes(rowsTwice).length, 5, '仍然只少 1 枚（不会多减）')
}

// ---------------------------------------------------------------------------
section('清空复位：可填数恢复')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const rows = pi.buildOcrCandidateRows(parsed, {})
	const deleted = {}
	rows.slice(0, 3).forEach((r) => {
		deleted[r.key] = true
	})
	equal(pi.selectFillableOcrCodes(pi.buildOcrCandidateRows(parsed, deleted)).length, 3, '删 3 条 → 可填 3 枚')

	// clearOcrCandidates() 会把 ocrDeleted 重置成 {}
	const rowsReset = pi.buildOcrCandidateRows(parsed, {})
	equal(pi.selectFillableOcrCodes(rowsReset).length, 6, '复位后可填数回到 6（对应「重新识别 / 清空」）')
	equal(rowsReset.filter((r) => r.deleted).length, 0, '复位后没有已删除标记')
}

// ---------------------------------------------------------------------------
section('key 不串行：同一枚码删了再识别仍能判断')
// ---------------------------------------------------------------------------

{
	const parsed = buildParsed()
	const rows = pi.buildOcrCandidateRows(parsed, {})
	const key = rowOf(rows, full(1)).key
	equal(key, `v-${full(1)}`, '有效行的 key 形如 v-<码>')
	equal(rowOf(rows, full(1)).key, key, '同一枚码每次构造的 key 都一样（不依赖随机/时间）')

	// 误删后重新识别：传新的 parsed 但 deletedMap 还留着旧的 key
	const parsed2 = pi.parseOcrParticleCandidates([block(short(9), 100)])
	const rowsNew = pi.buildOcrCandidateRows(parsed2, { [key]: true })
	equal(rowsNew.length, 1, '新一批候选只有 1 行')
	equal(rowsNew[0].deleted, false, '新码没有被旧的删除记录误伤（key 按码绑定）')
	equal(pi.selectFillableOcrCodes(rowsNew).length, 1, '新码可填')
}

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`OCR 候选行构造 / 删除过滤单测全部通过（${passed} 项）。`)
process.exit(0)
