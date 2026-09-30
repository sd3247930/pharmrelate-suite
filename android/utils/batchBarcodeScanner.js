/**
 * 批量连续扫码启动链（plus.barcode 原生控件）—— Android 端唯一入口。
 *
 * 为什么单独成文件（而不是继续堆在 scan.vue）：
 *   plus.barcode 的生命周期是「原生控件」，出错面（权限 / Webview / append / start 重入）
 *   与业务数据层完全无关。分开以后，页面只关心「扫到什么码」，这里只关心「摄像头能不能
 *   连续跑」。同时这份实现可以用**假 plus** 做单测（tests/batchBarcodeScanner.test.mjs），
 *   PC 上就能验证状态机与重启逻辑，真机只验摄像头行为。
 *
 * 官方 API 事实（HBuilderX 内置 html5plus/plus.d.ts 与 html5plus.org/doc/zh_cn/barcode.html）：
 *   1. plus.barcode.create(id, filters, styles, autoDecodeCharset) **不会自动显示**，
 *      必须再调 plus.webview.Webview.append(barcode) 才会挂到页面上；
 *   2. create 的返回值就是 Barcode 对象，不需要 getBarcodeById 回查；
 *   3. cancel()   = 停止识别并关闭摄像头捕获，之后可以再 start()；
 *      close()    = 释放控件资源，调用后对象不可再用（会抛）；
 *   4. start(options) 的合法参数只有 conserve / filename / vibrate / sound
 *      —— 老代码里的 start({ conceal: true }) 是无效参数，已删除；
 *   5. 识别到一枚码后扫码头会停下，必须再次 start() 才能继续，
 *      所以「连续扫码」= start → onmarked → 处理 → start → onmarked → …
 *
 * 核心原则（本轮拍板）：
 *   Barcode 只 create 一次、Webview 只 append 一次、每识别一枚后重新 start，
 *   退出页面统一 cancel + close。
 */

export const ScannerState = {
	IDLE: 'idle',
	STARTING: 'starting',
	SCANNING: 'scanning',
	PROCESSING: 'processing',
	STOPPING: 'stopping',
	ERROR: 'error'
}

/** 原生控件的标识（仅作标识用，不依赖页面里存在同名 DOM 节点）。 */
export const SCANNER_ID = 'pr-batch-barcode-scanner'

/**
 * 码制过滤器。
 *
 * 收窄依据（阶段 D 任务 1，实拍标签解码取证，不是猜的）：
 *   把 private/图片 下的真实标签照片交给 zxing-cpp 解码，结果——
 *     15-箱码.jpg      → Code 128（8021761…，20 位数字）
 *     16-罐码.jpg      → QR Code（8021762…，罐号走 uni.scanCode，不经过本控件）
 *     17/18/19-条形码*.jpg、条形码.jpg → 全部 Code 128（8206233…，20 位数字）
 *   也就是说**粒子码实际只有 Code 128 一种**，所以这里只留 CODE128：
 *   码制越少，误识别越少、单枚识别越快。
 *
 * 以后如果标签换成别的码制，**只改这一行**（按实际存在的码制加，不预先全开）：
 *   ['CODE128', 'CODE39', 'CODE93', 'EAN13', 'EAN8']
 * 这里存的是常量名，调用时再从 plus.barcode 上取实际常量值，取不到的直接跳过。
 */
export const DEFAULT_FILTER_NAMES = ['CODE128']

/**
 * 每识别一枚之后、重新 start() 之前的等待（毫秒）—— 这段时间摄像头不取景，是**盲区**。
 *
 * 2026-10-01 复跑实测（544 次识别才换来 57 枚入库）：按「每次重启都等 350ms」算，
 * 整轮累计盲区 ≈190 秒，操作员连续扫时正好在这一段里把条码滑过去了 —— 这就是「漏扫」的主因。
 * 所以改成按结果分档，能少等的绝不多等：
 *   入库成功 → 等 200ms（留时间给 UI 更新、震动、落盘）
 *   业务拒绝 → 等 120ms（只是提示一下，没写库）
 *   瞬时忽略 → 等 60ms（同一枚码还在镜头里，越早恢复越好）
 */
export const RESTART_DELAY_ACCEPTED_MS = 200
export const RESTART_DELAY_REJECTED_MS = 120
export const RESTART_DELAY_IGNORED_MS = 60

/** 兼容旧调用方：不传 restartDelay 时，入库成功那条路用这个值。 */
export const DEFAULT_RESTART_DELAY = RESTART_DELAY_ACCEPTED_MS

/**
 * 瞬时防抖窗口（毫秒）：同一条码在这个窗口内重复触发一律静默忽略。
 *
 * 为什么是 2500（2026-09-30 真机压测拍板）：
 *   54 枚标签压测跑了 196 次识别、54 枚入库，中间有 80 次「同码 1.2 秒内重复」和
 *   62 次「同码超过 1.2 秒后又进业务层」——那 62 次全是操作员把同一枚标签多停在
 *   镜头里一会儿造成的。放宽到 2.5 秒把这类重复absorb 在扫码器层，业务层（本罐 Set
 *   与跨罐报警）继续兜底，合法新码一个都不会少。
 */
export const INSTANT_DEBOUNCE_MS = 2500

/** 逐枚耗时统计最多保留多少个入库时间戳（够压测用，不占内存）。 */
export const MAX_ACCEPT_SAMPLES = 300

/** 扫码控件默认位置：页面留位卡片会传入实测 styles，这里只是兜底。 */
export const DEFAULT_STYLES = {
	top: '0px',
	left: '0px',
	width: '100%',
	height: '45%',
	position: 'absolute',
	background: '#000000',
	frameColor: '#2563EB',
	scanbarColor: '#2563EB'
}

const LOG_PREFIX = '[BatchScan]'

function defaultLog(level, message, extra) {
	const sink = typeof console[level] === 'function' ? console[level] : console.log
	if (typeof extra === 'undefined') sink(LOG_PREFIX, message)
	else sink(LOG_PREFIX, message, extra)
}

/**
 * 取当前页面对应的 App Webview：append() 的接收方。
 *
 * uni-app 里 plus.webview.currentWebview() 多数情况可用，但页面栈才是权威来源，
 * 所以顺序是：页面实例 $getAppWebview() → 页面栈 $getAppWebview() → currentWebview()。
 */
export function getCurrentAppWebview(pageVm) {
	if (pageVm && typeof pageVm.$getAppWebview === 'function') {
		const webview = pageVm.$getAppWebview()
		if (webview) return webview
	}

	const pages = typeof getCurrentPages === 'function' ? getCurrentPages() : []
	if (pages && pages.length) {
		const page = pages[pages.length - 1]
		if (page && typeof page.$getAppWebview === 'function') {
			const webview = page.$getAppWebview()
			if (webview) return webview
		}
		if (page && page.$vm && page.$vm.$mp && page.$vm.$mp.page) {
			const mpPage = page.$vm.$mp.page
			if (typeof mpPage.$getAppWebview === 'function') {
				const webview = mpPage.$getAppWebview()
				if (webview) return webview
			}
		}
	}

	if (typeof plus !== 'undefined' && plus && plus.webview && plus.webview.currentWebview) {
		const webview = plus.webview.currentWebview()
		if (webview) return webview
	}

	throw new Error('APP_WEBVIEW_UNAVAILABLE')
}

/** 把常量名解析成 plus.barcode 上的真实值；缺失的码制直接跳过，不塞 undefined。 */
export function resolveFilters(plusLike, names) {
	const barcode = (plusLike && plusLike.barcode) || null
	const wanted = Array.isArray(names) ? names : DEFAULT_FILTER_NAMES
	const filters = []
	wanted.forEach((name) => {
		const value = barcode ? barcode[name] : null
		if (value) filters.push(value)
	})
	return filters
}

/**
 * 创建一个批量连续扫码器。
 *
 * @param {object}   [options]
 * @param {Function} [options.onCode]       识别到一枚码后调用：(code, type) => void | {accepted}
 * @param {Function} [options.onError]      出错时调用：(error, stage) => void
 * @param {Function} [options.onStateChange] 状态机变化时调用：(state, previous) => void
 * @param {Function} [options.ensurePermission] () => Promise<boolean>，默认放行
 * @param {Function} [options.getPlus]      取 plus 环境（默认取全局 plus），便于单测注假对象
 * @param {Function} [options.getWebview]   取 App Webview（默认 getCurrentAppWebview(pageVm)）
 * @param {object}   [options.pageVm]       页面实例，用于 $getAppWebview()
 * @param {Function} [options.log]          (level, message, extra) => void
 * @param {string[]} [options.filterNames]  码制常量名
 * @param {number}   [options.restartDelay] 入库成功后的重启延迟，默认 200ms
 * @param {number}   [options.rejectedRestartDelay] 被业务拒绝后的重启延迟，默认 120ms
 * @param {number}   [options.ignoredRestartDelay]  瞬时忽略后的重启延迟，默认 60ms
 * @param {Function} [options.getFeedback] () => ({ vibrate, sound })：每轮 start 时取最新设置
 * @param {number}   [options.duplicateCooldown] 瞬时防抖窗口，默认 INSTANT_DEBOUNCE_MS（2500ms）
 * @param {Function} [options.onRunSummary] 停止时回调本轮统计（含逐枚耗时），页面用它落盘
 * @param {Function} [options.setTimeout]   定时器（单测注入）
 * @param {Function} [options.clearTimeout] 清定时器（单测注入）
 * @param {Function} [options.now]          取时间戳（单测注入）
 */
export function createBatchBarcodeScanner(options = {}) {
	const log = typeof options.log === 'function' ? options.log : defaultLog
	const now = typeof options.now === 'function' ? options.now : () => Date.now()
	const scheduleTimer =
		typeof options.setTimeout === 'function' ? options.setTimeout : (fn, ms) => setTimeout(fn, ms)
	const cancelTimer =
		typeof options.clearTimeout === 'function' ? options.clearTimeout : (id) => clearTimeout(id)
	const getPlus =
		typeof options.getPlus === 'function'
			? options.getPlus
			: () => {
					if (typeof plus === 'undefined' || !plus) throw new Error('PLUS_UNAVAILABLE')
					if (!plus.barcode) throw new Error('PLUS_BARCODE_UNAVAILABLE')
					return plus
				}
	const getWebview =
		typeof options.getWebview === 'function'
			? options.getWebview
			: () => getCurrentAppWebview(options.pageVm)
	const ensurePermission =
		typeof options.ensurePermission === 'function' ? options.ensurePermission : async () => true
	const notifyError = typeof options.onError === 'function' ? options.onError : () => {}
	const notifyState =
		typeof options.onStateChange === 'function' ? options.onStateChange : () => {}
	const onCode = typeof options.onCode === 'function' ? options.onCode : async () => ({})

	const filterNames = Array.isArray(options.filterNames) ? options.filterNames : DEFAULT_FILTER_NAMES
	const restartDelay =
		Number.isFinite(options.restartDelay) && options.restartDelay >= 0
			? options.restartDelay
			: DEFAULT_RESTART_DELAY
	const rejectedRestartDelay =
		Number.isFinite(options.rejectedRestartDelay) && options.rejectedRestartDelay >= 0
			? options.rejectedRestartDelay
			: RESTART_DELAY_REJECTED_MS
	const ignoredRestartDelay =
		Number.isFinite(options.ignoredRestartDelay) && options.ignoredRestartDelay >= 0
			? options.ignoredRestartDelay
			: RESTART_DELAY_IGNORED_MS
	const getFeedback =
		typeof options.getFeedback === 'function'
			? options.getFeedback
			: () => ({ vibrate: true, sound: 'default' })
	const duplicateCooldown =
		Number.isFinite(options.duplicateCooldown) && options.duplicateCooldown >= 0
			? options.duplicateCooldown
			: INSTANT_DEBOUNCE_MS
	const onRunSummary =
		typeof options.onRunSummary === 'function' ? options.onRunSummary : () => {}

	let state = ScannerState.IDLE
	let barcode = null
	let active = false
	let restartTimer = null
	let lastCode = ''
	let lastCodeAt = 0
	let lastError = null
	const stats = {
		createCount: 0,
		appendCount: 0,
		startCount: 0,
		restartCount: 0,
		markedCount: 0,
		acceptedCount: 0,
		rejectedCount: 0,
		rapidDuplicateCount: 0,
		errorCount: 0,
		// 业务层拒绝的原始原因计数（按 onCode 返回的 reason 原样归类，诊断用）
		rejectReasonCodes: {},
		// 成功入库那一刻的时间戳（用于逐枚耗时统计，最多 MAX_ACCEPT_SAMPLES 个）
		acceptTimestamps: [],
		firstMarkedAt: 0,
		lastMarkedAt: 0
	}

	function setState(next) {
		if (state === next) return
		const previous = state
		state = next
		log('state', `${previous} -> ${next}`)
		try {
			notifyState(next, previous)
		} catch (error) {
			log('warn', 'onStateChange failed', error)
		}
	}

	function reportError(stage, error) {
		lastError = error || new Error(String(stage))
		stats.errorCount += 1
		log('error', `${stage} failed`, (error && error.message) || error)
		try {
			notifyError(error, stage)
		} catch (inner) {
			log('warn', 'onError callback failed', inner)
		}
	}

	function clearRestartTimer() {
		if (restartTimer) {
			cancelTimer(restartTimer)
			restartTimer = null
		}
	}

	/**
	 * 每次 start() 都重新取一遍反馈设置，所以「提示音开关」下一轮识别就生效
	 * （plus.barcode 的 sound / vibrate 是 start 参数，不是控件属性）。
	 */
	function scanStartOptions() {
		let feedback = null
		try {
			feedback = getFeedback()
		} catch (error) {
			log('warn', 'getFeedback failed', error)
		}
		const source = feedback && typeof feedback === 'object' ? feedback : {}
		return {
			vibrate: source.vibrate !== false,
			sound: source.sound === 'none' ? 'none' : 'default'
		}
	}

	function isRunning() {
		return (
			state === ScannerState.STARTING ||
			state === ScannerState.SCANNING ||
			state === ScannerState.PROCESSING
		)
	}

	/** 只释放原生控件，不改变 active（start 中途清理残留时用）。 */
	function releaseScanner(reason) {
		clearRestartTimer()
		if (!barcode) return
		const target = barcode
		barcode = null
		try {
			target.onmarked = null
			target.onerror = null
		} catch (error) {
			log('warn', 'clear listeners failed', error)
		}
		try {
			target.cancel()
			log('cancelled', reason || '')
		} catch (error) {
			log('warn', 'cancel failed', error)
		}
		try {
			target.close()
			log('closed', reason || '')
		} catch (error) {
			log('warn', 'close failed', error)
		}
	}

	/** 瞬时防抖：同一条码在窗口内重复触发 → 忽略（不算业务重复）。 */
	function isRapidDuplicate(code) {
		const stamp = now()
		if (code === lastCode && stamp - lastCodeAt < duplicateCooldown) return true
		lastCode = code
		lastCodeAt = stamp
		return false
	}

	/** 统一调度下一次识别：任何业务分支结束后都必须回到这里。 */
	function scheduleNextScan(delay) {
		clearRestartTimer()
		if (!active) return
		const wait = Number.isFinite(delay) ? delay : restartDelay
		restartTimer = scheduleTimer(() => {
			restartTimer = null
			if (!active || !barcode) return
			try {
				barcode.start(scanStartOptions())
				stats.startCount += 1
				stats.restartCount += 1
				log('restart scanning')
				// 计数先加再报状态：页面 onStateChange 里读到的统计才是这一轮的最新值
				setState(ScannerState.SCANNING)
			} catch (error) {
				reportError('restart', error)
				setState(ScannerState.ERROR)
			}
		}, wait)
	}

	/**
	 * 识别回调。无论正常码 / 重复码 / 格式错 / 业务校验失败，只要操作员还在连续扫码状态，
	 * 最后都必须回到 scheduleNextScan() —— 摄像头不能因为业务失败停掉。
	 */
	async function handleMarked(type, code) {
		if (!active) {
			log('marked ignored', 'scanner not active')
			return
		}
		const value = String(code == null ? '' : code).trim()
		stats.markedCount += 1
		const stamp = now()
		if (!stats.firstMarkedAt) stats.firstMarkedAt = stamp
		stats.lastMarkedAt = stamp
		// 同上：先记数，再让页面看到 processing
		setState(ScannerState.PROCESSING)
		log('marked', { type, code: value })

		// 盲区大小按结果分档：没写库的尽快恢复取景，写库成功才多等一会儿让 UI 落定
		let nextDelay = restartDelay
		try {
			if (!value) {
				nextDelay = ignoredRestartDelay
				return
			}
			if (isRapidDuplicate(value)) {
				stats.rapidDuplicateCount += 1
				log('rapid duplicate ignored', value)
				nextDelay = ignoredRestartDelay
				return
			}
			const result = await onCode(value, type)
			if (result && result.accepted === false) {
				stats.rejectedCount += 1
				const reason = result.reason || 'UNKNOWN'
				stats.rejectReasonCodes[reason] = (stats.rejectReasonCodes[reason] || 0) + 1
				nextDelay = rejectedRestartDelay
			} else {
				stats.acceptedCount += 1
				// 只记录成功入库的时刻：逐枚耗时看的是「有效码之间的间隔」
				if (stats.acceptTimestamps.length < MAX_ACCEPT_SAMPLES) {
					stats.acceptTimestamps.push(now())
				}
			}
		} catch (error) {
			// 业务异常只提示，不停摄像头
			reportError('onmarked', error)
			nextDelay = rejectedRestartDelay
		} finally {
			scheduleNextScan(nextDelay)
		}
	}

	function handleError(error) {
		reportError('onerror', error)
		setState(ScannerState.ERROR)
	}

	/**
	 * 启动连续扫码。返回 { ok, reason, state }：
	 *   - 已在跑 → { ok:false, reason:'ALREADY_RUNNING' }（不会重复 create）
	 *   - 失败   → { ok:false, reason: 错误信息 }，摄像头保持关闭，可由页面提示后重试
	 */
	async function start(startOptions = {}) {
		if (isRunning()) {
			log('start ignored', `already ${state}`)
			return { ok: false, reason: 'ALREADY_RUNNING', state }
		}

		setState(ScannerState.STARTING)
		active = true
		lastError = null

		try {
			log('start initialize')
			const plusLike = getPlus()
			// getPlus 的结果也要挡一道：无论是默认实现还是页面自己传进来的取法，
			// 都不能让「没有 plus」或「没有 Barcode 模块」变成一句看不懂的 TypeError。
			if (!plusLike) throw new Error('PLUS_UNAVAILABLE')
			if (!plusLike.barcode) throw new Error('PLUS_BARCODE_UNAVAILABLE')
			log('plus barcode module ready', (plusLike.os && plusLike.os.name) || 'unknown')

			const granted = await ensurePermission()
			if (granted === false) throw new Error('CAMERA_PERMISSION_DENIED')
			log('camera permission granted')

			// 上一次异常退出可能留下控件，先清干净（不改变 active）
			releaseScanner('before-start')

			const webview = getWebview()
			log('get app webview success')

			const styles = Object.assign({}, DEFAULT_STYLES, startOptions.styles || {})
			const filters = resolveFilters(plusLike, filterNames)
			log('creating barcode', { filters, styles })
			const target = plusLike.barcode.create(SCANNER_ID, filters, styles, false)
			if (!target) throw new Error('BARCODE_CREATE_RETURNED_NULL')
			stats.createCount += 1
			log('barcode created', `#${stats.createCount}`)

			target.onmarked = (type, code) => {
				handleMarked(type, code)
			}
			target.onerror = (error) => {
				handleError(error)
			}
			barcode = target

			webview.append(target)
			stats.appendCount += 1
			log('barcode appended')

			target.start(scanStartOptions())
			stats.startCount += 1
			log('barcode started')
			setState(ScannerState.SCANNING)
			return { ok: true, state, createCount: stats.createCount }
		} catch (error) {
			active = false
			reportError('start', error)
			releaseScanner('start-failed')
			setState(ScannerState.ERROR)
			return { ok: false, reason: (error && error.message) || String(error), state }
		}
	}

	/** 收掉原生控件并释放摄像头（cancel + close）。 */
	async function stop(reason) {
		active = false
		setState(ScannerState.STOPPING)
		releaseScanner(reason || 'stop')
		setState(ScannerState.IDLE)
		log('destroyed')
		// 把本轮统计交回页面落盘：HBuilderX 基座的 console 读不到，
		// 真机压测的「逐枚耗时 / 五维统计」只能靠这条回调带出来。
		try {
			onRunSummary(getStats(), reason || 'stop')
		} catch (error) {
			log('warn', 'onRunSummary failed', error)
		}
		return { ok: true, state }
	}

	/** 异常后由页面按钮触发的「重新启动扫码」：先 stop 再 start，绝不复用已 close 的对象。 */
	async function restart(startOptions = {}) {
		await stop('restart')
		return start(startOptions)
	}

	/**
	 * 逐枚耗时：只看两次「成功入库」之间的间隔（重复码、瞬时忽略都不算采样点）。
	 * 返回的 intervals 就是压测报告里那张逐枚耗时表。
	 */
	function getTiming() {
		const stamps = stats.acceptTimestamps
		if (!stamps.length) {
			return { count: 0, intervals: [], totalMs: 0, avgMs: null, minMs: null, maxMs: null, firstAt: 0, lastAt: 0 }
		}
		const intervals = []
		for (let index = 1; index < stamps.length; index += 1) {
			intervals.push(stamps[index] - stamps[index - 1])
		}
		const totalMs = stamps[stamps.length - 1] - stamps[0]
		return {
			count: stamps.length,
			intervals,
			totalMs,
			avgMs: intervals.length ? Math.round(totalMs / intervals.length) : null,
			minMs: intervals.length ? Math.min.apply(null, intervals) : null,
			maxMs: intervals.length ? Math.max.apply(null, intervals) : null,
			firstAt: stamps[0],
			lastAt: stamps[stamps.length - 1]
		}
	}

	/**
	 * 拒绝原因归类成四个桶（面板与压测报告统一口径）：
	 *   instantIgnore     = 同码在防抖窗口内被扫码器静默忽略
	 *   businessDuplicate = 本罐重复 / 跨罐重复（数据层判定）
	 *   invalidChar       = 含非数字字符 / 格式不合法
	 *   unknown           = 其余（含业务层抛出的其它 reason）
	 */
	function getRejectReasons() {
		const codes = stats.rejectReasonCodes
		const duplicateKeys = ['CURRENT_BATCH_DUPLICATE', 'CROSS_CONTAINER_DUPLICATE', 'DUPLICATE_CODE']
		const invalidKeys = ['INVALID_FORMAT', 'ILLEGAL_CHAR', 'UNSUPPORTED_TYPE']
		const businessDuplicate = duplicateKeys.reduce((sum, key) => sum + (codes[key] || 0), 0)
		const invalidChar = invalidKeys.reduce((sum, key) => sum + (codes[key] || 0), 0)
		return {
			instantIgnore: stats.rapidDuplicateCount,
			businessDuplicate,
			invalidChar,
			unknown: Math.max(0, stats.rejectedCount - businessDuplicate - invalidChar)
		}
	}

	/** 对外快照：不把内部数组/对象直接交出去（避免被外部或 Vue 响应式改到）。 */
	function getStats() {
		return {
			state,
			active,
			createCount: stats.createCount,
			appendCount: stats.appendCount,
			startCount: stats.startCount,
			restartCount: stats.restartCount,
			markedCount: stats.markedCount,
			acceptedCount: stats.acceptedCount,
			rejectedCount: stats.rejectedCount,
			rapidDuplicateCount: stats.rapidDuplicateCount,
			errorCount: stats.errorCount,
			rejectReasonCodes: Object.assign({}, stats.rejectReasonCodes),
			rejectReasons: getRejectReasons(),
			timing: getTiming(),
			lastError: lastError ? lastError.message || String(lastError) : ''
		}
	}

	return {
		start,
		stop,
		restart,
		getState: () => state,
		getStats,
		getTiming,
		isActive: () => active,
		isRapidDuplicate
	}
}
