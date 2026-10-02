/**
 * 槽位补录 / 批量录入单测（阶段 A + B 的数据层部分）。
 *
 * 覆盖：
 *   - `fillSlot()`：往**空槽位**补录、同码幂等、全批去重、错前缀、越界、撤销；
 *   - `fillParticleCodesIntoEmptySlots()`：批量子集写入、**部分溢出不再整帧拒绝**、
 *     输入内重复 / 与罐内重复 / 非法码分类、顺序保持、计划粒子数不变、整批一次撤销。
 *
 * 加载方式与其它单测一致：源码读出来按 ESM 从 data: URL 加载。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/slotFill.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
const lb = await import(toDataUrl(readFileSync(resolve(here, '..', 'services', 'localBatch.js'), 'utf8')))

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

// ---------------------------------------------------------------------------
// 内存存储 + 造批次（与 localBatch.test.mjs 同一套写法）
// ---------------------------------------------------------------------------

function memoryAdapter() {
	const map = new Map()
	return {
		get: (key) => (map.has(key) ? JSON.parse(JSON.stringify(map.get(key))) : ''),
		set: (key, value) => map.set(key, JSON.parse(JSON.stringify(value))),
		remove: (key) => map.delete(key)
	}
}

lb.setStorageAdapter(memoryAdapter())

const boxCode = (n) => '8021761' + String(n).padStart(13, '0')
const canCode = (n) => '8021762' + String(n).padStart(13, '0')
const particle = (n) => '8206233' + String(n).padStart(13, '0')

const BOX1 = boxCode(1)
const CAN1 = canCode(1)
const P = particle

/** 造一个已经推进到「粒子相位」的批次（1 箱 1 罐 N 粒）。 */
function atParticlePhase(plannedParticles = 3) {
	const created = lb.createDraft({
		batchNo: 'T-SLOTFILL',
		produceDate: '2026-10-02',
		expireDate: '2026-12-01',
		deviceId: 'and-test-device'
	})
	let batch = lb.saveStructure(created, [[plannedParticles]]).batch
	batch = lb.applyCodes(batch, [BOX1]).batch
	batch = lb.applyCodes(batch, [CAN1]).batch
	return batch
}

const can0 = (batch) => batch.boxes[0].cans[0]
const slots = (batch) => can0(batch).particles
const filled = (batch) => slots(batch).filter((code) => !!code).length

// ---------------------------------------------------------------------------
section('fillSlot：往空槽位补录')
// ---------------------------------------------------------------------------

{
	let batch = atParticlePhase(3)
	equal(lb.deriveWizard(batch).phase, 'particle', '前置：已进入粒子相位')
	equal(filled(batch), 0, '前置：一个槽位都没填')

	const result = lb.fillSlot(batch, 0, 0, 0, P(5001))
	equal(result.event.code, lb.EVENT.OK, '空槽位补录 → 成功')
	batch = result.batch
	equal(slots(batch)[0], P(5001), '码写进了指定的 0 号槽位')
	equal(filled(batch), 1, '进度 +1')
	check(result.event.message.includes('补录'), '成功文案说的是“补录”', result.event.message)

	const undone = lb.undo(batch)
	batch = undone.batch
	equal(slots(batch)[0], '', '撤销后该槽位回到空')
	equal(filled(batch), 0, '撤销后进度回 0')
}

// ---------------------------------------------------------------------------
section('fillSlot：幂等、去重、非法与越界')
// ---------------------------------------------------------------------------

{
	let batch = lb.fillSlot(atParticlePhase(3), 0, 0, 0, P(5002)).batch

	const same = lb.fillSlot(batch, 0, 0, 0, P(5002))
	equal(same.event.code, lb.EVENT.OK, '同一槽位填同一枚码 → 幂等通过')
	check(same.event.message.includes('无需重复补录'), '给出“无需重复补录”提示', same.event.message)
	equal(same.batch, batch, '幂等时不产生新批次对象')

	const elsewhere = lb.fillSlot(batch, 0, 0, 2, P(5002))
	equal(elsewhere.event.code, lb.EVENT.DUPLICATE_CODE, '该码已在 0 号槽 → 判重复')
	check(elsewhere.event.message.includes('已被使用'), '重复提示说明用在哪里', elsewhere.event.message)
	equal(slots(elsewhere.batch)[2], '', '重复时不写入目标槽位')

	const wrongPrefix = lb.fillSlot(batch, 0, 0, 1, '8021761' + '0000000000001')
	equal(wrongPrefix.event.code, lb.EVENT.WRONG_LAYER, '错前缀 → 判层级/格式错误')
	equal(slots(wrongPrefix.batch)[1], '', '错前缀不写入')

	const tooShort = lb.fillSlot(batch, 0, 0, 1, '8206233000')
	equal(tooShort.event.code, lb.EVENT.WRONG_LAYER, '长度不对 → 拒绝')

	const outOfRange = lb.fillSlot(batch, 0, 0, 9, P(5003))
	equal(outOfRange.event.code, lb.EVENT.WRONG_STATE, '槽位越界 → WRONG_STATE')

	const noCan = lb.fillSlot(batch, 0, 5, 0, P(5004))
	equal(noCan.event.code, lb.EVENT.WRONG_STATE, '罐不存在 → WRONG_STATE')

	// 已填槽位也能通过 fillSlot 改写（弹窗对已填槽走 replaceSlot，这里只锁定行为一致）
	const overwrite = lb.fillSlot(batch, 0, 0, 0, P(5005))
	equal(overwrite.event.code, lb.EVENT.OK, 'fillSlot 改写已填槽位 → 成功')
	equal(slots(overwrite.batch)[0], P(5005), '槽位内容被替换')
	const undone = lb.undo(overwrite.batch)
	equal(slots(undone.batch)[0], P(5002), '撤销把这枚改回原来那枚')
}

// ---------------------------------------------------------------------------
section('fillParticleCodesIntoEmptySlots：批量子集写入')
// ---------------------------------------------------------------------------

{
	let batch = atParticlePhase(3)
	const result = lb.fillParticleCodesIntoEmptySlots(batch, [P(6001), P(6002)])
	equal(result.event.code, lb.EVENT.OK, '2 枚码写进 3 个槽位 → 成功')
	batch = result.batch
	equal(result.result.written.length, 2, '写入 2 枚')
	equal(result.result.overflow.length, 0, '没有溢出')
	equal(result.result.remaining, 3, '写入前剩余 3 个空槽')
	equal(filled(batch), 2, '进度 = 2')
	equal(slots(batch)[0], P(6001), '顺序写入：第 1 枚进 0 号槽')
	equal(slots(batch)[1], P(6002), '顺序写入：第 2 枚进 1 号槽')
	equal(slots(batch)[2], '', '第 3 个槽仍是空的')
	equal(can0(batch).plannedParticleCount, 3, '计划粒子数不变（不会被批量录入撑大）')

	const undone = lb.undo(batch)
	equal(filled(undone.batch), 0, '一次撤销把整批 2 枚一起回退')
}

// ---------------------------------------------------------------------------
section('fillParticleCodesIntoEmptySlots：部分溢出（不再整帧拒绝）')
// ---------------------------------------------------------------------------

{
	let batch = lb.fillParticleCodesIntoEmptySlots(atParticlePhase(3), [P(7001)]).batch
	equal(filled(batch), 1, '前置：先占掉 1 个槽')

	const result = lb.fillParticleCodesIntoEmptySlots(batch, [P(7002), P(7003), P(7004), P(7005)])
	equal(result.event.code, lb.EVENT.OK, '4 枚码填 2 个空槽 → 仍然成功（不整帧拒绝）')
	equal(result.result.written.length, 2, '前 2 枚写入')
	equal(result.result.written.join(','), `${P(7002)},${P(7003)}`, '按输入顺序填前 2 枚')
	equal(result.result.overflow.length, 2, '剩下 2 枚列为未写入')
	equal(result.result.overflow.join(','), `${P(7004)},${P(7005)}`, '未写入的是后 2 枚（顺序不变）')
	check(result.event.message.includes('未写入'), '文案明确写出“未写入”', result.event.message)
	batch = result.batch
	equal(filled(batch), 3, '最终进度 = 3（罐满）')
	equal(slots(batch).filter((code) => code === P(7004)).length, 0, '未写入的码确实没有进库')
}

// ---------------------------------------------------------------------------
section('fillParticleCodesIntoEmptySlots：重复与非法分类')
// ---------------------------------------------------------------------------

{
	let batch = lb.fillParticleCodesIntoEmptySlots(atParticlePhase(5), [P(8001)]).batch

	const result = lb.fillParticleCodesIntoEmptySlots(batch, [
		P(8002),
		P(8002), // 输入内重复
		P(8001), // 已在罐里
		'8021761' + '0000000000009', // 错前缀
		'8206233' + '00000000000', // 12 位，非法
		P(8003)
	])
	equal(result.result.written.join(','), `${P(8002)},${P(8003)}`, '只写入两枚新码')
	equal(result.result.duplicates.length, 2, '重复 2 条（1 条输入内 + 1 条罐内）')
	equal(result.result.duplicates[0].where, '本次输入', '第 1 条重复的原因 = 本次输入')
	check(result.result.duplicates[1].where.includes('槽位'), '第 2 条重复说明在哪个槽位', result.result.duplicates[1].where)
	equal(result.result.invalid.length, 2, '无效 2 条（错前缀 + 短码）')
	equal(result.result.overflow.length, 0, '没有溢出')
	batch = result.batch
	equal(filled(batch), 3, '最终 3 枚（1 枚原有 + 2 枚新写）')

	const allDup = lb.fillParticleCodesIntoEmptySlots(batch, [P(8001), P(8002)])
	check(allDup.event.code !== lb.EVENT.OK, '全是重复 → 不报成功')
	equal(allDup.result.written.length, 0, '全是重复 → 一枚都不写')
	equal(allDup.batch, batch, '全是重复时不产生新批次对象')
}

// ---------------------------------------------------------------------------
section('fillParticleCodesIntoEmptySlots：罐满与非粒子相位')
// ---------------------------------------------------------------------------

{
	let batch = atParticlePhase(2)
	batch = lb.fillParticleCodesIntoEmptySlots(batch, [P(9001), P(9002)]).batch
	equal(filled(batch), 2, '前置：罐已满')

	const overflowAll = lb.fillParticleCodesIntoEmptySlots(batch, [P(9003)])
	check(overflowAll.event.code !== lb.EVENT.OK, '已满时再录入 → 不报成功')
	equal(overflowAll.result.written.length, 0, '已满 → 不写入')
	equal(overflowAll.result.overflow.length, 1, '已满 → 该码列进“未写入”')

	// 还没推进到粒子相位时，批量录入必须被拦住
	const created = lb.createDraft({
		batchNo: 'T-PHASE',
		produceDate: '2026-10-02',
		expireDate: '2026-12-01',
		deviceId: 'and-test-device'
	})
	const early = lb.fillParticleCodesIntoEmptySlots(lb.saveStructure(created, [[3]]).batch, [P(9010)])
	equal(early.event.code, lb.EVENT.WRONG_STATE, '箱号/罐号相位不接受粒子批量录入')
	equal(early.result.written.length, 0, '相位不对时不写入')

	const empty = lb.fillParticleCodesIntoEmptySlots(atParticlePhase(3), [])
	check(empty.event.code !== lb.EVENT.OK, '空输入 → 不报成功')
	equal(empty.result.written.length, 0, '空输入 → 不写入')
}

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`槽位补录 / 批量录入单测全部通过（${passed} 项）。`)
process.exit(0)
