/**
 * 图库识别的**服务层支撑**（解码本体已迁到 renderjs 视图层，见 pages/scan/scan.vue 的
 * `<script module="imageDecoder" lang="renderjs">`）。
 *
 * 为什么解码搬走：真机实测 `readBarcodes()` 在服务层（DCloud JSCore）**永不返回**
 * （12MP / 3.4MP / 800px 全卡 >35s；Node 同算法 97~171ms）——服务层没有
 * Blob / Image / canvas / createImageBitmap。视图层是完整浏览器环境，同一套代码可用。
 *
 * 这个文件只做四件事，都是服务层该干的：
 *   1. 把图片读成 data URL（plus.io，带"先复制进沙箱"的兜底 —— 相册"原图"URI 直接读会失败）；
 *   2. 把 wasm 读成 base64（只读一次并缓存，注入给视图层，**不 fetch**）；
 *   3. 提供 ROI（条码框 → 下方数字区域）的纯函数，可单测；
 *   4. 暴露开关与超时常量。
 */

/** 总开关：renderjs 解码链路（真机验收通过后置 true；失败时置 false 即回到纯手动录入）。 */
export const IMAGE_CODE_DECODER_ENABLED = true

/** 硬超时：任何情况下 12 秒内必须给出结果或降级，不允许卡界面。 */
export const DECODER_TIMEOUT_MS = 12000

/** 软超时（秒）：到了就先提示"已识别 N 个，继续识别中"，允许操作员提前确认。 */
export const DECODER_SOFT_TIMEOUT_MS = 5000

/**
 * 工作图最长边。renderjs（浏览器环境）能吃下整张原图，所以直接给 3240：
 * 实测 2400px 时 9 码标签页只能解出 8 枚（漏 1 枚），原分辨率可全中；
 * 而浏览器里的 wasm 对 12MP 也只需百毫秒级，不必为性能牺牲识别率。
 */
export const DECODER_MAX_SIDE = 4096

/** 内联 wasm 路径（视图层拿不到它，服务层读成 base64 传过去）。 */
export const DECODER_WASM_URL = '_www/static/zxing/zxing_reader.wasm'

const BASE64_LOOKUP = (() => {
	const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
	const table = new Int16Array(256).fill(-1)
	for (let index = 0; index < chars.length; index += 1) table[chars.charCodeAt(index)] = index
	return table
})()

/**
 * base64 → Uint8Array（纯 JS 解码表）。
 * 刻意不用 `atob`：uni-app App 的服务层是 JSCore，`atob` / `Blob` 这类 Web API 不一定存在。
 */
export function base64ToBytes(base64) {
	const clean = String(base64 || '').replace(/^data:[^,]*,/, '').replace(/[^A-Za-z0-9+/=]/g, '')
	const padding = clean.endsWith('==') ? 2 : clean.endsWith('=') ? 1 : 0
	const length = Math.max(0, (clean.length / 4) * 3 - padding)
	const bytes = new Uint8Array(length)
	let byteIndex = 0
	let buffer = 0
	let bits = 0
	for (let index = 0; index < clean.length; index += 1) {
		const value = BASE64_LOOKUP[clean.charCodeAt(index)]
		if (value < 0) continue
		buffer = (buffer << 6) | value
		bits += 6
		if (bits >= 8) {
			bits -= 8
			bytes[byteIndex] = (buffer >> bits) & 0xff
			byteIndex += 1
		}
	}
	return bytes.subarray(0, byteIndex)
}

/** 运行时是否具备读取条件（App 端 + plus.io）。 */
export function isDecoderSupported() {
	return typeof plus !== 'undefined' && !!(plus && plus.io && plus.io.resolveLocalFileSystemURL)
}

/** 解析文件/内容 URI 为 entry。 */
function resolveEntry(url) {
	return new Promise((resolve, reject) => {
		plus.io.resolveLocalFileSystemURL(
			url,
			(entry) => resolve(entry),
			(error) => reject(new Error(`打不开文件：${(error && error.message) || url}`))
		)
	})
}

/** 直接读 entry 为 base64 data URL。 */
function readEntryAsDataUrl(entry) {
	return new Promise((resolve, reject) => {
		entry.file(
			(file) => {
				const reader = new plus.io.FileReader()
				reader.onloadend = (event) => {
					const result = (event && event.target && event.target.result) || reader.result
					if (!result) {
						reject(new Error('文件读取结果为空'))
						return
					}
					resolve(String(result))
				}
				reader.onerror = () => reject(new Error('文件读取失败'))
				reader.readAsDataURL(file)
			},
			(error) => reject(new Error(`取文件失败：${(error && error.message) || '未知'}`))
		)
	})
}

/**
 * 兜底：把源文件复制进应用沙箱再读。
 * 真机实测：相册选"原图"拿到的是内容/媒体 URI，`readAsDataURL` 直接读它会失败；
 * 复制到 `_doc` 后再读就正常（临时文件用完即删）。
 */
function copyAndRead(entry) {
	return new Promise((resolve, reject) => {
		plus.io.resolveLocalFileSystemURL(
			'_doc',
			(dirEntry) => {
				entry.copyTo(
					dirEntry,
					'pr-decode-tmp.jpg',
					(copied) => {
						readEntryAsDataUrl(copied)
							.then((dataUrl) => {
								try {
									copied.remove()
								} catch (error) {
									// 删不掉不影响解码，临时目录会被系统清理
								}
								resolve(dataUrl)
							})
							.catch(reject)
					},
					(error) => reject(new Error(`复制图片失败：${(error && error.message) || '未知'}`))
				)
			},
			(error) => reject(new Error(`打不开沙箱目录：${(error && error.message) || ''}`))
		)
	})
}

/** 图片路径 → data URL（服务层读，供视图层解码）。 */
export function readImageAsDataUrl(filePath) {
	if (!isDecoderSupported()) {
		return Promise.reject(new Error('当前环境不支持本地解码（仅 App 端可用）'))
	}
	if (!filePath) {
		return Promise.reject(new Error('没有拿到图片路径'))
	}
	return resolveEntry(filePath).then((entry) => readEntryAsDataUrl(entry).catch(() => copyAndRead(entry)))
}

/** wasm data URL 只读一次（931KB → base64 约 1.2MB），后续复用。 */
let wasmDataUrlPromise = null
export function readWasmAsDataUrl() {
	if (!wasmDataUrlPromise) {
		wasmDataUrlPromise = resolveEntry(DECODER_WASM_URL)
			.then((entry) => readEntryAsDataUrl(entry))
			.catch((error) => {
				wasmDataUrlPromise = null
				throw new Error(`读取解码引擎失败：${(error && error.message) || error}`)
			})
	}
	return wasmDataUrlPromise
}

/** 测试用：清掉 wasm 缓存。 */
export function resetDecoderCache() {
	wasmDataUrlPromise = null
}

/**
 * R4：条码框 → 下方"人眼可读数字"ROI（纯函数，可单测）。
 *
 * 思路：数字通常印在条码正下方，所以从条码框下沿往下扩一定比例，
 * 左右各留一点边距（标签排版会有偏移）。返回整数像素矩形，并夹在原图范围内。
 *
 * @param {{left:number,top:number,right:number,bottom:number}} box 条码框（原图坐标）
 * @param {object} [options] { marginRatio=0.08, heightRatio=0.7, imageWidth, imageHeight }
 */
export function buildDigitRoi(box, options) {
	if (!box) return null
	const left = Number(box.left)
	const right = Number(box.right)
	const top = Number(box.top)
	const bottom = Number(box.bottom)
	if (![left, right, top, bottom].every((value) => Number.isFinite(value))) return null
	const settings = options || {}
	const width = Math.max(0, right - left)
	const height = Math.max(0, bottom - top)
	if (!width || !height) return null
	const marginRatio = Number.isFinite(settings.marginRatio) ? settings.marginRatio : 0.08
	const heightRatio = Number.isFinite(settings.heightRatio) ? settings.heightRatio : 0.7
	const margin = Math.round(width * marginRatio)
	const roiLeft = Math.max(0, left - margin)
	const roiRight = right + margin
	const roiTop = bottom
	const roiBottom = bottom + Math.round(height * heightRatio)
	const imageWidth = Number.isFinite(settings.imageWidth) ? settings.imageWidth : null
	const imageHeight = Number.isFinite(settings.imageHeight) ? settings.imageHeight : null
	return {
		left: Math.round(roiLeft),
		top: Math.round(roiTop),
		right: Math.round(imageWidth ? Math.min(imageWidth, roiRight) : roiRight),
		bottom: Math.round(imageHeight ? Math.min(imageHeight, roiBottom) : roiBottom)
	}
}
