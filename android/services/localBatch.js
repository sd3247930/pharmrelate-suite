/**
 * 本地批次数据层（v1.3.1：多箱包装结构）。
 *
 * 为什么要有这一层：v1.2.x 的手机端是"纯采集终端"——状态机、条码校验、去重、
 * 溢出判定、槽位、核对全在 Windows 服务端。断网就没法工作。
 * v1.3.0 把这一套在本地实现一份（拍板 C1 双模式：本地为默认与兜底，在线时仍以服务端为准）；
 * v1.3.1 再把结构从"单箱扁平"升级为"多箱层级"。
 *
 * 数据结构（v1.3.1，schemaVersion = 2）：
 *   {
 *     localId, deviceId, offline: true, status,
 *     batchNo, produceDate, expireDate,
 *     boxes: [
 *       {
 *         boxIndex: 1, boxCode: '',
 *         reviewConfirmed: false,
 *         cans: [
 *           { canIndex: 1, canCode: '', plannedParticleCount: 2, confirmed: false, particles: ['', ''] }
 *         ]
 *       }
 *     ],
 *     history: { undo: [], redo: [] }, earlyEnd, finishRequested, createdAt, updatedAt
 *   }
 * `particles` 就是槽位数组：下标 = 采集顺序，空串 = 还没扫。**严禁排序**。
 *
 * 三条不可违背的约束（写死在这里，页面不许绕开）：
 *   1. 分层校验：箱号 / 罐号是**自然数**（1~9999，现场就是 1、2、3），
 *      只有粒子码才是 20 位 ASCII 数字 + 前缀 8206233；**不要把 20 位规则套到箱/罐上**；
 *   2. `cascade` 是固定字面量 "1:5:2500"，不随实际箱数、罐数或粒子数变化；
 *   3. 粒子顺序 = 采集原始顺序，**严禁排序**。
 * 另外查重是**分层作用域**的：箱号全批唯一、罐号本箱内唯一、粒子码全批唯一（见 findUsage）。
 *
 * 本文件刻意**不 import 任何东西**（设备指纹等由调用方传入），
 * 这样 Node 单测可以直接把它当 ESM 加载并注入内存 storage —— 见 tests/localBatch.test.mjs。
 */

// ---------------------------------------------------------------------------
// 常量与固定参数
// ---------------------------------------------------------------------------

export const BARCODE_LENGTH = 20

/** 层级由前缀唯一决定（与后端 domain/constants.py 对齐）。 */
export const CODE_PREFIXES = {
	3: '8021761',
	2: '8021762',
	1: '8206233'
}

export const LAYER_LABELS = { 3: '箱', 2: '罐', 1: '粒子' }

export const MIN_BOXES = 1
export const MAX_BOXES = 5
export const MIN_CANS = 1
export const MAX_CANS = 5
export const MIN_PARTICLES_PER_CAN = 1
export const MAX_PARTICLES_PER_CAN = 2500
export const MAX_PARTICLES_PER_BATCH = 12500

/** 数据结构版本：v1.3.0 的单箱数据会在读取时自动迁移成 v2（见 migrateBatch）。 */
export const SCHEMA_VERSION = 2

/** 固定字面量：即使实际只有 1 箱 1 罐 4 粒，导出的 XML 里也必须是这个值。 */
export const CASCADE = '1:5:2500'

/** 13 项固定参数：界面上只读展示，不参与输入。 */
export const FIXED_PARAMS = [
	{ key: 'productCode', label: '产品编码 productCode', value: '9999999' },
	{ key: 'subTypeNo', label: '子类型 subTypeNo', value: '9500000001' },
	{ key: 'cascade', label: '级联 cascade', value: CASCADE },
	{ key: 'packageSpec', label: '包装规格 packageSpec', value: '粒1粒' },
	{ key: 'comment', label: '备注 comment', value: '0' },
	{ key: 'flag', label: '标志 flag', value: '2' },
	{ key: 'workshop', label: '车间 workshop', value: '一号车间' },
	{ key: 'lineName', label: '产线 lineName', value: '一号生产线' },
	{ key: 'lineManager', label: '负责人 lineManager', value: '操作员甲' },
	{ key: 'license', label: '许可证 License', value: '1001123' },
	{
		key: 'schemaLocation',
		label: 'Schema xsi:noNamespaceSchemaLocation',
		value: '关联关系XML Schema-3.0.xsd'
	},
	{ key: 'eventsVersion', label: 'Events Version', value: '3.0' },
	{ key: 'eventName', label: 'Event Name', value: 'RelationCreate' }
]

/** 本地状态机：草稿 → 采集中 → 待核对 → 已核对（手机端本期不产出 XML，故止于已核对）。 */
export const LOCAL_STATUS = {
	DRAFT: 'draft',
	COLLECTING: 'collecting',
	PENDING_REVIEW: 'pending_review',
	VERIFIED: 'verified'
}

export const STATUS_LABELS = {
	draft: '草稿',
	collecting: '采集中',
	pending_review: '待核对',
	verified: '已核对'
}

/** 合法流转表：非法流转一律拒绝（验收要求"明确提示并阻止"）。 */
export const LOCAL_TRANSITIONS = {
	draft: ['collecting'],
	collecting: ['pending_review'],
	pending_review: ['verified'],
	verified: []
}

export const UNDO_LIMIT = 50

/**
 * 向导相位（v1.3.1 多箱）：箱 → 罐 → 粒子 → 本罐核对 → 本箱核对 → 整体核对。
 * 相位不落盘，一律由 boxes 数据推导（deriveWizard），避免状态与数据不一致。
 */
export const PHASE = {
	BOX: 'box',
	CAN: 'can',
	PARTICLE: 'particle',
	CAN_REVIEW: 'can_review',
	BOX_REVIEW: 'box_review',
	REVIEW: 'review'
}

/** 本地事件码：与后端 scan_state 的语义一一对应，便于二期对齐。 */
export const EVENT = {
	OK: 'OK',
	NO_CODE: 'NO_CODE',
	MULTI_CODE: 'MULTI_CODE',
	WRONG_LAYER: 'WRONG_LAYER',
	DUPLICATE_CODE: 'DUPLICATE_CODE',
	OVERFLOW: 'OVERFLOW',
	WRONG_STATE: 'WRONG_STATE'
}

export const EVENT_LABELS = {
	OK: '已识别',
	NO_CODE: '未识别到条码',
	MULTI_CODE: '检测到多个条码',
	WRONG_LAYER: '条码层级不符',
	DUPLICATE_CODE: '条码已被使用',
	OVERFLOW: '超出本罐计划数量',
	WRONG_STATE: '当前步骤不允许该操作'
}

/** 需要震动 + 视觉双重提示的事件（与一期 ALARM_EVENTS 一致）。 */
export const ALARM_EVENTS = [
	EVENT.MULTI_CODE,
	EVENT.WRONG_LAYER,
	EVENT.DUPLICATE_CODE,
	EVENT.OVERFLOW
]

const KEY_BATCHES = 'pharmrelate.local.batches'
const KEY_ACTIVE = 'pharmrelate.local.activeId'

// ---------------------------------------------------------------------------
// 存储适配：默认走 uni.setStorageSync，单测注入内存实现
// ---------------------------------------------------------------------------

let adapter = null

function defaultAdapter() {
	return {
		get(key) {
			return uni.getStorageSync(key)
		},
		set(key, value) {
			uni.setStorageSync(key, value)
		},
		remove(key) {
			uni.removeStorageSync(key)
		}
	}
}

function store() {
	if (!adapter) adapter = defaultAdapter()
	return adapter
}

/** 单测用：替换存储实现（传 null 恢复默认）。 */
export function setStorageAdapter(next) {
	adapter = next
}

// ---------------------------------------------------------------------------
// v1.3.0 → v1.3.1 数据迁移
// ---------------------------------------------------------------------------

/** v1.3.0 的撤销记录是 `{ type, canIndex }`，迁移后补上 boxIndex。 */
function migrateOperation(operation) {
	if (!operation || typeof operation !== 'object') return operation
	if (typeof operation.boxIndex === 'number') return operation
	return Object.assign({}, operation, { boxIndex: 0 })
}

function migrateHistory(history) {
	const source = history && typeof history === 'object' ? history : {}
	const undo = Array.isArray(source.undo) ? source.undo.map(migrateOperation) : []
	const redo = Array.isArray(source.redo) ? source.redo.map(migrateOperation) : []
	return { undo, redo }
}

/**
 * 把 v1.3.0 的单箱批次迁移成 v1.3.1 的多箱结构。
 * 已经是 v2（有 boxes 数组）就原样返回 —— 调用方靠引用比较判断是否需要回写。
 */
export function migrateBatch(batch) {
	if (!batch || typeof batch !== 'object') return batch
	if (Array.isArray(batch.boxes)) return batch

	const legacyPlan = Array.isArray(batch.plannedParticleCounts) ? batch.plannedParticleCounts : []
	const legacyCans = Array.isArray(batch.cans) ? batch.cans : []
	const counts = legacyPlan.length
		? legacyPlan.map((value) => Number(value) || 0)
		: legacyCans.map((can) => Number((can && can.plannedParticleCount) || 0))

	const next = Object.assign({}, batch)
	next.schemaVersion = SCHEMA_VERSION
	next.history = migrateHistory(batch.history)
	if (counts.length) {
		next.boxes = [
			{
				boxIndex: 1,
				boxCode: (batch.box && batch.box.code) || '',
				// 单箱数据只有一个箱子，罐级核对在迁移时必然已完成，否则老数据每次都要多问一次
				reviewConfirmed: true,
				cans: counts.map((count, index) => {
					const legacy = legacyCans[index] || {}
					return {
						canIndex: index + 1,
						canCode: legacy.code || '',
						plannedParticleCount: count,
						confirmed: !!legacy.confirmed,
						particles: Array.isArray(legacy.slots) ? legacy.slots.slice() : new Array(count).fill('')
					}
				})
			}
		]
	} else {
		next.boxes = []
	}
	delete next.box
	delete next.cans
	delete next.plannedParticleCounts
	return next
}

export function loadBatches() {
	const raw = store().get(KEY_BATCHES)
	if (!raw || typeof raw !== 'object') return {}
	let changed = false
	const next = {}
	Object.keys(raw).forEach((key) => {
		const migrated = migrateBatch(raw[key])
		if (migrated !== raw[key]) changed = true
		next[key] = migrated
	})
	if (changed) store().set(KEY_BATCHES, next)
	return next
}

export function saveBatches(batches) {
	store().set(KEY_BATCHES, batches)
}

export function getActiveId() {
	return store().get(KEY_ACTIVE) || ''
}

export function setActiveId(localId) {
	store().set(KEY_ACTIVE, localId || '')
}

export function listBatches() {
	const batches = loadBatches()
	return Object.keys(batches)
		.map((key) => batches[key])
		.sort((a, b) => String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')))
}

export function getActiveBatch() {
	const id = getActiveId()
	if (!id) return null
	const batches = loadBatches()
	return batches[id] || null
}

/** 写入一个批次并把它设为当前批次。 */
export function saveBatch(batch) {
	const batches = loadBatches()
	const next = Object.assign({}, migrateBatch(batch), { updatedAt: nowIso() })
	batches[next.localId] = next
	saveBatches(batches)
	setActiveId(next.localId)
	return next
}

export function removeBatch(localId) {
	const batches = loadBatches()
	delete batches[localId]
	saveBatches(batches)
	if (getActiveId() === localId) setActiveId('')
}

export function clearAll() {
	store().remove(KEY_BATCHES)
	store().remove(KEY_ACTIVE)
}

function nowIso() {
	return new Date().toISOString()
}

function makeLocalId() {
	const stamp = Date.now().toString(36)
	const rand = Math.random().toString(36).slice(2, 8)
	return `LB-${stamp}-${rand}`
}

// ---------------------------------------------------------------------------
// 条码与校验
// ---------------------------------------------------------------------------

/** 层级判定：长度、纯数字、前缀三者都对才算合法，否则返回 null。 */
export function classifyCode(value) {
	const code = String(value == null ? '' : value).trim()
	if (code.length !== BARCODE_LENGTH) return null
	if (!/^\d+$/.test(code)) return null
	const layers = Object.keys(CODE_PREFIXES)
	for (let index = 0; index < layers.length; index += 1) {
		const layer = Number(layers[index])
		if (code.indexOf(CODE_PREFIXES[layer]) === 0) return layer
	}
	return null
}

export function layerLabel(layer) {
	return LAYER_LABELS[layer] || '未知'
}

/** 手动输入提示里用的完整叫法（文档要求「箱号必须为 20 位数字，且前缀为 8021761」）。 */
const LAYER_FULL_LABELS = { 3: '箱号', 2: '罐号', 1: '粒子码' }

/**
 * 分层校验规则（v1.3.2 拍板）：
 *   - 箱号 / 罐号：**自然数**（现场就是 1、2、3 这种），允许前导零，范围 1~9999；
 *   - 粒子码：仍然是 20 位 ASCII 数字 + 前缀 8206233（这条绝对不动）。
 * 早期版本把 20 位条码规则错套在箱/罐上，导致现场录不进「1」——这里是修正点。
 */
export const MAX_NATURAL = 9999
export const NATURAL_PATTERN = /^\d+$/

/** 箱/罐号是否为合法自然数（1~9999，允许前导零，最多 4 位）。 */
export function isNaturalCode(value) {
	const code = String(value == null ? '' : value).trim()
	if (!NATURAL_PATTERN.test(code)) return false
	if (code.length > 4) return false
	const number = Number(code)
	return number >= 1 && number <= MAX_NATURAL
}

/**
 * 层级码格式校验（给「手动输入箱号/罐号」与三条采集通道共用）。
 * 返回空串表示通过；否则返回一句能直接给操作员看的中文提示。
 *
 * 只做格式校验，不查重、不写数据 —— 命中的码仍然要走 applyCodes，
 * 这样状态机与去重逻辑只有一份（避免手动输入绕开既有规则）。
 */
export function validateLayerCode(value, layer) {
	const code = String(value == null ? '' : value).trim()
	const label = LAYER_FULL_LABELS[layer] || '条码'
	if (!CODE_PREFIXES[layer]) return `未知的层级：${layer}`
	if (!code) return `${label}不能为空。`
	if (layer === 3 || layer === 2) {
		if (!isNaturalCode(code)) {
			return `${label}必须是 1~${MAX_NATURAL} 之间的自然数（如 1、2、3），不能含字母、小数或符号。`
		}
		return ''
	}
	const prefix = CODE_PREFIXES[layer]
	if (code.length !== BARCODE_LENGTH || !/^\d+$/.test(code) || code.indexOf(prefix) !== 0) {
		return `${label}必须为 ${BARCODE_LENGTH} 位数字，且前缀为 ${prefix}`
	}
	return ''
}

/**
 * 面向操作员的错误文案：格式不合法时再补一层「误扫了粒子条码」的特判。
 * 返回空串表示通过。
 */
export function describeCodeIssue(value, layer) {
	const issue = validateLayerCode(value, layer)
	if (!issue) return ''
	const code = String(value == null ? '' : value).trim()
	if (layer !== 1 && classifyCode(code) === 1) {
		return `这是粒子条码，${LAYER_FULL_LABELS[layer] || '条码'}只需要自然数（1~${MAX_NATURAL}）。`
	}
	return issue
}

function issue(code, field, message) {
	return { severity: 'error', code, field, message }
}

/** 基础信息校验（阶段 2 的验收点：必填 + 有效期 > 生产日期）。 */
export function validateBaseInfo(input) {
	const issues = []
	const batchNo = String((input && input.batchNo) || '').trim()
	const produceDate = String((input && input.produceDate) || '').trim()
	const expireDate = String((input && input.expireDate) || '').trim()

	if (!batchNo) {
		issues.push(issue('BATCH_NO_REQUIRED', 'batchNo', '批号必填。'))
	}
	if (!produceDate) {
		issues.push(issue('PRODUCE_DATE_REQUIRED', 'produceDate', '生产日期必填。'))
	}
	if (!expireDate) {
		issues.push(issue('EXPIRE_DATE_REQUIRED', 'expireDate', '有效期必填。'))
	}
	if (produceDate && expireDate && expireDate <= produceDate) {
		issues.push(issue('EXPIRE_NOT_AFTER_PRODUCE', 'expireDate', '有效期必须大于生产日期。'))
	}
	return issues
}

/**
 * 包装结构校验（阶段 3 的验收点）。
 * 入参是**箱 → 罐**的二维数组，例如 `[[2, 2, 2], [1, 1]]`：
 *   箱数 1~5；每箱罐数各自独立 1~5；每罐 1~2500；单批总数 ≤ 12500（硬上限，方案 A）。
 */
export function validateStructure(boxCounts) {
	const issues = []
	const boxes = Array.isArray(boxCounts) ? boxCounts : []
	if (boxes.length < MIN_BOXES || boxes.length > MAX_BOXES) {
		issues.push(issue('BOX_COUNT_RANGE', 'boxes', `纸箱数必须在 ${MIN_BOXES}～${MAX_BOXES} 之间`))
		return issues
	}
	let total = 0
	boxes.forEach((counts, boxIndex) => {
		const list = Array.isArray(counts) ? counts : []
		if (list.length < MIN_CANS || list.length > MAX_CANS) {
			issues.push(
				issue(
					'CAN_COUNT_RANGE',
					`box${boxIndex + 1}`,
					`箱 ${boxIndex + 1} 的罐数必须在 ${MIN_CANS}～${MAX_CANS} 之间`
				)
			)
			return
		}
		list.forEach((value, canIndex) => {
			const count = Number(value)
			const where = `箱 ${boxIndex + 1} 罐 ${canIndex + 1}`
			if (!Number.isFinite(count) || Math.trunc(count) !== count) {
				issues.push(issue('PARTICLE_NOT_INTEGER', `box${boxIndex + 1}Can${canIndex + 1}`, `${where} 的粒子数必须是整数。`))
				return
			}
			if (count < MIN_PARTICLES_PER_CAN) {
				issues.push(
					issue('PARTICLE_TOO_SMALL', `box${boxIndex + 1}Can${canIndex + 1}`, `${where} 的粒子数至少 ${MIN_PARTICLES_PER_CAN} 粒。`)
				)
				return
			}
			if (count > MAX_PARTICLES_PER_CAN) {
				issues.push(
					issue(
						'PARTICLE_TOO_MANY',
						`box${boxIndex + 1}Can${canIndex + 1}`,
						`${where} 的粒子数不得超过 ${MAX_PARTICLES_PER_CAN} 粒。`
					)
				)
				return
			}
			total += count
		})
	})
	if (total > MAX_PARTICLES_PER_BATCH) {
		issues.push(
			issue('BATCH_LIMIT_EXCEEDED', 'boxes', `单批粒子总数不得超过 ${MAX_PARTICLES_PER_BATCH} 粒（当前 ${total}）。`)
		)
	}
	return issues
}

/** 求和：兼容一维（单箱）与二维（多箱）数组。 */
export function particleTotal(counts) {
	return (Array.isArray(counts) ? counts : []).reduce((sum, value) => {
		if (Array.isArray(value)) return sum + particleTotal(value)
		return sum + (Number(value) || 0)
	}, 0)
}

/** 从 boxes 推导「箱 → 罐」的计划矩阵（单一数据源，避免两处各存一份对不上）。 */
export function planCounts(batch) {
	return (batch && batch.boxes ? batch.boxes : []).map((box) =>
		(box.cans || []).map((can) => Number(can.plannedParticleCount) || 0)
	)
}

export function planSummary(batch) {
	const counts = planCounts(batch)
	const boxes = counts.length
	const cans = counts.reduce((sum, list) => sum + list.length, 0)
	const particles = particleTotal(counts)
	return { boxes, cans, particles }
}

export function progress(batch) {
	const total = planSummary(batch).particles
	return {
		total,
		percent: Math.min(100, Math.round((total / MAX_PARTICLES_PER_BATCH) * 1000) / 10),
		over: total > MAX_PARTICLES_PER_BATCH
	}
}

// ---------------------------------------------------------------------------
// 批次：建档 / 配结构
// ---------------------------------------------------------------------------

function clone(value) {
	return JSON.parse(JSON.stringify(value))
}

function touch(batch) {
	const next = clone(batch)
	next.updatedAt = nowIso()
	return next
}

function eventOf(code, message, detail) {
	return {
		code,
		label: EVENT_LABELS[code] || code,
		message: message || EVENT_LABELS[code] || code,
		needsAlarm: ALARM_EVENTS.indexOf(code) >= 0,
		detail: detail || {}
	}
}

/**
 * 新建本地批次（草稿）。
 * `deviceId` 由调用方从 services/store.js 取设备指纹传进来（拍板 C4）。
 */
export function createDraft(input) {
	const stamp = nowIso()
	return {
		localId: makeLocalId(),
		schemaVersion: SCHEMA_VERSION,
		deviceId: (input && input.deviceId) || '',
		offline: true,
		status: LOCAL_STATUS.DRAFT,
		batchNo: String((input && input.batchNo) || '').trim(),
		produceDate: String((input && input.produceDate) || '').trim(),
		expireDate: String((input && input.expireDate) || '').trim(),
		boxes: [],
		history: { undo: [], redo: [] },
		earlyEnd: null,
		finishRequested: false,
		createdAt: stamp,
		updatedAt: stamp
	}
}

/** 保存基础信息（保留已采集的数据，只在草稿态允许改）。 */
export function updateBaseInfo(batch, input) {
	if (batch.status !== LOCAL_STATUS.DRAFT) {
		return { batch, event: eventOf(EVENT.WRONG_STATE, `批次已进入「${STATUS_LABELS[batch.status]}」，基础信息只读。`) }
	}
	const issues = validateBaseInfo(input)
	if (issues.length) {
		return { batch, issues, event: eventOf(EVENT.WRONG_STATE, issues[0].message) }
	}
	const next = clone(batch)
	next.batchNo = String(input.batchNo).trim()
	next.produceDate = String(input.produceDate).trim()
	next.expireDate = String(input.expireDate).trim()
	return { batch: touch(next), issues: [] }
}

/** 按「箱 → 罐」生成空白结构（每罐都是空槽位）。 */
export function buildBoxes(boxCounts) {
	return (Array.isArray(boxCounts) ? boxCounts : []).map((counts, boxIndex) => ({
		boxIndex: boxIndex + 1,
		boxCode: '',
		reviewConfirmed: false,
		cans: (Array.isArray(counts) ? counts : []).map((count, canIndex) => ({
			canIndex: canIndex + 1,
			canCode: '',
			plannedParticleCount: Number(count),
			confirmed: false,
			particles: new Array(Number(count)).fill('')
		}))
	}))
}

/**
 * 保存包装结构 → 状态置「采集中」，返回新批次。
 * 已经在采集的批次不允许改结构（改了会让已扫的槽位失去意义）。
 */
export function saveStructure(batch, boxCounts) {
	if (batch.status !== LOCAL_STATUS.DRAFT) {
		return { batch, issues: [], event: eventOf(EVENT.WRONG_STATE, '已经开始采集，包装结构不可再改。') }
	}
	const issues = validateStructure(boxCounts)
	if (issues.length) {
		return { batch, issues, event: eventOf(EVENT.WRONG_STATE, issues[0].message) }
	}
	const next = clone(batch)
	next.boxes = buildBoxes(boxCounts)
	next.status = LOCAL_STATUS.COLLECTING
	return { batch: touch(next), issues: [] }
}

/** 状态流转（非法流转一律拒绝）。 */
export function transition(batch, target) {
	const allowed = LOCAL_TRANSITIONS[batch.status] || []
	if (allowed.indexOf(target) < 0) {
		return {
			batch,
			allowed,
			event: eventOf(
				EVENT.WRONG_STATE,
				`不能从「${STATUS_LABELS[batch.status] || batch.status}」直接跳到「${STATUS_LABELS[target] || target}」。允许：${allowed
					.map((item) => STATUS_LABELS[item] || item)
					.join('、') || '（无）'}`
			)
		}
	}
	const next = clone(batch)
	next.status = target
	return { batch: touch(next), allowed: LOCAL_TRANSITIONS[target] || [] }
}

// ---------------------------------------------------------------------------
// 向导：状态一律从数据推导（不另存一份，避免与数据不一致）
// ---------------------------------------------------------------------------

function filledCount(can) {
	return (can.particles || []).filter((code) => !!code).length
}

/** 取某个箱子里的某罐（都传 1 起的序号）。找不到返回 null。 */
export function findCan(batch, boxIndex, canIndex) {
	const box = (batch.boxes || [])[boxIndex - 1]
	if (!box) return null
	return (box.cans || [])[canIndex - 1] || null
}

function wizardState(base, extra) {
	return Object.assign({}, base, extra)
}

/**
 * 从数据推导当前步骤与相位（不能跳步）。
 * 相位序列：box → can → particle → can_review → box_review →（下一箱 | review）。
 */
export function deriveWizard(batch) {
	const boxes = (batch && batch.boxes) || []
	const counts = planCounts(batch)
	const totalBoxes = boxes.length
	const totalCans = counts.reduce((sum, list) => sum + list.length, 0)
	const base = {
		totalBoxes,
		totalCans,
		plannedParticles: particleTotal(counts),
		actualBoxes: 0,
		actualCans: 0,
		actualParticles: 0,
		boxIndex: 1,
		canIndex: 1,
		cansInBox: counts.length ? counts[0].length : 0,
		isLastBox: totalBoxes <= 1
	}

	if (!totalBoxes) {
		return wizardState(base, {
			step: 1,
			phase: PHASE.BOX,
			prompt: '还没有包装结构，请先到「设置」配置纸箱数与罐数。'
		})
	}

	const finished = !!(batch.finishRequested || batch.earlyEnd)

	for (let b = 0; b < totalBoxes; b += 1) {
		const box = boxes[b]
		const cans = box.cans || []
		if (box.boxCode) base.actualBoxes += 1
		for (let c = 0; c < cans.length; c += 1) {
			const can = cans[c]
			if (can.canCode) base.actualCans += 1
			base.actualParticles += filledCount(can)
		}
		if (finished) continue

		const where = { boxIndex: b + 1, cansInBox: cans.length, isLastBox: b === totalBoxes - 1 }

		if (!box.boxCode) {
			return wizardState(base, {
				step: 1,
				phase: PHASE.BOX,
				...where,
				prompt: `请拍摄/输入箱号（第 ${b + 1} 箱 / 共 ${totalBoxes} 箱，自然数 1~${MAX_NATURAL}）`
			})
		}

		for (let c = 0; c < cans.length; c += 1) {
			const can = cans[c]
			const canIndex = c + 1
			if (!can.canCode) {
				return wizardState(base, {
					step: 2,
					phase: PHASE.CAN,
					...where,
					canIndex,
					prompt: `请拍摄/输入箱 ${b + 1} 罐 ${canIndex} 号（自然数 1~${MAX_NATURAL}）`
				})
			}
			const filled = filledCount(can)
			if (filled < can.plannedParticleCount) {
				return wizardState(base, {
					step: 2,
					phase: PHASE.PARTICLE,
					...where,
					canIndex,
					prompt: `请扫描箱 ${b + 1} 罐 ${canIndex} 的粒子（${filled}/${can.plannedParticleCount}，前缀 8206233）`
				})
			}
			if (!can.confirmed) {
				return wizardState(base, {
					step: 2,
					phase: PHASE.CAN_REVIEW,
					...where,
					canIndex,
					prompt: `箱 ${b + 1} 罐 ${canIndex} 已扫满 ${can.plannedParticleCount} 粒，请核对`
				})
			}
		}

		if (!box.reviewConfirmed) {
			return wizardState(base, {
				step: 2,
				phase: PHASE.BOX_REVIEW,
				...where,
				canIndex: cans.length,
				prompt:
					b === totalBoxes - 1
						? `箱 ${b + 1}（最后一箱）已完成 ${cans.length} 罐，请进行整体核对`
						: `箱 ${b + 1} 已完成 ${cans.length} 罐，是否继续拍下一箱？`
			})
		}
	}

	return wizardState(base, {
		step: 3,
		phase: PHASE.REVIEW,
		boxIndex: totalBoxes,
		canIndex: counts[totalBoxes - 1].length,
		cansInBox: counts[totalBoxes - 1].length,
		isLastBox: true,
		prompt: finished ? '已结束剩余拍摄，请进行整体核对' : '所有箱已完成，请进行整体核对'
	})
}

/**
 * 分层作用域查重（v1.3.2 拍板）：
 *   - 箱号（layer 3）：**全批唯一** —— 同一批里两箱不能叫同一个号；
 *   - 罐号（layer 2）：**本箱内唯一** —— 箱 1 的罐 1 与箱 2 的罐 1 都是合法的「1」；
 *   - 粒子码（layer 1）：**全批唯一** —— 20 位条码是物理唯一的。
 *
 * 为什么必须分层：箱/罐改成自然数后，「1」这种值天然会在不同层级重复出现，
 * 再用全批不分层级查重会把「箱 1 + 罐 1」判成重复，直接录不进去。
 *
 * context（都是 0 起的索引）：
 *   - excludeBoxIndex：查箱号时跳过自己（改号场景）
 *   - boxIndex：查罐号时限定在哪一箱
 *   - excludeCanIndex：查罐号时跳过自己
 */
export function findUsage(batch, code, layer, context) {
	const value = String(code == null ? '' : code).trim()
	const boxes = (batch && batch.boxes) || []
	const scope = context || {}

	if (layer === 3) {
		for (let b = 0; b < boxes.length; b += 1) {
			if (b === scope.excludeBoxIndex) continue
			if (boxes[b].boxCode === value) {
				return { where: `箱 ${b + 1} 号`, layer: 3, boxIndex: b + 1, canIndex: 0 }
			}
		}
		return null
	}

	if (layer === 2) {
		const b = Number.isFinite(scope.boxIndex) ? Number(scope.boxIndex) : 0
		const box = boxes[b]
		if (!box) return null
		const cans = box.cans || []
		for (let c = 0; c < cans.length; c += 1) {
			if (c === scope.excludeCanIndex) continue
			if (cans[c].canCode === value) {
				return { where: `箱 ${b + 1} 罐 ${c + 1} 号`, layer: 2, boxIndex: b + 1, canIndex: c + 1 }
			}
		}
		return null
	}

	if (layer === 1) {
		for (let b = 0; b < boxes.length; b += 1) {
			const cans = boxes[b].cans || []
			for (let c = 0; c < cans.length; c += 1) {
				const slotIndex = (cans[c].particles || []).indexOf(value)
				if (slotIndex >= 0) {
					return {
						where: `箱 ${b + 1} 罐 ${c + 1} / 槽位 ${slotIndex + 1}`,
						layer: 1,
						boxIndex: b + 1,
						canIndex: c + 1
					}
				}
			}
		}
		return null
	}

	// 未指定层级：按 箱 → 罐 → 粒子 全查（兼容旧调用，新代码请显式传 layer）
	for (let b = 0; b < boxes.length; b += 1) {
		const box = boxes[b]
		if (box.boxCode === value) return { where: `箱 ${b + 1} 号`, layer: 3, boxIndex: b + 1, canIndex: 0 }
		const cans = box.cans || []
		for (let c = 0; c < cans.length; c += 1) {
			const can = cans[c]
			if (can.canCode === value) {
				return { where: `箱 ${b + 1} 罐 ${c + 1} 号`, layer: 2, boxIndex: b + 1, canIndex: c + 1 }
			}
			const slotIndex = (can.particles || []).indexOf(value)
			if (slotIndex >= 0) {
				return { where: `箱 ${b + 1} 罐 ${c + 1} / 槽位 ${slotIndex + 1}`, layer: 1, boxIndex: b + 1, canIndex: c + 1 }
			}
		}
	}
	return null
}

/**
 * 把一次识别结果应用到本地批次（本地状态机的核心）。
 * 返回 `{ batch, event }`：event.code 为 OK 表示写入成功，其余为被拦截的原因。
 */
export function applyCodes(batch, codes) {
	const list = (Array.isArray(codes) ? codes : [codes])
		.map((value) => String(value == null ? '' : value).trim())
		.filter(Boolean)
	if (!list.length) {
		return { batch, event: eventOf(EVENT.NO_CODE, '没有识别到条码，请重新拍摄。') }
	}

	const wizard = deriveWizard(batch)

	if (wizard.phase === PHASE.BOX || wizard.phase === PHASE.CAN) {
		const expectedLayer = wizard.phase === PHASE.BOX ? 3 : 2
		if (list.length > 1) {
			return {
				batch,
				event: eventOf(
					EVENT.MULTI_CODE,
					`一次识别到 ${list.length} 个号码；拍摄${layerLabel(expectedLayer)}号时只能有一个，请重拍。`,
					{ detected: list }
				)
			}
		}
		const code = list[0]
		// 箱/罐走自然数校验（不再用 20 位条码规则）；粒子码另有自己的分支
		const issueMessage = describeCodeIssue(code, expectedLayer)
		if (issueMessage) {
			return {
				batch,
				event: eventOf(EVENT.WRONG_LAYER, issueMessage, {
					code,
					expectedLayer,
					scannedLayer: classifyCode(code)
				})
			}
		}
		// 分层作用域查重：箱号全批唯一，罐号本箱内唯一
		const used =
			wizard.phase === PHASE.BOX
				? findUsage(batch, code, 3, { excludeBoxIndex: wizard.boxIndex - 1 })
				: findUsage(batch, code, 2, { boxIndex: wizard.boxIndex - 1, excludeCanIndex: wizard.canIndex - 1 })
		if (used) {
			return {
				batch,
				event: eventOf(
					EVENT.DUPLICATE_CODE,
					`${LAYER_FULL_LABELS[expectedLayer] || '条码'} ${code} 已被使用于「${used.where}」，请勿重复录入。`,
					used
				)
			}
		}
		const next = clone(batch)
		if (wizard.phase === PHASE.BOX) {
			next.boxes[wizard.boxIndex - 1].boxCode = code
		} else {
			next.boxes[wizard.boxIndex - 1].cans[wizard.canIndex - 1].canCode = code
		}
		return {
			batch: touch(next),
			event: eventOf(
				EVENT.OK,
				wizard.phase === PHASE.BOX
					? `已记录箱 ${wizard.boxIndex} 的箱号 ${code}。`
					: `已记录箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 号 ${code}。`
			)
		}
	}

	if (wizard.phase === PHASE.PARTICLE) {
		const can = findCan(batch, wizard.boxIndex, wizard.canIndex)
		const wrong = list.filter((code) => classifyCode(code) !== 1)
		if (wrong.length) {
			return {
				batch,
				event: eventOf(
					EVENT.WRONG_LAYER,
					`条码 ${wrong[0]} 是「${layerLabel(classifyCode(wrong[0]))}」，粒子扫描只接受粒子码。`,
					{ code: wrong[0], expectedLayer: 1 }
				)
			}
		}
		const seen = {}
		const duplicates = []
		list.forEach((code) => {
			if (seen[code] && duplicates.indexOf(code) < 0) duplicates.push(code)
			seen[code] = true
		})
		if (duplicates.length) {
			return {
				batch,
				event: eventOf(EVENT.DUPLICATE_CODE, `本次识别中有 ${duplicates.length} 个条码重复出现，请检查后重扫。`, { duplicates })
			}
		}
		const usedInBatch = list.filter((code) => findUsage(batch, code, 1))
		if (usedInBatch.length) {
			const used = findUsage(batch, usedInBatch[0], 1)
			return {
				batch,
				event: eventOf(EVENT.DUPLICATE_CODE, `条码 ${usedInBatch[0]} 已被使用于「${used.where}」。`, used)
			}
		}
		const filled = filledCount(can)
		const remaining = can.plannedParticleCount - filled
		if (list.length > remaining) {
			return {
				batch,
				event: eventOf(
					EVENT.OVERFLOW,
					`箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 只差 ${remaining} 粒，本次识别到 ${list.length} 个，整帧不写入。请重扫或先删掉多余槽位。`,
					{ boxIndex: wizard.boxIndex, canIndex: wizard.canIndex, remaining, detected: list.length }
				)
			}
		}
		const next = clone(batch)
		const target = next.boxes[wizard.boxIndex - 1].cans[wizard.canIndex - 1]
		// 顺序写入：**不排序**，识别顺序就是最终顺序
		const entries = []
		list.forEach((code) => {
			let emptyIndex = target.particles.indexOf('')
			if (emptyIndex < 0) {
				target.particles.push(code)
				emptyIndex = target.particles.length - 1
			} else {
				target.particles[emptyIndex] = code
			}
			entries.push({ index: emptyIndex, code })
		})
		pushOperation(next, {
			type: 'fill',
			boxIndex: wizard.boxIndex - 1,
			canIndex: wizard.canIndex - 1,
			entries
		})
		const after = filledCount(target)
		const where = `箱 ${wizard.boxIndex} 罐 ${wizard.canIndex}`
		return {
			batch: touch(next),
			event: eventOf(
				EVENT.OK,
				after >= target.plannedParticleCount
					? `${where} 已扫满 ${after} 粒，请核对。`
					: `本次加入 ${list.length} 粒，${where} 进度 ${after}/${target.plannedParticleCount}。`
			)
		}
	}

	return {
		batch,
		event: eventOf(EVENT.WRONG_STATE, `当前步骤是「${wizard.prompt}」，不接受新的识别结果。`)
	}
}

/** 本罐核对：确认无误 → 标记已确认；还没好 → 保持在本罐（可删/换槽位后再扫）。 */
export function confirmCanReview(batch, done) {
	const wizard = deriveWizard(batch)
	if (wizard.phase !== PHASE.CAN_REVIEW) {
		return { batch, event: eventOf(EVENT.WRONG_STATE, '当前不在本罐核对步骤。') }
	}
	if (!done) {
		return { batch, event: eventOf(EVENT.OK, '可以删除或替换槽位后继续扫描（粒子顺序不会被重排）。') }
	}
	const next = clone(batch)
	next.boxes[wizard.boxIndex - 1].cans[wizard.canIndex - 1].confirmed = true
	return { batch: touch(next), event: eventOf(EVENT.OK, `箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 已确认。`) }
}

/** 本箱核对：确认无误 → 标记本箱完成，向导进入下一箱；还没好 → 留在本箱。 */
export function confirmBoxReview(batch, done) {
	const wizard = deriveWizard(batch)
	if (wizard.phase !== PHASE.BOX_REVIEW) {
		return { batch, event: eventOf(EVENT.WRONG_STATE, '当前不在本箱核对步骤。') }
	}
	if (!done) {
		return { batch, event: eventOf(EVENT.OK, '可以回到本箱补拍或修改槽位（粒子顺序不会被重排）。') }
	}
	const next = clone(batch)
	next.boxes[wizard.boxIndex - 1].reviewConfirmed = true
	return { batch: touch(next), event: eventOf(EVENT.OK, `箱 ${wizard.boxIndex} 已确认完成。`) }
}

/**
 * 提前结束（拍板决策 4：**从当前箱当前罐起，剩余全部不再拍**，整批终止）。
 * 置 finishRequested，向导直接进入整体核对；缺漏会如实显示，需到状态页签名。
 */
export function finishRemaining(batch) {
	const next = clone(batch)
	next.finishRequested = true
	return { batch: touch(next), event: eventOf(EVENT.OK, '已结束剩余箱/罐的拍摄，请到状态页处理缺漏与签名。') }
}

/** 提前结束签名（原因 + 操作人必填，实际数量由数据算，不接受外部传入）。 */
export function registerEarlyEnd(batch, input) {
	const reason = String((input && input.reason) || '').trim()
	const operator = String((input && input.operator) || '').trim()
	const note = String((input && input.note) || '').trim()
	if (!reason || !operator) {
		return { batch, event: eventOf(EVENT.WRONG_STATE, '提前结束必须填写原因与操作人。') }
	}
	const wizard = deriveWizard(batch)
	const next = clone(batch)
	next.earlyEnd = {
		reason,
		operator,
		note,
		at: nowIso(),
		actualBoxCount: wizard.actualBoxes,
		actualCanCount: wizard.actualCans,
		actualParticleTotal: wizard.actualParticles
	}
	return { batch: touch(next), event: eventOf(EVENT.OK, `已登记提前结束（${operator}）。`) }
}

export function clearEarlyEnd(batch) {
	const next = clone(batch)
	next.earlyEnd = null
	return { batch: touch(next) }
}

// ---------------------------------------------------------------------------
// 槽位编辑与撤销栈（最多 50 步，超出自动丢弃最旧记录）
// ---------------------------------------------------------------------------

function history(batch) {
	if (!batch.history) batch.history = { undo: [], redo: [] }
	if (!Array.isArray(batch.history.undo)) batch.history.undo = []
	if (!Array.isArray(batch.history.redo)) batch.history.redo = []
	return batch.history
}

function pushOperation(batch, operation) {
	const log = history(batch)
	log.undo.push(operation)
	if (log.undo.length > UNDO_LIMIT) log.undo.splice(0, log.undo.length - UNDO_LIMIT)
	// 新操作让"重做"失效（标准撤销语义）
	log.redo = []
}

function operationWhere(operation) {
	return `箱 ${Number(operation.boxIndex || 0) + 1} 罐 ${Number(operation.canIndex || 0) + 1}`
}

function describeOperation(operation) {
	if (operation.type === 'fill') return `${operationWhere(operation)} 录入 ${operation.entries.length} 粒`
	if (operation.type === 'replace') return `${operationWhere(operation)} 槽位 ${operation.slotIndex + 1} 替换`
	if (operation.type === 'delete') return `${operationWhere(operation)} 槽位 ${operation.slotIndex + 1} 删除`
	return operation.type
}

function applyOperation(batch, operation, direction) {
	const box = (batch.boxes || [])[operation.boxIndex]
	if (!box) return
	const can = (box.cans || [])[operation.canIndex]
	if (!can) return
	const forward = direction === 'redo'
	if (operation.type === 'fill') {
		operation.entries.forEach((entry) => {
			can.particles[entry.index] = forward ? entry.code : ''
		})
		return
	}
	if (operation.type === 'replace') {
		can.particles[operation.slotIndex] = forward ? operation.to : operation.from
		return
	}
	if (operation.type === 'delete') {
		can.particles[operation.slotIndex] = forward ? '' : operation.code
	}
}

/** 替换槽位（校验层级 + 全批去重，顺序不变）。boxIndex / canIndex / slotIndex 均为 0 起。 */
export function replaceSlot(batch, boxIndex, canIndex, slotIndex, newCode) {
	const code = String(newCode == null ? '' : newCode).trim()
	const can = findCan(batch, Number(boxIndex) + 1, Number(canIndex) + 1)
	if (!can) return { batch, event: eventOf(EVENT.WRONG_STATE, '该罐不存在。') }
	const layer = classifyCode(code)
	if (layer !== 1) {
		return {
			batch,
			event: eventOf(EVENT.WRONG_LAYER, `条码 ${code || '（空）'} 不是有效的粒子码（需 20 位、前缀 8206233）。`)
		}
	}
	if (can.particles[slotIndex] === code) {
		return { batch, event: eventOf(EVENT.OK, '与现有条码相同，无需替换。') }
	}
	const used = findUsage(batch, code, 1)
	if (used) {
		return { batch, event: eventOf(EVENT.DUPLICATE_CODE, `条码 ${code} 已被使用于「${used.where}」。`) }
	}
	const from = can.particles[slotIndex] || ''
	if (!from) return { batch, event: eventOf(EVENT.WRONG_STATE, '该槽位还是空的，直接扫描即可。') }
	const next = clone(batch)
	next.boxes[boxIndex].cans[canIndex].particles[slotIndex] = code
	pushOperation(next, { type: 'replace', boxIndex, canIndex, slotIndex, from, to: code })
	return {
		batch: touch(next),
		event: eventOf(EVENT.OK, `箱 ${Number(boxIndex) + 1} 罐 ${Number(canIndex) + 1} 槽位 ${slotIndex + 1} 已替换为 ${code}。`)
	}
}

/** 删除槽位（置空，位置保留 —— 顺序与缺漏位置都还能看出来）。 */
export function deleteSlot(batch, boxIndex, canIndex, slotIndex) {
	const can = findCan(batch, Number(boxIndex) + 1, Number(canIndex) + 1)
	if (!can) return { batch, event: eventOf(EVENT.WRONG_STATE, '该罐不存在。') }
	const code = can.particles[slotIndex] || ''
	if (!code) return { batch, event: eventOf(EVENT.WRONG_STATE, '该槽位本来就是空的。') }
	const next = clone(batch)
	next.boxes[boxIndex].cans[canIndex].particles[slotIndex] = ''
	pushOperation(next, { type: 'delete', boxIndex, canIndex, slotIndex, code })
	return {
		batch: touch(next),
		event: eventOf(EVENT.OK, `已删除箱 ${Number(boxIndex) + 1} 罐 ${Number(canIndex) + 1} 槽位 ${slotIndex + 1} 的条码。`)
	}
}

export function undo(batch) {
	const log = history(batch)
	const operation = log.undo[log.undo.length - 1]
	if (!operation) return { batch, event: eventOf(EVENT.WRONG_STATE, '没有可撤销的操作。') }
	const next = clone(batch)
	applyOperation(next, operation, 'undo')
	next.history.undo.pop()
	next.history.redo.push(operation)
	return { batch: touch(next), event: eventOf(EVENT.OK, `已撤销：${describeOperation(operation)}`) }
}

export function redo(batch) {
	const log = history(batch)
	const operation = log.redo[log.redo.length - 1]
	if (!operation) return { batch, event: eventOf(EVENT.WRONG_STATE, '没有可重做的操作。') }
	const next = clone(batch)
	applyOperation(next, operation, 'redo')
	next.history.redo.pop()
	next.history.undo.push(operation)
	return { batch: touch(next), event: eventOf(EVENT.OK, `已重做：${describeOperation(operation)}`) }
}

export function historyState(batch) {
	const log = history(batch)
	return {
		canUndo: log.undo.length > 0,
		canRedo: log.redo.length > 0,
		undoCount: log.undo.length,
		redoCount: log.redo.length,
		limit: UNDO_LIMIT
	}
}

// ---------------------------------------------------------------------------
// 本地核对（状态页）
// ---------------------------------------------------------------------------

/**
 * 五项检查（与文档 §五 的清单一一对应），全部按「箱 index + 罐 index」双坐标汇总。
 * 「箱数一致」不单列一项：它由第 5 项（箱号/罐号/粒子码未缺漏）覆盖
 * —— 少一箱就必然缺箱号；整体核对的对照表里仍有独立的「箱」一行。
 */
export function review(batch) {
	const boxes = batch.boxes || []

	const perBox = boxes.map((box, bIndex) => {
		const cans = box.cans || []
		const plannedParticles = cans.reduce((sum, can) => sum + (Number(can.plannedParticleCount) || 0), 0)
		const scannedCans = cans.filter((can) => !!can.canCode).length
		const scannedParticles = cans.reduce((sum, can) => sum + filledCount(can), 0)
		return {
			boxIndex: bIndex + 1,
			boxCode: box.boxCode || '',
			plannedCans: cans.length,
			scannedCans,
			plannedParticles,
			scannedParticles,
			missing: Math.max(0, plannedParticles - scannedParticles),
			complete:
				!!box.boxCode &&
				cans.length > 0 &&
				cans.every((can) => !!can.canCode && filledCount(can) >= Number(can.plannedParticleCount))
		}
	})

	const perCan = []
	boxes.forEach((box, bIndex) => {
		;(box.cans || []).forEach((can, cIndex) => {
			const planned = Number(can.plannedParticleCount) || 0
			const scanned = filledCount(can)
			perCan.push({
				boxIndex: bIndex + 1,
				canIndex: cIndex + 1,
				canCode: can.canCode || '',
				planned,
				scanned,
				missing: Math.max(0, planned - scanned),
				complete: !!can.canCode && scanned >= planned
			})
		})
	})

	const planBoxes = perBox.length
	const planCans = perCan.length
	const planParticles = perCan.reduce((sum, row) => sum + row.planned, 0)
	const actualBoxes = perBox.filter((row) => !!row.boxCode).length
	const actualCans = perCan.filter((row) => !!row.canCode).length
	const actualParticles = perCan.reduce((sum, row) => sum + row.scanned, 0)
	const missingParticles = Math.max(0, planParticles - actualParticles)
	const earlyEnd = batch.earlyEnd || null

	const checks = [
		{
			code: 'CAN_COUNT_MATCHES',
			label: '罐数一致',
			passed: actualCans === planCans,
			detail: `计划 ${planBoxes} 箱 ${planCans} 罐，实际识别 ${actualBoxes} 箱 ${actualCans} 罐`
		},
		{
			code: 'PARTICLE_TOTAL_MATCHES',
			label: '粒子总数一致',
			passed: actualParticles === planParticles,
			detail: `计划 ${planParticles} 粒，实际 ${actualParticles} 粒`
		},
		{
			code: 'BATCH_LIMIT_OK',
			label: `粒子总数不超 ${MAX_PARTICLES_PER_BATCH}`,
			passed: planParticles <= MAX_PARTICLES_PER_BATCH,
			detail: `计划 ${planParticles} 粒 / 上限 ${MAX_PARTICLES_PER_BATCH} 粒`
		},
		{
			code: 'PER_CAN_LIMIT_OK',
			label: `每罐粒子数不超 ${MAX_PARTICLES_PER_CAN}`,
			passed: perCan.every((row) => row.planned <= MAX_PARTICLES_PER_CAN),
			detail:
				perBox
					.map(
						(row, index) =>
							`箱${index + 1} ${(boxes[index].cans || []).map((can) => can.plannedParticleCount).join('/')}`
					)
					.join(' · ') || '（未配置结构）'
		},
		{
			code: 'CODES_COMPLETE',
			label: '箱号 / 罐号 / 粒子码未缺漏',
			passed: planBoxes > 0 && perBox.every((row) => row.complete),
			detail:
				planBoxes === 0
					? '包装结构未配置'
					: missingParticles > 0
						? `缺 ${missingParticles} 粒（箱 ${perBox.filter((row) => !row.complete).map((row) => row.boxIndex).join('、')}）`
						: '箱号、罐号与全部槽位均已采集'
		}
	]

	const blocking = checks.filter((item) => !item.passed)
	return {
		localId: batch.localId,
		batchNo: batch.batchNo,
		deviceId: batch.deviceId || '',
		status: batch.status,
		statusLabel: STATUS_LABELS[batch.status] || batch.status,
		boxCodes: perBox.map((row) => row.boxCode),
		plan: { boxCount: planBoxes, canCount: planCans, particleTotal: planParticles },
		actual: { boxCount: actualBoxes, canCount: actualCans, particleTotal: actualParticles },
		missingParticles,
		perBox,
		perCan,
		checks,
		blocking,
		earlyEnd,
		/** 缺漏时，只有办了提前结束签名才允许确认核对（与一期 A-06 的闸门语义一致）。 */
		canVerify: blocking.length === 0 || !!earlyEnd,
		offline: true
	}
}
