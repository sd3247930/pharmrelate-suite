/**
 * 粒子码手动录入的解析层（纯函数，可在 PC 上单测）。
 *
 * 现场问题（2026-10-02 拍板要做的事）：
 *   粒子码标准形态是 20 位 = 固定前缀 `8206233` + 13 位序列号，但标签上操作员
 *   真正要照着念/敲的往往只有那 13 位序列号。让操作员手打 20 位既慢又容易错位，
 *   所以这里统一约定：
 *
 *   1. 恰好 13 位纯数字  → 自动补前缀，得到完整 20 位；
 *   2. 恰好 20 位纯数字  → 若前缀正确则原样保留（**绝不重复加前缀**）；
 *   3. 27 位且前缀写了两遍 → 去掉多余的那一遍前缀（现场确实会有人把前缀敲两遍）；
 *   4. 其它长度 / 前缀不对 / 含非数字 → 明确判非法。
 *
 * **不猜测、不补位**：不做 `O→0`、`l→1` 这类模糊字符映射，也不给缺失位补 0 ——
 * 那会把错码洗成"看起来合法"的码写进库里（与 `localBatch.extractDigits` 同一口径）。
 *
 * 这个模块刻意不 import 任何东西：依赖越少越好测、也好被将来的 OCR 清洗器复用。
 * 前缀常量与 `localBatch.CODE_PREFIXES[1]` 的一致性由单测锁定（见
 * tests/particleInput.test.mjs），两边不会悄悄漂移。
 */

/** 粒子层固定前缀（必须与 localBatch.CODE_PREFIXES[1] 一致，单测锁定）。 */
export const PARTICLE_PREFIX = '8206233'

/** 完整粒子码位数（必须与 localBatch.BARCODE_LENGTH 一致，单测锁定）。 */
export const PARTICLE_CODE_LENGTH = 20

/** 短码位数 = 完整位数 − 前缀位数 = 13。 */
export const PARTICLE_SHORT_LENGTH = PARTICLE_CODE_LENGTH - PARTICLE_PREFIX.length

/** 批量录入支持的分隔符：空白（含 Tab/换行）、中英文逗号、中英文分号、顿号。 */
export const BATCH_SEPARATOR_PATTERN = /[\s,;，；、]+/

/**
 * 把一条人工输入解析成标准粒子码。
 *
 * @returns {{ok: boolean, code: string, mode: string, reason: string, message: string, input: string}}
 *   ok=false 时 `message` 是能直接给操作员看的中文提示。
 */
export function normalizeParticleCode(raw) {
	const input = String(raw == null ? '' : raw).trim()
	const fail = (reason, message) => ({ ok: false, code: '', mode: '', reason, message, input })

	if (!input) {
		return fail('EMPTY', '输入不能为空，请输入 13 位序列号或完整 20 位粒子码。')
	}
	if (!/^\d+$/.test(input)) {
		return fail('INVALID_FORMAT', '粒子码只能包含数字，请重新输入（不会自动把字母 O/I 换成数字）。')
	}

	// 恰好 13 位：补前缀
	if (input.length === PARTICLE_SHORT_LENGTH) {
		return {
			ok: true,
			code: PARTICLE_PREFIX + input,
			mode: 'short',
			reason: '',
			message: '',
			input
		}
	}

	// 恰好 20 位：前缀正确才认
	if (input.length === PARTICLE_CODE_LENGTH) {
		if (input.indexOf(PARTICLE_PREFIX) === 0) {
			return { ok: true, code: input, mode: 'full', reason: '', message: '', input }
		}
		return fail(
			'WRONG_PREFIX',
			`20 位粒子码必须以 ${PARTICLE_PREFIX} 开头，当前是 ${input.slice(0, PARTICLE_PREFIX.length)}。`
		)
	}

	// 前缀被敲了两遍（27 位 = 7 + 20）：去掉多余那一遍，剩下按 20 位再判一次
	if (input.length === PARTICLE_PREFIX.length + PARTICLE_CODE_LENGTH) {
		const stripped = input.slice(PARTICLE_PREFIX.length)
		if (stripped.indexOf(PARTICLE_PREFIX) === 0) {
			return {
				ok: true,
				code: stripped,
				mode: 'stripped',
				reason: '',
				message: '',
				input
			}
		}
	}

	return fail(
		'INVALID_LENGTH',
		`粒子码需要 ${PARTICLE_SHORT_LENGTH} 位序列号或 ${PARTICLE_CODE_LENGTH} 位完整码，当前输入 ${input.length} 位。`
	)
}

/**
 * 解析一整段粘贴/输入的文本（多行、空格、逗号分隔都行）。
 *
 * 返回：
 *   valid            通过的候选（按输入顺序、已做输入内去重）
 *   duplicateInInput 本次输入里重复出现的（第二条及以后）
 *   invalid          长度/前缀/字符不合法的
 *   total            解析出的条目总数
 */
export function parseParticleBatch(text) {
	const raw = String(text == null ? '' : text)
	const tokens = raw.split(BATCH_SEPARATOR_PATTERN).filter((item) => item !== '')
	const seen = {}
	const valid = []
	const duplicateInInput = []
	const invalid = []

	tokens.forEach((token) => {
		const parsed = normalizeParticleCode(token)
		if (!parsed.ok) {
			invalid.push({ input: token, reason: parsed.reason, message: parsed.message })
			return
		}
		if (seen[parsed.code]) {
			duplicateInInput.push({ input: token, code: parsed.code, mode: parsed.mode })
			return
		}
		seen[parsed.code] = true
		valid.push({ input: token, code: parsed.code, mode: parsed.mode })
	})

	return { valid, duplicateInInput, invalid, total: tokens.length }
}

/** 给操作员看的一句话汇总（Toast / 事件条共用，避免各处自己拼文案）。 */
export function summarizeBatchParse(parsed) {
	const parts = [`有效 ${parsed.valid.length} 条`]
	if (parsed.duplicateInInput.length) parts.push(`重复 ${parsed.duplicateInInput.length} 条`)
	if (parsed.invalid.length) parts.push(`无效 ${parsed.invalid.length} 条`)
	return `本次解析 ${parsed.total} 条：${parts.join('，')}`
}

/**
 * 条码解码结果 → 与 OCR 同构的 blocks（`{text,left,top,right,bottom}`）。
 *
 * 为什么复用同一套结构：解码（zxing-wasm）和 OCR（ML Kit）两条引擎的产物都只是
 * "文本 + 坐标"，后面的清洗/排序/分类逻辑完全一样，不该写两份。
 * 缺坐标的项补 0，交给 `parseOcrParticleCandidates`（它会退化为保持原顺序，不瞎排）。
 */
export function barcodeResultsToBlocks(codes) {
	return (Array.isArray(codes) ? codes : [])
		.filter((item) => item && typeof item.text === 'string' && item.text !== '')
		.map((item) => {
			const box = {}
			// 坐标缺失就**保持缺失**（不补 0）：排序时会被放到最后，而不是被当成"左上角"
			;['left', 'top', 'right', 'bottom'].forEach((key) => {
				const value = Number(item[key])
				if (Number.isFinite(value)) box[key] = value
			})
			return Object.assign({ text: item.text }, box)
		})
}

/** 同一"行"的判定容差（OCR 坐标是图片像素）：top 差小于它就当作同一行，按 left 排序。 */
export const OCR_ROW_TOLERANCE = 24

/** 候选列表里"已删除"行的展示口径（视图层与单测共用同一份常量）。 */
export const OCR_ROW_DELETED_STATUS = '已删除'
export const OCR_ROW_DELETED_BADGE = 'badge-deleted'

/**
 * 候选行构造（纯函数）：把 `parseOcrParticleCandidates()` 的四类结果摊平成列表行。
 *
 * **必须传 `deletedMap`**：已删除的行保留在列表里（可追溯、删错能靠"重新识别"找回），
 * 但状态改成「已删除」、徽标换成灰色，并且 `deleted: true` —— 视图层据此加删除线、
 * 禁用删除按钮，`selectFillableOcrCodes()` 据此把它排除在"可填入"之外。
 *
 * 行 key 与四类结果的顺序绑定（有效/本次重复/批次内已存在/无效），删除判断按 key 做，
 * 所以同一枚码删掉后再识别也不会串行。
 *
 * @param {object|null} parsed `parseOcrParticleCandidates()` 的返回值
 * @param {object} deletedMap `{ [rowKey]: true }`，由操作员点「删除」累积
 * @returns {Array<{key,kind,index,code,input,status,badge,deleted}>}
 */
export function buildOcrCandidateRows(parsed, deletedMap) {
	const deleted = deletedMap && typeof deletedMap === 'object' ? deletedMap : {}
	const rows = []
	if (!parsed) return rows
	const push = (row) => {
		const isDeleted = deleted[row.key] === true
		rows.push(
			Object.assign({}, row, {
				index: rows.length + 1,
				deleted: isDeleted,
				status: isDeleted ? OCR_ROW_DELETED_STATUS : row.status,
				badge: isDeleted ? OCR_ROW_DELETED_BADGE : row.badge
			})
		)
	}
	;(parsed.valid || []).forEach((item) => {
		push({ kind: 'valid', key: `v-${item.code}`, code: item.code, input: item.input, status: '有效', badge: 'badge-ok' })
	})
	;(parsed.duplicateInInput || []).forEach((item) => {
		push({
			kind: 'dup-input',
			key: `i-${item.code}`,
			code: item.code,
			input: item.input,
			status: '本次重复',
			badge: 'badge-warn'
		})
	})
	;(parsed.duplicateInCurrentBatch || []).forEach((item) => {
		push({
			kind: 'dup-batch',
			key: `b-${item.code}`,
			code: item.code,
			input: item.input,
			status: '批次内已存在',
			badge: 'badge-warn'
		})
	})
	;(parsed.invalid || []).forEach((item, index) => {
		push({
			kind: 'invalid',
			key: `x-${index}-${item.input}`,
			code: '',
			input: item.input,
			status: '无效',
			badge: 'badge-error'
		})
	})
	return rows
}

/**
 * 可确认填入的码（纯函数）：只取"有效且没被操作员删掉"的行。
 * 这是「确认有效码并填入（N）」按钮的数字来源，也是唯一的写入数据源。
 */
export function selectFillableOcrCodes(rows) {
	return (Array.isArray(rows) ? rows : [])
		.filter((row) => row && row.kind === 'valid' && !row.deleted)
		.map((row) => row.code)
}

/**
 * 按位置排序 OCR 文本块。
 *
 * 为什么需要：ML Kit 返回的 block 顺序**不保证**是从上到下、从左到右，
 * 同一行还会因为字间距被拆成多个 block（项目已知问题）。
 * 所以先按 top、再按 left 排；再把 top 接近的归成同一行、行内按 left 排。
 * 没有坐标的 block 保持原顺序（不猜）。
 */
function sortOcrBlocks(blocks, rowTolerance) {
	// 有坐标的按位置排；**没有坐标的排在最后并保持原顺序** ——
	// 不能给它们补 0，否则会被当成"位于左上角"排到最前面（这是本模块踩过的坑）。
	const located = []
	const unlocated = []
	blocks.forEach((block, index) => {
		const top = Number(block.top)
		const left = Number(block.left)
		if (Number.isFinite(top) && Number.isFinite(left)) located.push({ block, index, top, left })
		else unlocated.push({ block, index })
	})
	if (!located.length) return blocks.slice()

	const entries = located
	entries.sort((a, b) => a.top - b.top || a.left - b.left || a.index - b.index)

	const rows = []
	entries.forEach((entry) => {
		const row = rows.find((item) => Math.abs(item.top - entry.top) <= rowTolerance)
		if (row) {
			row.items.push(entry)
			if (entry.top < row.top) row.top = entry.top
		} else {
			rows.push({ top: entry.top, items: [entry] })
		}
	})
	rows.sort((a, b) => a.top - b.top)
	return rows
		.flatMap((row) => row.items.sort((a, b) => a.left - b.left || a.index - b.index).map((entry) => entry.block))
		.concat(unlocated.map((entry) => entry.block))
}

/**
 * OCR 文本块 → 粒子码候选（阶段 2 的纯函数核心，不依赖任何原生插件，可单测）。
 *
 * 口径：
 *   - 每个 block 里抽出连续数字（`/\d+/g`），一行里有多个数字就都算候选；
 *   - 按 bounding box 从上到下、从左到右排序（ML Kit 顺序错乱的兜底）；
 *   - 复用 `normalizeParticleCode()` 标准化（13 位补前缀 / 20 位原样 / 其它非法）；
 *   - 分类成 `{ valid, duplicateInInput, duplicateInCurrentBatch, invalid }`；
 *   - **不做 O→0、I→1 猜测，不自动补零**；
 *   - 查重通过 `options.isUsed(code)` 注入（页面传 `findUsage(batch, code, 1)`），
 *     这样本模块保持零依赖、可在 PC 上单测。
 */
export function parseOcrParticleCandidates(blocks, options) {
	const settings = options || {}
	const isUsed = typeof settings.isUsed === 'function' ? settings.isUsed : () => null
	const rowTolerance = Number.isFinite(settings.rowTolerance) ? settings.rowTolerance : OCR_ROW_TOLERANCE
	const list = (Array.isArray(blocks) ? blocks : []).filter(
		(block) => block && typeof block.text === 'string' && block.text !== ''
	)
	const ordered = sortOcrBlocks(list, rowTolerance)
	// R5：先把"被字间距拆开的相邻数字块"拼回来（严格规则，见函数注释）
	const mergeResult =
		settings.mergeAdjacent === false ? { merged: [], consumedIndexes: [] } : mergeAdjacentDigitBlocks(ordered, settings)
	const consumed = {}
	mergeResult.consumedIndexes.forEach((index) => {
		consumed[index] = true
	})

	const valid = []
	const duplicateInInput = []
	const duplicateInCurrentBatch = []
	const invalid = []
	const seen = {}

	ordered.forEach((block, index) => {
		if (consumed[index]) return
		const raw = String(block.text)
		const tokens = raw.match(/\d+/g) || []
		tokens.forEach((token) => {
			const parsed = normalizeParticleCode(token)
			if (!parsed.ok) {
				invalid.push({ input: token, block: raw, reason: parsed.reason, message: parsed.message })
				return
			}
			if (seen[parsed.code]) {
				duplicateInInput.push({ input: token, code: parsed.code, mode: parsed.mode, block: raw })
				return
			}
			seen[parsed.code] = true
			const used = isUsed(parsed.code)
			if (used) {
				duplicateInCurrentBatch.push({
					input: token,
					code: parsed.code,
					mode: parsed.mode,
					block: raw,
					where: (used && used.where) || ''
				})
				return
			}
			valid.push({ input: token, code: parsed.code, mode: parsed.mode, block: raw })
		})
	})

	// 拼接出来的码与单个块走同一套校验/去重（保证规则只有一份）
	mergeResult.merged.forEach((block) => {
		const raw = String(block.text)
		const headers = (raw.match(/\d+/g) || [])
		headers.forEach((token) => {
			const parsed = normalizeParticleCode(token)
			if (!parsed.ok) return
			if (seen[parsed.code]) {
				duplicateInInput.push({ input: token, code: parsed.code, mode: parsed.mode, block: raw, mergedFrom: block.mergedFrom })
				return
			}
			seen[parsed.code] = true
			const used = isUsed(parsed.code)
			if (used) {
				duplicateInCurrentBatch.push({
					input: token,
					code: parsed.code,
					mode: parsed.mode,
					block: raw,
					mergedFrom: block.mergedFrom,
					where: (used && used.where) || ''
				})
				return
			}
			valid.push({
				input: token,
				code: parsed.code,
				mode: parsed.mode,
				block: raw,
				mergedFrom: block.mergedFrom
			})
		})
	})

	return {
		valid,
		duplicateInInput,
		duplicateInCurrentBatch,
		invalid,
		rawText: ordered.map((block) => String(block.text)).join('\n'),
		blockCount: ordered.length,
		mergedCount: mergeResult.merged.length
	}
}

/** 同一行的判定容差放大倍数：X 间隙 ≤ 行高 × 该倍数才认为"相邻"。 */
export const MERGE_GAP_RATIO = 1.2

/**
 * R5：把被字间距拆开的相邻数字块拼回来（纯函数，可单测）。
 *
 * 现场形态：ML Kit 会把一串 20 位数字按间距拆成 "8206233" + "1234567890123" 两块，
 * 每块单独看长度都不合法，直接判无效就会"识别不全"。
 *
 * 严格规则（与"不猜测"口径一致）：
 *   1. 只有**同一行**（top 差 ≤ 行容差）且 **X 相邻**（水平间隙 ≤ 行高 × 1.2）的块才尝试；
 *   2. 合并结果必须是 **13 位或 20 位纯数字**，并再过一次 `normalizeParticleCode()`；
 *   3. **不做字符猜测、不补零**；合并只发生在"数字块 + 数字块"之间；
 *   4. 每个块最多参与一次合并（避免链式误合并）；
 *   5. 返回 `consumedIndexes`，让调用方把被吃掉的碎片从"无效列表"里去掉，UI 更干净。
 */
export function mergeAdjacentDigitBlocks(blocks, options) {
	const settings = options || {}
	const rowTolerance = Number.isFinite(settings.rowTolerance) ? settings.rowTolerance : OCR_ROW_TOLERANCE
	const list = Array.isArray(blocks) ? blocks : []
	const merged = []
	const consumedIndexes = []
	const consumed = {}

	for (let index = 0; index < list.length; index += 1) {
		if (consumed[index]) continue
		const first = list[index]
		if (!first || typeof first.text !== 'string') continue
		const firstDigits = (first.text.match(/\d+/g) || []).join('')
		if (!firstDigits) continue
		const firstTop = Number(first.top)
		const firstBottom = Number(first.bottom)
		const firstRight = Number(first.right)
		if (![firstTop, firstBottom, firstRight].every((value) => Number.isFinite(value))) continue
		const rowHeight = Math.max(1, firstBottom - firstTop)
		const gapLimit = rowHeight * MERGE_GAP_RATIO

		for (let next = index + 1; next < list.length; next += 1) {
			if (consumed[next]) continue
			const second = list[next]
			if (!second || typeof second.text !== 'string') continue
			const secondDigits = (second.text.match(/\d+/g) || []).join('')
			if (!secondDigits) continue
			const secondTop = Number(second.top)
			const secondLeft = Number(second.left)
			if (!Number.isFinite(secondTop) || !Number.isFinite(secondLeft)) continue
			if (Math.abs(secondTop - firstTop) > rowTolerance) continue
			const gap = secondLeft - firstRight
			if (gap < 0 || gap > gapLimit) continue

			const candidate = firstDigits + secondDigits
			const parsed = normalizeParticleCode(candidate)
			if (!parsed.ok) continue

			merged.push({
				text: candidate,
				left: Math.min(Number(first.left), secondLeft),
				top: Math.min(firstTop, secondTop),
				right: Math.max(firstRight, Number(second.right)),
				bottom: Math.max(firstBottom, Number(second.bottom)),
				mergedFrom: [first.text, second.text]
			})
			consumed[index] = true
			consumed[next] = true
			consumedIndexes.push(index, next)
			break
		}
	}
	return { merged, consumedIndexes }
}
