/**
 * 会话 API 客户端。

 * 严格复用一期已冻结的后端接口 —— Android 端只是"另一个提交识别结果的来源"，
 * 状态机、拦截规则、去重、审计全部在服务端，这里不做任何本地判定。
 */

import { getServer } from './store'

export class ApiError extends Error {
	constructor(statusCode, body) {
		const error = (body && body.error) || {}
		super(error.message || `请求失败（HTTP ${statusCode}）`)
		this.name = 'ApiError'
		this.statusCode = statusCode
		this.code = error.code || 'UNKNOWN'
		this.detail = error.detail || {}
	}

	/** 校验类错误携带的问题清单。 */
	get issues() {
		return Array.isArray(this.detail.issues) ? this.detail.issues : []
	}
}

function baseUrl() {
	const server = getServer()
	if (!server.baseUrl) {
		throw new ApiError(0, {
			error: {
				code: 'NOT_CONFIGURED',
				message: '尚未设置服务地址。请到「连接设置」填写 Windows 主控机的局域网地址。'
			}
		})
	}
	return server.baseUrl.replace(/\/$/, '')
}

export function request(path, options = {}) {
	return new Promise((resolve, reject) => {
		let url
		try {
			url = `${baseUrl()}${path}`
		} catch (error) {
			reject(error)
			return
		}

		uni.request({
			url,
			method: options.method || 'GET',
			data: options.data,
			header: { 'Content-Type': 'application/json' },
			timeout: options.timeout || 15000,
			success(response) {
				if (response.statusCode >= 200 && response.statusCode < 300) {
					resolve(response.data)
					return
				}
				reject(new ApiError(response.statusCode, response.data))
			},
			fail(error) {
				reject(
					new ApiError(0, {
						error: {
							code: 'NETWORK_ERROR',
							message: `连不上服务（${error.errMsg || '未知原因'}）。请确认已连到车间局域网，且地址填写正确。`
						}
					})
				)
			}
		})
	})
}

export const api = {
	health: () => request('/api/health'),

	storage: () => request('/api/system/storage'),

	/** 批次列表，用于在手机上选一个正在采集的批次。 */
	listBatches: (status) =>
		request(`/api/batches${status ? `?status=${encodeURIComponent(status)}` : ''}`),

	getBatch: (batchId) => request(`/api/batches/${batchId}`),

	review: (batchId) => request(`/api/batches/${batchId}/review`),

	// ------------------------------------------------------------ 扫码会话
	scanSession: (batchId) => request(`/api/scan/${batchId}/session`),

	scanFrame: (batchId, codes, conflicts) =>
		request(`/api/scan/${batchId}/frame`, {
			method: 'POST',
			data: { codes: codes || [], conflicts: conflicts || [] }
		}),

	scanConfirm: (batchId) => request(`/api/scan/${batchId}/confirm`, { method: 'POST' }),

	scanRescan: (batchId) => request(`/api/scan/${batchId}/rescan`, { method: 'POST' }),

	scanNextCan: (batchId, proceed) =>
		request(`/api/scan/${batchId}/next-can`, { method: 'POST', data: { proceed: !!proceed } }),

	registerEarlyEnd: (batchId, reason, operator, note) =>
		request(`/api/batches/${batchId}/early-end`, {
			method: 'POST',
			data: { reason, operator, note }
		})
}

/**
 * 上传一张照片做识别。

 * 与 uni.scanCode 的区别：扫码一次只得到一个码；
 * 这里一次拍一张，服务端识别出**多个**码 —— 一张粒子标签纸有好几枚，
 * 逐个扫要扫很多次，拍一张就够。识别与拦截仍然全部在服务端。

 * 图片规格（拍板 D6）：长边 ≤1920、JPEG、≤5MB。
 * 长边由服务端识别前归一化；体积在服务端拒收并给出可读原因。
 */
export function captureUpload(filePath, options = {}) {
	return new Promise((resolve, reject) => {
		let base
		try {
			base = baseUrl()
		} catch (error) {
			reject(error)
			return
		}

		uni.uploadFile({
			url: `${base}/api/capture/upload`,
			filePath,
			name: 'photo',
			formData: {
				batchId: options.batchId || '',
				maxWidth: String(options.maxWidth || 1920)
			},
			timeout: 30000,
			success(response) {
				let body = null
				try {
					body = JSON.parse(response.data)
				} catch (error) {
					body = null
				}
				if (response.statusCode >= 200 && response.statusCode < 300) {
					resolve((body && body.capture) || {})
					return
				}
				reject(new ApiError(response.statusCode, body || {}))
			},
			fail(error) {
				reject(
					new ApiError(0, {
						error: {
							code: 'NETWORK_ERROR',
							message: `照片上传失败（${error.errMsg || '未知原因'}）。请确认已连到车间局域网。`
						}
					})
				)
			}
		})
	})
}

/**
 * 取该批次 XML 文件的下载地址（给 uni.downloadFile 用）。

 * XML 由服务端生成 —— 与电脑端导出**同一份产物**：同一条导出记录、
 * 同一个 SHA-256、同一套命名 `Relation_{批号}_{时间戳}.xml`。
 * 手机端不拼 XML 字符串：字节级格式只有一份实现，两处实现必然漂移。

 * operator 传本机设备名，这样导出记录里能看出是哪个终端导出的。
 */
export function exportXmlUrl(batchId, operator) {
	const server = getServer()
	if (!server.baseUrl) {
		throw new ApiError(0, {
			error: {
				code: 'NOT_CONFIGURED',
				message: '尚未设置服务地址。请到「连接设置」填写 Windows 主控机的局域网地址。'
			}
		})
	}
	if (!batchId) {
		throw new ApiError(0, {
			error: { code: 'NOT_CONFIGURED', message: '尚未选择批次，请先到「扫码」页刷新任务状态。' }
		})
	}
	const base = server.baseUrl.replace(/\/$/, '')
	const who = encodeURIComponent(operator || 'mobile')
	return `${base}/api/export/xml?batchId=${encodeURIComponent(batchId)}&operator=${who}`
}
