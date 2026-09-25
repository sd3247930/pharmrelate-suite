/**
 * 本地配置与状态。

 * uni-app App 端没有 localStorage，一律走 uni.setStorageSync。
 * 键名与一期桌面端的浏览器存储保持一致的命名习惯，便于排查。
 */

const KEY_SERVER = 'pharmrelate.server'
const KEY_DEVICE = 'pharmrelate.device'

const DEFAULT_SERVER = {
	/** Windows 主控机的局域网地址，例如 http://192.168.1.20:17800 */
	baseUrl: '',
	/** WSS/WS 地址；留空则按 baseUrl 推导 */
	wsUrl: '',
	/** 配对 Token（一次性，5 分钟过期） */
	token: '',
	/** 当前批次 id */
	batchId: '',
	/** 当前批次号（显示用） */
	batchNo: ''
}

export function ensureDefaults() {
	const server = uni.getStorageSync(KEY_SERVER)
	if (!server || typeof server !== 'object') {
		uni.setStorageSync(KEY_SERVER, { ...DEFAULT_SERVER })
	}
	if (!getDevice().fingerprint) {
		setDevice({
			fingerprint: makeFingerprint(),
			name: defaultDeviceName()
		})
	}
}

export function getServer() {
	const stored = uni.getStorageSync(KEY_SERVER)
	return { ...DEFAULT_SERVER, ...(stored && typeof stored === 'object' ? stored : {}) }
}

export function setServer(patch) {
	const next = { ...getServer(), ...patch }
	uni.setStorageSync(KEY_SERVER, next)
	return next
}

/**
 * WebSocket 地址：显式配置优先，否则由 baseUrl 推导。
 * http → ws，https → wss。
 */
export function resolveWsUrl(server) {
	const current = server || getServer()
	if (current.wsUrl) return current.wsUrl
	if (!current.baseUrl) return ''
	return current.baseUrl.replace(/^http/, 'ws')
}

export function getDevice() {
	const stored = uni.getStorageSync(KEY_DEVICE)
	return stored && typeof stored === 'object' ? stored : { fingerprint: '', name: '' }
}

export function setDevice(patch) {
	const next = { ...getDevice(), ...patch }
	uni.setStorageSync(KEY_DEVICE, next)
	return next
}

function defaultDeviceName() {
	try {
		const info = uni.getSystemInfoSync()
		return `${info.brand || ''}${info.model || ''}`.trim() || 'android-device'
	} catch (error) {
		return 'android-device'
	}
}

/** 设备指纹：与一期服务端 pairing.fingerprint 的用途一致（绑定 Token，防转发）。 */
function makeFingerprint() {
	const seed = `${defaultDeviceName()}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
	// 简易散列足以生成稳定标识；真正的安全意义在于"换设备就变"
	let hash = 0
	for (let index = 0; index < seed.length; index += 1) {
		hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
	}
	return `and-${hash.toString(16)}-${seed.length}`
}
