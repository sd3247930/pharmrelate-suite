/**
 * WebSocket 客户端。

 * 严格实现 docs/43 冻结的信封格式。与 PC 侧 `WebSocketTransport` 是同一套协议，
 * 因此服务端一行不用改。

 * uni.connectSocket 在 App 端底层走**原生网络栈**（不是 WebView），
 * 这意味着自签证书的处理方式可能比 Capacitor 的 WebView 情况更好 ——
 * 但这一点必须真机验证，代码此处不预设结论。
 */

import { getDevice, getServer, resolveWsUrl } from './store'

export const PROTOCOL_VERSION = 1

/** 重连退避（V1.1 11.3），末档为上限。 */
export const BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 30]
export const JITTER_RATIO = 0.2

export function backoffDelay(attempt) {
	const base = BACKOFF_SCHEDULE[Math.min(Math.max(attempt, 1), BACKOFF_SCHEDULE.length) - 1]
	const jitter = 1 + (Math.random() * 2 - 1) * JITTER_RATIO
	return base * jitter
}

export class Envelope {
	constructor(kind, payload, options = {}) {
		this.version = PROTOCOL_VERSION
		this.kind = kind
		this.deviceId = options.deviceId || ''
		this.batchId = options.batchId || ''
		this.seq = options.seq || 0
		this.hlc = options.hlc || ''
		this.sentAt = options.sentAt || new Date().toISOString()
		this.payload = payload || {}
	}

	toJSON() {
		return {
			version: this.version,
			kind: this.kind,
			deviceId: this.deviceId,
			batchId: this.batchId,
			seq: this.seq,
			hlc: this.hlc,
			sentAt: this.sentAt,
			payload: this.payload
		}
	}
}

/**
 * 客户端封装。

 * 用法：
 *   const client = createClient({ onMessage, onStateChange })
 *   await client.connect(batchId)
 *   client.sendOps([{ code, packLayer, batchId }])
 */
export function createClient(handlers = {}) {
	let socket = null
	let seq = 0
	let attempt = 0
	let timer = null
	let closed = false
	let state = 'idle'

	function setState(next, detail) {
		state = next
		if (typeof handlers.onStateChange === 'function') {
			handlers.onStateChange(next, detail || '')
		}
	}

	function currentConfig() {
		const server = getServer()
		const device = getDevice()
		return {
			url: resolveWsUrl(server),
			token: server.token,
			batchId: server.batchId,
			deviceId: device.fingerprint || 'android-device',
			fingerprint: device.fingerprint || ''
		}
	}

	function connect() {
		return new Promise((resolve, reject) => {
			const config = currentConfig()
			if (!config.url) {
				reject(new Error('尚未设置 WebSocket 地址。'))
				return
			}
			if (!config.token) {
				reject(new Error('尚未配对。请到「连接设置」用扫码或输入配对 Token。'))
				return
			}

			closed = false
			setState('connecting', config.url)

			uni.connectSocket({ url: config.url })

			uni.onSocketOpen(() => {
				attempt = 0
				send(
					new Envelope(
						'hello',
						{
							deviceId: config.deviceId,
							deviceFingerprint: config.fingerprint,
							token: config.token,
							protocolVersion: PROTOCOL_VERSION
						},
						{ deviceId: config.deviceId, batchId: config.batchId, seq: 0 }
					)
				)
			})

			uni.onSocketMessage((message) => {
				let envelope
				try {
					envelope = JSON.parse(message.data)
				} catch (error) {
					setState('error', '收到无法解析的消息')
					return
				}

				if (envelope.kind === 'hello_ack') {
					if (envelope.payload && envelope.payload.ok) {
						setState('open', '')
						resolve({ socket, handshake: envelope.payload })
					} else {
						const reason = (envelope.payload && envelope.payload.reason) || 'UNKNOWN'
						setState('error', `配对失败：${reason}`)
						reject(new Error(`配对失败：${reason}`))
					}
					return
				}

				if (typeof handlers.onMessage === 'function') {
					handlers.onMessage(envelope)
				}
			})

			uni.onSocketError((error) => {
				setState('error', error.errMsg || '连接错误')
				reject(new Error(error.errMsg || '连接错误'))
			})

			uni.onSocketClose(() => {
				setState('closed', '')
				if (!closed) scheduleReconnect()
			})
		})
	}

	function scheduleReconnect() {
		const config = currentConfig()
		if (!config.url || !config.token) return
		attempt += 1
		const delay = backoffDelay(attempt)
		setState('reconnecting', `第 ${attempt} 次，${delay.toFixed(1)}s 后重试`)
		if (timer) clearTimeout(timer)
		timer = setTimeout(() => {
			connect().catch(() => {
				/* 失败会由 onSocketClose 再次触发调度 */
			})
		}, delay * 1000)
	}

	function send(envelope) {
		return new Promise((resolve, reject) => {
			uni.sendSocketMessage({
				data: JSON.stringify(envelope.toJSON()),
				success: resolve,
				fail: reject
			})
		})
	}

	/** 发送一批操作。序号由客户端维护（与 PC 侧一致）。 */
	function sendOps(ops) {
		const config = currentConfig()
		seq += 1
		return send(
			new Envelope('oplog', { ops }, {
				deviceId: config.deviceId,
				batchId: config.batchId,
				seq
			})
		)
	}

	function close() {
		closed = true
		if (timer) clearTimeout(timer)
		timer = null
		try {
			uni.closeSocket()
		} catch (error) {
			/* 已经关掉了 */
		}
		setState('closed', '手动断开')
	}

	return {
		connect,
		send,
		sendOps,
		close,
		getState: () => state,
		getSeq: () => seq,
		resetSeq: () => {
			seq = 0
		}
	}
}
