/**
 * 追溯码视觉识别契约层（v1.4.0，方案 C：契约 + 降级）。
 *
 * 为什么是契约层而不是真 OCR：
 *   真机实测（HONOR ANDROID_DEVICE / HBuilderX 标准基座）—— `plus` 的 49 个命名空间里
 *   没有任何 ocr/ai/ml/vision/infer，`plus.barcode` 也没有 `scanImage`（传文件路径一律 fail code=8），
 *   工程里也没有 ONNX 模型或 OCR 原生插件。所以在「不改后端 + 识别在手机本地完成 + 离线可用」
 *   三条约束下，「拍照 → 自动提取 20 位追溯码」当前**做不到**。
 *   于是把「识别」抽成可插拔 Provider：默认 Provider 严格返回 failure，界面降级到人工读数；
 *   将来接入云侧 API 或端侧模型时只要 `setProvider()` 换一个实现，界面与业务层一行不用改。
 *
 * ── 自拟识别规范（原《Android 摄像头数字识别提示词》未提供，这里按业务要求落成硬规则，
 *    供将来的真实 Provider 作为输入输出基准）────────────────────────────────────────
 *   1. 只认「真正的数字」：忽略 Word 段落标记 ↵、回车换行、空格、下划线、光标残留、
 *      表格边框、条形码线条、标签上的连字符（`8021762-9000000001003` 中间那个 `-`），
 *      以及手机状态栏（时间/电量/信号）和电脑屏幕的工具栏/标尺/任务栏；
 *   2. 字母不转数字：`I`/`l`/`O`/`o`/`S`/`B` 等明显是字母的字符一律保留原样，
 *      `normalizeResult` 见到非数字字符就判失败，**绝不**把 `I23` 强行当成 `123`；
 *   3. 禁止补位：不补零、不补全 20 位、不推测被遮挡的数字 —— 宁可返回 `success:false`；
 *   4. 置信度 `< 0.70` → `needsConfirmation = true`；不确定 → `success:false`；
 *   5. 一张图里读到多组号码 → 全部放进 `candidates`，由**业务层**决定是否多码报警。
 *
 * ── 职责边界（文档要求「识别与业务校验必须分离」）────────────────────────────────
 *   本模块只回答「看见了什么数字」，**不做**任何业务判断：
 *   长度（20 位）、前缀（箱 8021761 / 罐 8021762 / 粒子 8206233）、查重、相位推进
 *   都在 `services/localBatch.js` 与页面里做。
 *   所以 `normalizeResult` 对长度不足 20 位或前缀不符的内容仍然会给 `success:true`，
 *   由业务层的 `validateLayerCode()` 去拦。
 *   连字符属于标签**排版噪声**（现场标签就是「药品标识码-序列号」两段拼的），
 *   在这里剥掉；它是格式噪声，不属于业务判断。
 *
 * 本文件与 `localBatch.js` 一样刻意**不 import 任何东西**，Node 单测可以直接加载。
 */

/** 识别来源类型（Provider 应尽量如实标注）。 */
export const SOURCE_TYPES = {
	HANDWRITTEN_BOX: 'handwritten_box',
	COMPUTER_DOCUMENT: 'computer_document',
	PRINTED_DOCUMENT: 'printed_document',
	UNKNOWN: 'unknown'
}

/** 低于这个置信度必须人工确认（文档拍板 0.70）。 */
export const CONFIDENCE_THRESHOLD = 0.7

/** 契约的空结果（也是默认降级 Provider 的返回值）。 */
export const EMPTY_RESULT = Object.freeze({
	success: false,
	number: '',
	confidence: 0,
	sourceType: SOURCE_TYPES.UNKNOWN,
	needsConfirmation: true,
	candidates: []
})

/**
 * 噪声净化：剔除段落标记、空白、零宽字符、下划线/光标竖线，以及标签上的连字符。
 * 只做「去掉明显不是数字的排版噪声」，不做任何补位或字符替换。
 */
export function sanitizeDigits(value) {
	const raw = String(value == null ? '' : value)
		.replace(/[\u21B5\u240D\u23CE\u00B6\u00A7]/g, '') // ↵ 段落标记的几种写法
		.replace(/[\s\u00A0\u200B-\u200D\uFEFF]/g, '') // 空格、不间断空格、零宽字符
		.replace(/[_\uFF3F|]/g, '') // 下划线 / 光标竖线
	// 连字符：现场罐码印的是 `8021762-9000000001003`，两段之间的 `-` 是排版分隔符。
	// 只剔「夹在两个数字之间」的连字符，行首的负号保留 ——
	// 这样 `-1` 仍然按「不猜测」判失败（见单测 ③），不会把符号悄悄吃掉。
	let out = raw
	let prev = ''
	while (out !== prev) {
		prev = out
		out = out.replace(/(\d)-(\d)/g, '$1$2') // 循环是为了吃掉 `1-2-3` 这种连续分段
	}
	return out
}

function toConfidence(value) {
	const number = Number(value)
	if (!Number.isFinite(number)) return 0
	if (number < 0) return 0
	if (number > 1) return 1
	return number
}

function isSourceType(value) {
	return Object.keys(SOURCE_TYPES).some((key) => SOURCE_TYPES[key] === value)
}

/**
 * 把 Provider 的原始返回净化成契约结果。
 * 规则：非纯数字（含字母/小数点/负号）一律判失败且**不保留原值**，绝不猜测、绝不补位。
 */
export function normalizeResult(raw) {
	const input = raw && typeof raw === 'object' ? raw : {}
	const number = sanitizeDigits(input.number)
	const confidence = toConfidence(input.confidence)
	const sourceType = isSourceType(input.sourceType) ? input.sourceType : SOURCE_TYPES.UNKNOWN

	const rawCandidates = Array.isArray(input.candidates)
		? input.candidates
		: number
			? [number]
			: []
	const candidates = rawCandidates
		.map((item) => sanitizeDigits(item))
		.filter((item) => item.length > 0)

	const pureDigits = number.length > 0 && /^\d+$/.test(number)
	const success = input.success === true && pureDigits

	return {
		success,
		number: success ? number : '',
		confidence: success ? confidence : 0,
		sourceType,
		// 失败、或置信度不达标 → 都要人工确认
		needsConfirmation: !success || confidence < CONFIDENCE_THRESHOLD,
		candidates
	}
}

/**
 * 默认 Provider（方案 C）：本机没有识别引擎，严格返回失败，绝不猜测。
 * 界面据此降级到「拍照 → 人眼读数 → 手动输入」。
 */
export function manualConfirmProvider() {
	return Object.assign({}, EMPTY_RESULT)
}

let provider = manualConfirmProvider

/** 插拔真实识别实现（云侧 API 或端侧模型）。传非函数则回落到默认 Provider。 */
export function setProvider(next) {
	provider = typeof next === 'function' ? next : manualConfirmProvider
	return provider
}

export function getProviderName() {
	return (provider && provider.name) || 'anonymousProvider'
}

/**
 * 识别入口：`recognizeNumber(imagePath, options)`。
 * Provider 抛错也不影响采集 —— 按「识别失败」处理，交给人工确认。
 */
export async function recognizeNumber(imagePath, options) {
	const filePath = String(imagePath == null ? '' : imagePath)
	if (!filePath) return Object.assign({}, EMPTY_RESULT)
	try {
		const raw = await provider({ imagePath: filePath, options: options || {} })
		return normalizeResult(raw)
	} catch (error) {
		return Object.assign({}, EMPTY_RESULT)
	}
}
