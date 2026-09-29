/**
 * 本地数据层单测（v1.3.1：多箱包装结构，≥100 项）。
 *
 * 为什么用 .mjs + data: 导入，而不是直接 require：
 *   - `services/localBatch.js` 是 uni-app 的 ESM 源码，工程里没有 package.json；
 *   - Node 会把无 package.json 目录下的 .js 当 CommonJS，直接 import 会报语法错。
 *   所以这里把源码读出来、按 ESM 从 data: URL 加载。
 *   好处是**不为了测试去改产品代码**，也不引入任何测试框架依赖。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/localBatch.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '..', 'services', 'localBatch.js'), 'utf8')
const lb = await import('data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'))

// ---------------------------------------------------------------------------
// 极简断言
// ---------------------------------------------------------------------------

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
// 内存存储适配器（模拟 uni.setStorageSync / getStorageSync）
// ---------------------------------------------------------------------------

function memoryAdapter() {
	const map = new Map()
	return {
		get: (key) => (map.has(key) ? JSON.parse(JSON.stringify(map.get(key))) : ''),
		set: (key, value) => map.set(key, JSON.parse(JSON.stringify(value))),
		remove: (key) => map.delete(key),
		_raw: map
	}
}

const storage = memoryAdapter()
lb.setStorageAdapter(storage)

// 造码工具：箱 / 罐 / 粒子**统一是 20 位追溯码**，层级只由前缀决定（v1.4.0）
const boxCode = (n) => '8021761' + String(n).padStart(13, '0')
const canCode = (n) => '8021762' + String(n).padStart(13, '0')
const particle = (n) => '8206233' + String(n).padStart(13, '0')

// 20 位条码：用于 classifyCode 与层级断言
const BOX_BARCODE = boxCode(1001)
const CAN_BARCODE = canCode(2001)

// 业务值（v1.4.0）：箱号 / 罐号与粒子码同口径 —— 20 位 + 前缀。
// 罐号在本箱内唯一，所以不同箱可以复用同一个罐号（CAN3 与 CAN1 相同）。
const BOX1 = boxCode(1)
const BOX2 = boxCode(2)
const CAN1 = canCode(1)
const CAN2 = canCode(2)
const CAN3 = canCode(1)
const P1 = particle(3001)
const P2 = particle(3002)
const P3 = particle(3003)

function draft(boxCounts, options) {
	const created = lb.createDraft({
		batchNo: 'T-20260927',
		produceDate: '2026-09-27',
		expireDate: '2026-10-27',
		deviceId: 'and-test-device'
	})
	if (!boxCounts) return created
	const outcome = lb.saveStructure(created, boxCounts, options)
	if (outcome.issues && outcome.issues.length) throw new Error('测试结构不合法：' + outcome.issues[0].message)
	return outcome.batch
}

/** 连续扫一串码，返回最后一批。 */
function scan(batch, codes) {
	let current = batch
	for (const code of codes) {
		current = lb.applyCodes(current, [code]).batch
	}
	return current
}

// ---------------------------------------------------------------------------
section('条码校验（20 位定长 + 前缀表）')
// ---------------------------------------------------------------------------

equal(lb.classifyCode(BOX_BARCODE), 3, '20 位串 8021761… → classifyCode 判为层级 3')
equal(lb.classifyCode(CAN_BARCODE), 2, '20 位串 8021762… → classifyCode 判为层级 2')
equal(lb.classifyCode(P1), 1, '粒子码前缀 8206233 → 层级 1')
equal(lb.classifyCode('8021761000001412585'), null, '19 位 → 拒绝')
equal(lb.classifyCode('802176190000000010031'), null, '21 位 → 拒绝')
equal(lb.classifyCode('8021761000001412585A'), null, '含字母 → 拒绝')
equal(lb.classifyCode('99999990000014125856'), null, '未知前缀 → 拒绝')
equal(lb.classifyCode('  ' + BOX_BARCODE + '  '), 3, '首尾空格容忍')
equal(lb.classifyCode(''), null, '空串 → 拒绝')
equal(lb.CASCADE, '1:5:2500', 'cascade 是固定字面量')
equal(lb.FIXED_PARAMS.length, 13, '固定参数 13 项')
equal(lb.SCHEMA_VERSION, 2, '数据结构版本 = 2（多箱）')

// ---------------------------------------------------------------------------
section('分层校验：箱 / 罐 / 粒子 = 20 位追溯码 + 前缀（v1.4.0）')
// ---------------------------------------------------------------------------

equal(lb.BARCODE_LENGTH, 20, '统一长度 = 20 位')
equal(lb.CODE_PREFIXES[3], '8021761', '箱号前缀 = 8021761')
equal(lb.CODE_PREFIXES[2], '8021762', '罐号前缀 = 8021762')
equal(lb.CODE_PREFIXES[1], '8206233', '粒子前缀 = 8206233')

// 连字符清洗：现场罐码二维码印的就是「8021762-9000000001003」
equal(lb.cleanLayerCode('8021762-9000000001003', 2), '80217629000000001003', '罐号：剥掉连字符')
equal(lb.cleanLayerCode(' 8021762-9000000001003 ', 2), '80217629000000001003', '罐号：首尾空格 + 连字符一起清')
equal(lb.cleanLayerCode('80217629000000001003', 2), '80217629000000001003', '罐号：清洗幂等（本身无连字符）')
equal(lb.cleanLayerCode('8021761-9000000001002', 3), '80217619000000001002', '箱号：同样剥连字符')
equal(lb.cleanLayerCode('8206233-000003000001', 1), '8206233-000003000001', '粒子码：保持原样，不清洗')

// 正向：20 位 + 前缀正确 → 通过
equal(lb.validateLayerCode('80217619000000001002', 3), '', '箱号 20 位 + 8021761 → 通过')
equal(lb.validateLayerCode(BOX1, 3), '', '箱号（造码工具）→ 通过')
equal(lb.validateLayerCode('8021761-9000000001002', 3), '', '箱号带连字符 → 清洗后通过')
equal(lb.validateLayerCode('8021762-9000000001003', 2), '', '罐号带连字符 → 清洗后通过（文档验收点）')
equal(lb.validateLayerCode(CAN1, 2), '', '罐号（造码工具）→ 通过')
equal(lb.validateLayerCode(P1, 1), '', '粒子码 → 通过（规则不变）')

// 反向：长度 / 字符 / 前缀不对 → 拦
check(lb.validateLayerCode('1', 3).includes('20 位'), '箱号「1」→ 拦截并要求 20 位', lb.validateLayerCode('1', 3))
check(lb.validateLayerCode('10000', 3).includes('20 位'), '箱号「10000」→ 拦截并要求 20 位', lb.validateLayerCode('10000', 3))
check(lb.validateLayerCode('1.5', 3).includes('20 位'), '箱号「1.5」→ 拦截', lb.validateLayerCode('1.5', 3))
check(lb.validateLayerCode('1a', 3).includes('20 位'), '箱号「1a」→ 拦截', lb.validateLayerCode('1a', 3))
check(lb.validateLayerCode('8021761000001406604', 3).includes('20 位'), '箱号 19 位 → 拦截', lb.validateLayerCode('8021761000001406604', 3))
check(lb.validateLayerCode('80217629000000001002', 3).includes('8021761'), '箱号用了罐号前缀 → 拦截并指出 8021761', lb.validateLayerCode('80217629000000001002', 3))
check(lb.validateLayerCode('80217619000000001002', 2).includes('8021762'), '罐号用了箱号前缀 → 拦截并指出 8021762', lb.validateLayerCode('80217619000000001002', 2))
check(lb.validateLayerCode('99999999000000001002', 3).includes('20 位'), '未知前缀 → 拦截', lb.validateLayerCode('99999999000000001002', 3))
check(lb.validateLayerCode('', 3).includes('不能为空'), '空串 → 提示不能为空')
check(lb.validateLayerCode(P1, 3).includes('8021761'), '粒子条码当箱号 → 提示里给出箱号前缀', lb.validateLayerCode(P1, 3))
check(lb.validateLayerCode('1', 1).includes('20 位'), '短号当粒子码 → 仍要求 20 位', lb.validateLayerCode('1', 1))
equal(lb.validateLayerCode('1', 9), '未知的层级：9', '未知层级 → 明确报错')

// 面向操作员的文案：箱/罐步骤误扫粒子条码要给专门提示
check(
	lb.describeCodeIssue(P1, 3).includes('这是粒子条码') && lb.describeCodeIssue(P1, 3).includes('8021761'),
	'箱号步骤误扫粒子条码 → 提示「这是粒子条码…前缀 8021761」',
	lb.describeCodeIssue(P1, 3)
)
check(
	lb.describeCodeIssue(P1, 2).includes('这是粒子条码') && lb.describeCodeIssue(P1, 2).includes('8021762'),
	'罐号步骤误扫粒子条码 → 同样给粒子条码提示',
	lb.describeCodeIssue(P1, 2)
)
check(lb.describeCodeIssue(BOX1, 3) === '', '合法箱号 → 无提示')
check(lb.describeCodeIssue('8021762-9000000001003', 2) === '', '带连字符的合法罐号 → 无提示')
check(lb.describeCodeIssue('1a', 3).includes('20 位'), '非法字符 → 20 位提示', lb.describeCodeIssue('1a', 3))

// ---------------------------------------------------------------------------
section('基础信息校验')
// ---------------------------------------------------------------------------

check(lb.validateBaseInfo({ batchNo: '', produceDate: '', expireDate: '' }).length === 3, '三项必填都要报')
check(
	lb.validateBaseInfo({ batchNo: 'A', produceDate: '2026-09-27', expireDate: '2026-09-27' }).some(
		(item) => item.code === 'EXPIRE_NOT_AFTER_PRODUCE'
	),
	'有效期等于生产日期 → 拒绝'
)
equal(
	lb.validateBaseInfo({ batchNo: 'A', produceDate: '2026-09-27', expireDate: '2026-10-27' }).length,
	0,
	'合法基础信息 → 通过'
)
check(
	lb.validateBaseInfo({ batchNo: 'A', produceDate: '2026-09-27', expireDate: '2026-09-26' }).some(
		(item) => item.code === 'EXPIRE_NOT_AFTER_PRODUCE'
	),
	'有效期早于生产日期 → 拒绝'
)

// ---------------------------------------------------------------------------
section('包装结构校验（多箱：箱 1~5、每箱罐 1~5、每罐 1~2500、单批 ≤12500）')
// ---------------------------------------------------------------------------

check(lb.validateStructure([[1]]).length === 0, '1 箱 1 罐 → 通过')
check(lb.validateStructure([]).length > 0, '0 箱 → 拒绝')
check(lb.validateStructure([[1], [1], [1], [1], [1], [1]]).length > 0, '6 箱 → 拒绝')
check(lb.validateStructure([[]]).length > 0, '某箱 0 罐 → 拒绝')
check(lb.validateStructure([[1, 2, 3, 4, 5, 6]]).length > 0, '某箱 6 罐 → 拒绝')
check(lb.validateStructure([[0]]).length > 0, '每罐粒子数 0 → 拒绝')
check(lb.validateStructure([[2501]]).length > 0, '每罐粒子数 2501 → 拒绝')
check(lb.validateStructure([[2.5]]).length > 0, '粒子数非整数 → 拒绝')
equal(lb.validateStructure([[2500, 2500]]).length, 0, '2 罐 × 2500 = 5000 → 通过')
equal(lb.validateStructure([[2500, 2500, 2500, 2500, 2500]]).length, 0, '5 罐 × 2500 = 12500 → 刚好通过')
check(lb.validateStructure([[2500, 2500, 2500, 2500, 2501]]).length > 0, '单批超过 12500 → 拒绝（方案 A：硬上限）')
check(
	lb.validateStructure([[2500, 2500], [2500, 2500], [2500, 2500], [2500, 2500], [2500, 2501]]).length > 0,
	'5 箱 × 5 罐 × 2500 超上限 → 拒绝'
)
equal(lb.validateStructure([[1, 1], [1]]).length, 0, '各箱罐数独立（2 罐 + 1 罐）→ 通过')
equal(lb.particleTotal([1, 2, 3]), 6, '一维数组求和')
equal(lb.particleTotal([[1, 2], [3]]), 6, '二维数组求和')
equal(lb.MIN_BOXES, 0, '箱数下限 = 0（0 表示不扫箱号 → 生成虚拟箱）')
equal(lb.MIN_STRUCTURE_GROUPS, 1, '数据结构至少要 1 组罐（「0 箱」落库后是 1 组罐 + 虚拟箱）')
equal(lb.MAX_BOXES, 5, '箱数上限 = 5')

// ---------------------------------------------------------------------------
section('虚拟箱（箱数 = 0）：XML 必须仍有 packLayer="3"，不能是空文件')
// ---------------------------------------------------------------------------

equal(lb.VIRTUAL_BOX_CODE, '80217619999999999999', '虚拟箱号固定为 9 打头的串')
equal(lb.validateStructure([['2']], { virtualBox: true }).length, 0, '虚拟箱：1 组罐 → 通过')
check(
	lb.validateStructure([['2'], ['2']], { virtualBox: true }).some((item) => item.code === 'VIRTUAL_BOX_SHAPE'),
	'虚拟箱：两组罐 → 拒绝（虚拟箱只会生成一个）'
)

const vBatch = draft([['2']], { virtualBox: true })
equal(vBatch.boxes.length, 1, '虚拟箱场景仍然落 1 个箱节点')
equal(vBatch.boxes[0].boxCode, lb.VIRTUAL_BOX_CODE, '箱号被预填为虚拟箱号')
equal(vBatch.boxes[0].virtual, true, '标记为虚拟箱')
equal(vBatch.boxes[0].reviewConfirmed, true, '虚拟箱没有实物可核对 → 直接置真')
equal(lb.deriveWizard(vBatch).phase, 'can', '向导直接进罐号相位，跳过拍箱号')

let vFlow = lb.applyCodes(vBatch, [CAN1]).batch
vFlow = lb.applyCodes(vFlow, [P1, P2]).batch
vFlow = lb.confirmCanReview(vFlow, true).batch
equal(lb.deriveWizard(vFlow).phase, 'review', '虚拟箱不额外要求一次箱核对，直接进整体核对')

// 对照组：普通 1 箱仍然要求拍箱号
equal(lb.deriveWizard(draft([['2']])).phase, 'box', '普通箱仍然从拍箱号开始')

// ---------------------------------------------------------------------------
section('严格提取：只清已知分隔符，非法字符必须报警而不是静默清洗')
// ---------------------------------------------------------------------------

equal(lb.extractDigits('8021762-0000015372035', 2).code, '80217620000015372035', '罐码连字符被清掉')
equal(lb.extractDigits('8021762-0000015372035', 2).illegal, '', '正常罐码没有非法字符')
equal(lb.extractDigits(' 8021761-0000014066041 ', 3).code, '80217610000014066041', '箱码首尾空格 + 连字符一起清')
check(lb.extractDigits('A8021761-0000014066041', 3).illegal.includes('A'), '多余字母 A → 报出来')
check(lb.extractDigits('8O21761-0000014066041', 3).illegal.includes('O'), '字母 O 混入 → 报出来（绝不替换成 0）')
equal(
	lb.extractDigits('A8021761-0000014066041', 3).code,
	'A80217610000014066041',
	'code 原样保留非法字符，便于操作员核对'
)
check(!lb.extractDigits('A8021761-0000014066041', 3).code.includes('-'), '已知分隔符仍然被清掉')
equal(lb.extractDigits('82062330000362322676', 1).illegal, '', '粒子码不清洗也不报非法')

// ---------------------------------------------------------------------------
section('强制结束本罐：没扫满也能收尾，缺漏交给整体核对如实显示')
// ---------------------------------------------------------------------------

let fe = draft([[3]])
fe = lb.applyCodes(fe, [BOX1]).batch
fe = lb.applyCodes(fe, [CAN1]).batch
fe = lb.applyCodes(fe, [P1]).batch
equal(lb.deriveWizard(fe).phase, 'particle', '只扫了 1/3 → 仍在粒子相位（本来到不了 CAN_REVIEW）')
const feOut = lb.forceEndCan(fe)
equal(feOut.event.code, lb.EVENT.OK, '粒子相位可以强制结束本罐')
equal(feOut.batch.boxes[0].cans[0].confirmed, true, '本罐标记为已确认')
equal(lb.deriveWizard(feOut.batch).phase, 'box_review', '推进到本箱核对')
equal(lb.findUsage(feOut.batch, P1, 1).where, '箱 1 罐 1 / 槽位 1', '已扫的粒子仍在，没被补齐也没被抹掉')
check(lb.forceEndCan(feOut.batch).event.code === lb.EVENT.WRONG_STATE, '不在粒子相位 → 拒绝，避免重复触发')

// ---------------------------------------------------------------------------
section('本地存储与状态机')
// ---------------------------------------------------------------------------

const saved = lb.saveBatch(draft([[2, 2]]))
equal(lb.getActiveBatch().localId, saved.localId, '保存后成为当前批次')
equal(lb.getActiveBatch().deviceId, 'and-test-device', '本地批次带设备指纹（C4）')
equal(lb.getActiveBatch().status, lb.LOCAL_STATUS.COLLECTING, '配好结构后状态为采集中')
equal(lb.listBatches().length, 1, '批次列表可读回')
equal(lb.getActiveBatch().boxes.length, 1, '结构写入 boxes')
equal(lb.getActiveBatch().boxes[0].cans.length, 2, '箱 1 里有两罐')
equal(lb.getActiveBatch().boxes[0].cans[1].plannedParticleCount, 2, '罐 2 计划 2 粒')
equal(lb.getActiveBatch().boxes[0].cans[0].particles.length, 2, '罐 1 生成 2 个空槽位')
equal(lb.getActiveBatch().boxes[0].cans[0].particles[0], '', '槽位初始为空串')

const draftOnly = draft()
equal(draftOnly.boxes.length, 0, '新草稿还没有包装结构')
const toCollecting = lb.transition(draftOnly, lb.LOCAL_STATUS.COLLECTING)
equal(toCollecting.batch.status, 'collecting', '草稿 → 采集中 允许')
const jump = lb.transition(draftOnly, lb.LOCAL_STATUS.VERIFIED)
equal(jump.batch.status, 'draft', '草稿 → 已核对（跳级）被拒绝')
check(jump.event.message.includes('允许'), '跳级时说明允许的目标', jump.event.message)
equal(
	lb.transition(lb.transition(toCollecting.batch, 'pending_review').batch, 'verified').batch.status,
	'verified',
	'采集中 → 待核对 → 已核对'
)

// ---------------------------------------------------------------------------
section('向导推导：单箱不跳步')
// ---------------------------------------------------------------------------

let batch = draft([[2, 2]])
let wizard = lb.deriveWizard(batch)
equal(wizard.step, 1, '新建后停在步骤 1（拍箱号）')
equal(wizard.phase, 'box', '相位为 box')
equal(wizard.totalBoxes, 1, '总箱数 = 1')
equal(wizard.totalCans, 2, '总罐数 = 2')
equal(wizard.plannedParticles, 4, '计划粒子总数 = 4')

let result = lb.applyCodes(batch, [BOX1])
batch = result.batch
equal(result.event.code, lb.EVENT.OK, '箱号写入成功')
equal(batch.boxes[0].boxCode, BOX1, '箱号写在 boxes[0].boxCode')
wizard = lb.deriveWizard(batch)
equal(wizard.phase, 'can', '进入拍罐号')
equal(wizard.canIndex, 1, '当前罐 1')

result = lb.applyCodes(batch, [CAN1])
batch = result.batch
equal(batch.boxes[0].cans[0].canCode, CAN1, '罐号写在 cans[0].canCode')
equal(lb.deriveWizard(batch).phase, 'particle', '进入拍粒子')

result = lb.applyCodes(batch, [P1, P2])
batch = result.batch
equal(result.event.code, lb.EVENT.OK, '粒子按序写入')
equal(lb.deriveWizard(batch).phase, 'can_review', '本罐扫满 → 本罐核对')

result = lb.confirmCanReview(batch, false)
equal(lb.deriveWizard(result.batch).phase, 'can_review', '选「还没好」仍留在本罐核对')
const canConfirmed = lb.confirmCanReview(batch, true)
batch = canConfirmed.batch
equal(batch.boxes[0].cans[0].confirmed, true, '本罐确认落盘')
wizard = lb.deriveWizard(batch)
equal(wizard.phase, 'can', '确认后进入罐 2 的拍罐号')
equal(wizard.canIndex, 2, '当前罐 2')

// ---------------------------------------------------------------------------
section('向导推导：多箱循环（box → … → box_review → 下一箱 → review）')
// ---------------------------------------------------------------------------

let multi = draft([[2, 1], [1]])
wizard = lb.deriveWizard(multi)
equal(wizard.totalBoxes, 2, '总箱数 = 2')
equal(wizard.totalCans, 3, '总罐数 = 3（2 + 1）')
equal(wizard.plannedParticles, 4, '计划粒子 4（2+1+1）')
equal(wizard.cansInBox, 2, '第 1 箱有 2 罐')
check(wizard.prompt.includes('第 1 箱 / 共 2 箱'), '步骤 1 文案带箱序号', wizard.prompt)

multi = lb.applyCodes(multi, [BOX1]).batch
equal(lb.deriveWizard(multi).boxIndex, 1, '仍在第 1 箱')
multi = scan(multi, [CAN1, P1, P2])
multi = lb.confirmCanReview(multi, true).batch
multi = scan(multi, [CAN2, P3])
multi = lb.confirmCanReview(multi, true).batch
wizard = lb.deriveWizard(multi)
equal(wizard.phase, 'box_review', '本箱罐全部确认 → 本箱核对')
equal(wizard.isLastBox, false, '第 1 箱不是最后一箱')
check(wizard.prompt.includes('是否继续拍下一箱'), '本箱核对提示拍下一箱', wizard.prompt)

const boxConfirm = lb.confirmBoxReview(multi, true)
equal(boxConfirm.event.code, lb.EVENT.OK, '本箱确认成功')
multi = boxConfirm.batch
equal(multi.boxes[0].reviewConfirmed, true, '本箱完成标记落盘')
wizard = lb.deriveWizard(multi)
equal(wizard.phase, 'box', '确认后回到步骤 1 拍第 2 箱箱号')
equal(wizard.boxIndex, 2, '当前第 2 箱')
equal(wizard.isLastBox, true, '第 2 箱是最后一箱')
check(wizard.prompt.includes('第 2 箱 / 共 2 箱'), '第 2 箱提示带序号', wizard.prompt)

multi = lb.applyCodes(multi, [BOX2]).batch
equal(multi.boxes[1].boxCode, BOX2, '第 2 箱箱号写入 boxes[1]')
multi = scan(multi, [CAN3, particle(3004)])
multi = lb.confirmCanReview(multi, true).batch
wizard = lb.deriveWizard(multi)
equal(wizard.phase, 'box_review', '最后一箱罐确认后进入本箱核对')
equal(wizard.isLastBox, true, '标记为最后一箱')
const lastBoxConfirm = lb.confirmBoxReview(multi, true)
equal(lastBoxConfirm.event.code, lb.EVENT.OK, '最后一箱也能确认')
wizard = lb.deriveWizard(lastBoxConfirm.batch)
equal(wizard.step, 3, '确认最后一箱 → 步骤 3')
equal(wizard.phase, 'review', '相位为整体核对')
equal(
	lb.confirmBoxReview(lb.applyCodes(draft([[1]]), [BOX1]).batch, true).event.code,
	lb.EVENT.WRONG_STATE,
	'不在本箱核对时确认 → 拒绝'
)

// ---------------------------------------------------------------------------
section('拦截：多码 / 错层 / 重复 / 溢出（跨箱跨罐查重）')
// ---------------------------------------------------------------------------

const fresh = draft([[2, 2]])
const multiCode = lb.applyCodes(fresh, [BOX1, CAN1])
equal(multiCode.event.code, lb.EVENT.MULTI_CODE, '拍箱号时两个码 → 多码报警')
check(multiCode.event.needsAlarm === true, '多码事件要求震动+视觉报警')

const wrongLayer = lb.applyCodes(fresh, [P1])
equal(wrongLayer.event.code, lb.EVENT.WRONG_LAYER, '拍箱号时给粒子码 → 层级不符')

let dupe = lb.applyCodes(fresh, [BOX1]).batch
dupe = lb.applyCodes(dupe, [CAN1]).batch
const dupeResult = lb.applyCodes(dupe, [P1, P1])
equal(dupeResult.event.code, lb.EVENT.DUPLICATE_CODE, '同一帧内重复码 → 拒绝')
equal(lb.deriveWizard(dupeResult.batch).actualParticles, 0, '被拒的帧不写入')

let overflow = lb.applyCodes(fresh, [BOX1]).batch
overflow = lb.applyCodes(overflow, [CAN2]).batch
const overflowResult = lb.applyCodes(overflow, [P1, P2, P3])
equal(overflowResult.event.code, lb.EVENT.OVERFLOW, '超出本罐计划 → 溢出拦截')
equal(lb.deriveWizard(overflowResult.batch).actualParticles, 0, '溢出整帧不写入')
check(overflowResult.event.message.includes('箱 1 罐 1'), '溢出提示带箱罐坐标', overflowResult.event.message)

// 罐 1 完成后，罐 2 的溢出也要带正确的箱罐坐标
let overflow2 = scan(fresh, [BOX1, CAN1, P1, P2])
overflow2 = lb.confirmCanReview(overflow2, true).batch
overflow2 = scan(overflow2, [CAN2])
const overflowResult2 = lb.applyCodes(overflow2, [particle(3011), particle(3012), particle(3013)])
equal(overflowResult2.event.code, lb.EVENT.OVERFLOW, '罐 2 超计划 → 溢出拦截')
check(overflowResult2.event.message.includes('箱 1 罐 2'), '溢出提示的罐序号正确', overflowResult2.event.message)

const dupBatch = lb.applyCodes(lb.applyCodes(fresh, [BOX1]).batch, [CAN1]).batch
const intoCan2 = lb.applyCodes(dupBatch, [P1, P2]).batch
const reopen = lb.applyCodes(lb.confirmCanReview(intoCan2, true).batch, [CAN2]).batch
const crossDup = lb.applyCodes(reopen, [P1])
equal(crossDup.event.code, lb.EVENT.DUPLICATE_CODE, '跨罐重复粒子码 → 拒绝')

// 分层查重（v1.3.2 核心）：箱号全批唯一、罐号本箱内唯一
let twoBox = draft([[1], [1]])
twoBox = scan(twoBox, [BOX1, CAN1, P1])
twoBox = lb.confirmCanReview(twoBox, true).batch
twoBox = lb.confirmBoxReview(twoBox, true).batch
equal(lb.applyCodes(twoBox, [BOX1]).event.code, lb.EVENT.DUPLICATE_CODE, '箱号全批唯一：第 2 箱复用同一个箱号 → 拒绝')
check(
	lb.applyCodes(twoBox, [BOX1]).event.message.includes('箱 1 号'),
	'箱号重复时提示指明是哪一箱占用',
	lb.applyCodes(twoBox, [BOX1]).event.message
)
twoBox = lb.applyCodes(twoBox, [BOX2]).batch
// 罐 1 在箱 1 里已用过，但箱 2 的罐 1 依然是合法值 → 必须放行
const crossBoxCan = lb.applyCodes(twoBox, [CAN1])
equal(crossBoxCan.event.code, lb.EVENT.OK, '罐号本箱内唯一：箱 2 罐 1 与箱 1 罐 1 用同一个罐号 → 允许')
equal(crossBoxCan.batch.boxes[1].cans[0].canCode, CAN1, '箱 2 罐 1 的罐号写入成功')
equal(crossBoxCan.batch.boxes[0].cans[0].canCode, CAN1, '箱 1 罐 1 原值不受影响')

// 同一箱内重复罐号仍要挡住
let sameBox = draft([[1, 1]])
sameBox = scan(sameBox, [BOX1, CAN1, P1])
sameBox = lb.confirmCanReview(sameBox, true).batch
const sameBoxDup = lb.applyCodes(sameBox, [CAN1])
equal(sameBoxDup.event.code, lb.EVENT.DUPLICATE_CODE, '同一箱内罐号重复 → 拒绝')
check(sameBoxDup.event.message.includes(`罐号 ${CAN1} 已被使用`), '罐号重复提示带层级叫法', sameBoxDup.event.message)

// findUsage 的分层作用域（显式传 layer 的三种口径）
const settled = crossBoxCan.batch
equal(lb.findUsage(settled, BOX1, 3).where, '箱 1 号', 'findUsage(layer 3)：命中箱 1 号')
equal(lb.findUsage(settled, CAN1, 2, { boxIndex: 0 }).where, '箱 1 罐 1 号', 'findUsage(layer 2, 箱 1)：命中箱 1 罐 1')
equal(lb.findUsage(settled, CAN1, 2, { boxIndex: 1 }).where, '箱 2 罐 1 号', 'findUsage(layer 2, 箱 2)：命中箱 2 罐 1（同号但不同箱）')
equal(lb.findUsage(settled, CAN1, 2, { boxIndex: 1, excludeCanIndex: 0 }), null, 'findUsage(layer 2) 排除自己后不命中')
equal(lb.findUsage(settled, BOX1, 3, { excludeBoxIndex: 0 }), null, 'findUsage(layer 3) 排除自己后不命中')
equal(lb.findUsage(settled, '9', 2, { boxIndex: 1 }), null, '没出现过的号 → 不命中')

// ---------------------------------------------------------------------------
section('粒子顺序（严禁排序）')
// ---------------------------------------------------------------------------

let orderBatch = draft([[3, 1]])
orderBatch = scan(orderBatch, [BOX1, CAN1])
orderBatch = lb.applyCodes(orderBatch, [P3, P1, P2]).batch
equal(orderBatch.boxes[0].cans[0].particles.join(','), [P3, P1, P2].join(','), '写入顺序 = 识别顺序（未排序）')
equal(lb.deriveWizard(orderBatch).actualParticles, 3, '实际粒子数 = 3')

// ---------------------------------------------------------------------------
section('槽位替换 / 删除 / 撤销 / 重做（栈 50）')
// ---------------------------------------------------------------------------

let slotBatch = draft([[3, 1]])
slotBatch = scan(slotBatch, [BOX1, CAN1])
slotBatch = lb.applyCodes(slotBatch, [P1, P2, P3]).batch

const replaced = lb.replaceSlot(slotBatch, 0, 0, 0, particle(3009))
equal(replaced.event.code, lb.EVENT.OK, '替换槽位成功')
equal(replaced.batch.boxes[0].cans[0].particles[0], particle(3009), '替换后槽位是新码')
equal(lb.replaceSlot(slotBatch, 0, 0, 0, P2).event.code, lb.EVENT.DUPLICATE_CODE, '替换成已用码 → 拒绝')
equal(lb.replaceSlot(slotBatch, 0, 0, 0, BOX1).event.code, lb.EVENT.WRONG_LAYER, '替换成箱号 → 层级拒绝')
equal(lb.replaceSlot(slotBatch, 0, 9, 0, P1).event.code, lb.EVENT.WRONG_STATE, '换不存在的罐 → 拒绝')

const deleted = lb.deleteSlot(replaced.batch, 0, 0, 1)
equal(deleted.batch.boxes[0].cans[0].particles[1], '', '删除后槽位置空')
equal(lb.deleteSlot(deleted.batch, 0, 0, 1).event.code, lb.EVENT.WRONG_STATE, '删除空槽位 → 拒绝')

const undone = lb.undo(deleted.batch)
equal(undone.batch.boxes[0].cans[0].particles[1], P2, '撤销删除 → 条码回来')
const redone = lb.redo(undone.batch)
equal(redone.batch.boxes[0].cans[0].particles[1], '', '重做删除 → 又置空')
const undoAgain = lb.undo(redone.batch)
const undoReplace = lb.undo(undoAgain.batch)
equal(undoReplace.batch.boxes[0].cans[0].particles[0], P1, '继续撤销到替换之前')
check(lb.historyState(undoReplace.batch).canRedo === true, '撤销后可以重做')
equal(lb.undo(undoReplace.batch).event.code, lb.EVENT.OK, '还能继续撤销（撤掉本罐录入）')

let stackBatch = draft([[60]])
stackBatch = scan(stackBatch, [BOX1, CAN1])
for (let index = 0; index < 60; index += 1) {
	stackBatch = lb.applyCodes(stackBatch, [particle(4000 + index)]).batch
}
equal(lb.historyState(stackBatch).undoCount, lb.UNDO_LIMIT, `做 60 次操作后撤销栈被限制在 ${lb.UNDO_LIMIT} 步`)
equal(lb.historyState(stackBatch).undoCount, 50, '实测撤销栈 = 50')

let crossUndo = draft([[1], [1]])
crossUndo = scan(crossUndo, [BOX1, CAN1, P1])
crossUndo = lb.confirmCanReview(crossUndo, true).batch
crossUndo = lb.confirmBoxReview(crossUndo, true).batch
crossUndo = scan(crossUndo, [BOX2, CAN2, particle(3005)])
const crossUndoResult = lb.undo(crossUndo)
equal(crossUndoResult.batch.boxes[1].cans[0].particles[0], '', '撤销第 2 箱的粒子写入（坐标带箱号）')
equal(crossUndoResult.batch.boxes[0].cans[0].particles[0], P1, '第 1 箱数据不受影响')

// ---------------------------------------------------------------------------
section('本地核对（多箱）与提前结束')
// ---------------------------------------------------------------------------

let reviewBatch = draft([[2, 1], [1]])
reviewBatch = scan(reviewBatch, [BOX1, CAN1, P1, P2])
reviewBatch = lb.confirmCanReview(reviewBatch, true).batch
reviewBatch = scan(reviewBatch, [CAN2])
let review = lb.review(reviewBatch)
equal(review.checks.length, 5, '核对输出 5 项检查')
equal(review.perBox.length, 2, '按箱分组输出 2 组')
equal(review.perCan.length, 3, '罐明细 3 行')
equal(review.plan.boxCount, 2, '计划 2 箱')
equal(review.plan.canCount, 3, '计划 3 罐')
equal(review.plan.particleTotal, 4, '计划 4 粒')
equal(review.actual.particleTotal, 2, '实际 2 粒')
equal(review.missingParticles, 2, '缺漏 2 粒')
check(review.blocking.length > 0, '有缺漏 → 存在阻断项')
equal(review.canVerify, false, '缺漏且未签名 → 不允许确认核对')
equal(review.perBox[0].complete, false, '第 1 箱有罐没扫满 → 未完成')
equal(review.perBox[1].boxCode, '', '第 2 箱还没箱号')
check(review.checks[0].detail.includes('计划 2 箱 3 罐'), '罐数一致检查带箱数说明', review.checks[0].detail)
equal(review.perCan[0].boxIndex, 1, '罐明细带箱序号')
equal(review.perCan[2].boxIndex, 2, '第 3 行属于第 2 箱')

reviewBatch = scan(reviewBatch, [P3])
reviewBatch = lb.confirmCanReview(reviewBatch, true).batch
reviewBatch = lb.confirmBoxReview(reviewBatch, true).batch
reviewBatch = scan(reviewBatch, [BOX2, CAN3, particle(3006)])
reviewBatch = lb.confirmCanReview(reviewBatch, true).batch
reviewBatch = lb.confirmBoxReview(reviewBatch, true).batch
review = lb.review(reviewBatch)
equal(review.blocking.length, 0, '补齐全部箱罐后 5 项全过')
equal(review.canVerify, true, '全过 → 允许确认核对')
equal(review.actual.boxCount, 2, '实际箱数 = 2')
equal(review.actual.canCount, 3, '实际罐数 = 3')
equal(review.actual.particleTotal, 4, '实际粒子数 = 4')

let early = draft([[1], [1], [1]])
early = scan(early, [BOX1, CAN1, P1])
early = lb.confirmCanReview(early, true).batch
early = lb.confirmBoxReview(early, true).batch
early = lb.finishRemaining(early).batch
wizard = lb.deriveWizard(early)
equal(wizard.step, 3, '提前结束 → 直接进入整体核对')
equal(wizard.phase, 'review', '相位为 review')
const earlyReview = lb.review(early)
check(earlyReview.blocking.length > 0, '提前结束时仍如实显示缺漏')
equal(earlyReview.canVerify, false, '未签名 → 不允许确认核对')
equal(earlyReview.perBox.length, 3, '没拍的箱照样出现在核对里')
equal(
	lb.registerEarlyEnd(early, { reason: '', operator: '操作员甲' }).event.code,
	lb.EVENT.WRONG_STATE,
	'缺原因 → 拒绝签名'
)
equal(
	lb.registerEarlyEnd(early, { reason: '罐标签污损', operator: '' }).event.code,
	lb.EVENT.WRONG_STATE,
	'缺操作人 → 拒绝签名'
)
const signed = lb.registerEarlyEnd(early, { reason: '罐标签污损', operator: '操作员甲', note: '' })
equal(signed.event.code, lb.EVENT.OK, '原因+操作人齐全 → 登记成功')
equal(signed.batch.earlyEnd.actualBoxCount, 1, '提前结束记录的实际箱数由数据算出')
equal(signed.batch.earlyEnd.actualCanCount, 1, '提前结束记录的实际罐数由数据算出')
equal(lb.review(signed.batch).canVerify, true, '已签名 → 允许确认核对')
equal(lb.clearEarlyEnd(signed.batch).batch.earlyEnd, null, '可撤销提前结束登记')

// ---------------------------------------------------------------------------
section('v1.3.0 单箱数据自动迁移')
// ---------------------------------------------------------------------------

const legacy = {
	localId: 'LB-legacy-0001',
	deviceId: 'and-old',
	offline: true,
	status: 'collecting',
	batchNo: 'OLD-1',
	produceDate: '2026-09-01',
	expireDate: '2026-10-01',
	plannedParticleCounts: [2, 1],
	box: { code: BOX1 },
	cans: [
		{ canIndex: 1, code: CAN1, plannedParticleCount: 2, confirmed: true, slots: [P1, P2] },
		{ canIndex: 2, code: '', plannedParticleCount: 1, confirmed: false, slots: [''] }
	],
	history: { undo: [{ type: 'fill', canIndex: 0, entries: [{ index: 0, code: P1 }] }], redo: [] },
	earlyEnd: null,
	finishRequested: false,
	createdAt: '2026-09-01T00:00:00.000Z',
	updatedAt: '2026-09-01T00:00:00.000Z'
}

const migrated = lb.migrateBatch(legacy)
equal(migrated.schemaVersion, 2, '迁移后 schemaVersion = 2')
equal(migrated.boxes.length, 1, '单箱数据 → 1 个箱子')
equal(migrated.boxes[0].boxCode, BOX1, '旧 box.code → boxes[0].boxCode')
equal(migrated.boxes[0].cans.length, 2, '旧 cans → boxes[0].cans')
equal(migrated.boxes[0].cans[0].canCode, CAN1, '旧 can.code → canCode')
equal(migrated.boxes[0].cans[0].particles[0], P1, '旧 slots → particles')
equal(migrated.boxes[0].cans[1].particles.length, 1, '旧槽位长度按计划重建')
equal(migrated.box, undefined, '旧 box 字段已清掉')
equal(migrated.cans, undefined, '旧 cans 字段已清掉')
equal(migrated.plannedParticleCounts, undefined, '旧计划字段已清掉')
equal(migrated.history.undo[0].boxIndex, 0, '旧撤销记录补上 boxIndex = 0')
equal(migrated.boxes[0].reviewConfirmed, true, '单箱老数据视为本箱已完成，不额外追问一次')
equal(lb.migrateBatch(migrated), migrated, '已是 v2 的数据原样返回（幂等）')

const migratedWizard = lb.deriveWizard(migrated)
equal(migratedWizard.phase, 'can', '迁移后可继续向导（罐 2 还没罐号）')
equal(migratedWizard.boxIndex, 1, '停留在第 1 箱')
equal(migratedWizard.actualParticles, 2, '迁移后已扫粒子数仍为 2')
equal(lb.review(migrated).actual.particleTotal, 2, '迁移后核对口径一致')

lb.clearAll()
storage._raw.set('pharmrelate.local.batches', JSON.parse(JSON.stringify({ 'LB-legacy-0001': legacy })))
storage._raw.set('pharmrelate.local.activeId', 'LB-legacy-0001')
const readBack = lb.getActiveBatch()
equal(readBack.schemaVersion, 2, '从存储读回旧数据 → 自动迁移')
equal(readBack.boxes.length, 1, '读回后是 1 箱')
equal(storage.get('pharmrelate.local.batches')['LB-legacy-0001'].schemaVersion, 2, '迁移结果已回写存储')

// ---------------------------------------------------------------------------
section('存储读写（离线可用）')
// ---------------------------------------------------------------------------

lb.clearAll()
equal(lb.getActiveBatch(), null, '清空后没有当前批次')
const offlineBatch = lb.saveBatch(draft([[1]]))
equal(lb.getActiveBatch().localId, offlineBatch.localId, '保存后能读回（模拟断网）')
equal(lb.getActiveBatch().offline, true, '本地批次标记 offline')
equal(lb.loadBatches()[offlineBatch.localId].boxes.length, 1, '本地存储里是完整多箱结构')
lb.removeBatch(offlineBatch.localId)
equal(lb.getActiveBatch(), null, '删除后当前批次为空')

// ---------------------------------------------------------------------------
section('汇总（总箱数 / 总罐数 / 总粒子数 / 进度）')
// ---------------------------------------------------------------------------

const summary = lb.planSummary(draft([[1, 2], [3]]))
equal(summary.boxes, 2, '总箱数 = 2')
equal(summary.cans, 3, '总罐数 = 3')
equal(summary.particles, 6, '总粒子数 = 6')
equal(lb.progress(draft([[2500, 2500]])).percent, 40, '进度百分比 = 5000/12500 = 40%')
equal(lb.progress(draft([[2500, 2500]])).over, false, '5000 未超上限')
equal(lb.progress(draft([[2500, 2500, 2500, 2500, 2500]])).percent, 100, '12500 → 100%')
equal(lb.progress(draft([[2500, 2500, 2500, 2500, 2500]])).over, false, '12500 不算超限')
equal(lb.planCounts(draft([[1, 2], [3]])).length, 2, 'planCounts 返回箱维度')

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`本地数据层单测全部通过（${passed} 项）。`)
process.exit(0)
