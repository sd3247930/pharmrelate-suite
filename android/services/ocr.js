/**
 * 离线 OCR 桥接层（可降级）。
 *
 * 设计原则（业务方 2026-10-02 拍板）：
 *   1. **插件可有可无**：基座里没有 `pharmrelate-ocr` 插件时，这里返回
 *      `{ success:false, code:'OCR_PLUGIN_MISSING' }`，页面据此降级到多行手动录入，
 *      功能不残废、不报错弹窗；
 *   2. OCR 只做「图片 → 文本块」，**绝不碰业务数据**：候选解析在
 *      `particleInput.parseOcrParticleCandidates()`，写槽位必须由操作员确认后走
 *      `localBatch.fillParticleCodesIntoEmptySlots()`；
 *   3. 插件名三处必须一致：`uni_modules/pharmrelate-ocr/` 目录名、
 *      插件包内 `name`、这里的 `requireNativePlugin('pharmrelate-ocr')`。
 *
 * 真机实测（2026-10-02）：标准基座里 `uni.requireNativePlugin()` 返回 undefined，
 * 所以上面的降级路径是**默认路径**；等业务方用带插件的自定义基座打包后自动生效。
 */

export const OCR_PLUGIN_NAME = 'pharmrelate-ocr'

/** 单次识别的兜底超时（毫秒）：插件卡死时不能让页面一直转圈。 */
export const OCR_TIMEOUT_MS = 15000

let cachedPlugin
let cacheReady = false

/** 取 nativeplugins 形态的插件实例；没有就返回 null（结果缓存，避免每次点都查一遍）。 */
export function getOcrPlugin() {
	if (cacheReady) return cachedPlugin
	cacheReady = true
	cachedPlugin = null
	try {
		if (typeof uni !== 'undefined' && typeof uni.requireNativePlugin === 'function') {
			cachedPlugin = uni.requireNativePlugin(OCR_PLUGIN_NAME) || null
		}
	} catch (error) {
		cachedPlugin = null
	}
	return cachedPlugin
}

/**
 * 已经确定有 OCR 能力（nativeplugins 实例）。
 *
 * 注：UTS（uni_modules）形态暂不参与构建 —— 实测「UTS 插件 + Maven 依赖」在
 * **标准基座运行**时会编译失败（Unresolved reference）并直接阻断整个 App 启动。
 * 骨架保留在 `native-plugin-skeleton/pharmrelate-ocr/`，等业务方要打自定义基座时
 * 再移回 `uni_modules/` 并在这里接上动态 import（写法见该骨架 README）。
 */
export function isOcrAvailable() {
	const plugin = getOcrPlugin()
	return !!(plugin && typeof plugin.recognizeImage === 'function')
}

function failure(code, message) {
	return { success: false, code, message, blocks: [], rawText: '' }
}

function normalizeResult(result) {
	if (!result || typeof result !== 'object') {
		return failure('OCR_BAD_RESULT', 'OCR 插件返回了无法解析的结果。')
	}
	if (result.success === false) {
		return failure(result.code || 'OCR_FAILED', result.message || 'OCR 识别失败。')
	}
	return {
		success: true,
		code: '',
		message: '',
		blocks: Array.isArray(result.blocks) ? result.blocks : [],
		rawText: typeof result.rawText === 'string' ? result.rawText : ''
	}
}

/**
 * 识别一张本地图片。
 * @param {string} imagePath 图片路径（uni.chooseImage 返回的 tempFilePaths[0]）
 * @returns {Promise<{success:boolean, code:string, message:string, blocks:Array, rawText:string}>}
 */
export async function recognizeImage(imagePath) {
	if (!imagePath) {
		return failure('OCR_NO_IMAGE', '没有拿到图片路径，无法识别。')
	}

	// 唯一的插件形态：nativeplugins（uni.requireNativePlugin 是运行时解析，不参与构建期解析）
	const plugin = getOcrPlugin()
	if (plugin && typeof plugin.recognizeImage === 'function') {
		return callPlugin(plugin, imagePath)
	}

	// 没有插件 → 明确降级（页面会先走免插件的条码解码，再退到这里）
	return failure('OCR_PLUGIN_MISSING', '本机基座没有 OCR 插件，请放大图片后手动录入（有插件时会自动识别）。')
}

function callPlugin(plugin, imagePath) {
	return new Promise((resolve) => {
		let settled = false
		const finish = (value) => {
			if (settled) return
			settled = true
			resolve(normalizeResult(value))
		}
		const timer = setTimeout(() => finish(failure('OCR_TIMEOUT', '识别超时，请重试或改用手动录入。')), OCR_TIMEOUT_MS)
		const done = (value) => {
			clearTimeout(timer)
			finish(value)
		}

		try {
			// UTS 插件既可能返回 Promise，也可能走回调；两条路都兜住
			const returned = plugin.recognizeImage({ imagePath }, (result) => done(result))
			if (returned && typeof returned.then === 'function') {
				returned.then(done).catch((error) =>
					done(failure('OCR_CALL_FAILED', (error && error.message) || 'OCR 调用失败。'))
				)
			}
		} catch (error) {
			done(failure('OCR_CALL_FAILED', (error && error.message) || 'OCR 调用失败。'))
		}
	})
}
