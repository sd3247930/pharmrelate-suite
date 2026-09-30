/**
 * 批量连续扫码启动链单测。
 *
 * 真机行为（摄像头能不能连续取景）只能在手机上验，但**启动链本身**——状态机、
 * 「一次 create / 多次 start」、瞬时防抖、业务失败不停摄像头、重入保护、
 * cancel+close 释放——全部可以在 PC 上用「假 plus / 假定时器」验完。
 *
 * 加载方式与其它单测一致：源码读出来按 ESM 从 data: URL 加载，不为测试改产品代码。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/batchBarcodeScanner.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '..', 'utils', 'batchBarcodeScanner.js'), 'utf8')
const mod = await import('data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'))

const {
	ScannerState,
	createBatchBarcodeScanner,
	getCurrentAppWebview,
	resolveFilters,
	INSTANT_DEBOUNCE_MS
} = mod

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
// 测试替身：假 plus / 假 Webview / 假定时器 / 假时钟
// ---------------------------------------------------------------------------

function makeFakePlus() {
	const created = []
	const barcode = {
		// 常量名与官方一致；值本身无所谓，只要求唯一
		QR: 1,
		CODE128: 128,
		CODE39: 39,
		CODE93: 93,
		EAN13: 13,
		EAN8: 8,
		create(id, filters, styles, autoDecodeCharset) {
			const target = {
				id,
				filters,
				styles,
				autoDecodeCharset,
				onmarked: null,
				onerror: null,
				startCalls: 0,
				cancelCalls: 0,
				closeCalls: 0,
				lastOptions: null,
				start(options) {
					this.startCalls += 1
					this.lastOptions = options || null
				},
				cancel() {
					this.cancelCalls += 1
				},
				close() {
					this.closeCalls += 1
				}
			}
			created.push(target)
			return target
		}
	}
	return { os: { name: 'Android' }, barcode, created }
}

function makeFakeWebview() {
	return {
		appended: [],
		append(child) {
			this.appended.push(child)
		}
	}
}

function makeClock() {
	let current = 1_000_000
	let nextId = 1
	let lastDelay = null
	const timers = new Map()
	return {
		now: () => current,
		setTimeout: (fn, ms) => {
			const id = nextId
			nextId += 1
			lastDelay = typeof ms === 'number' ? ms : null
			timers.set(id, fn)
			return id
		},
		clearTimeout: (id) => {
			timers.delete(id)
		},
		advance: (ms) => {
			current += ms
		},
		size: () => timers.size,
		lastDelay: () => lastDelay,
		drain: (out) => {
			timers.forEach((fn) => out.push(fn))
			timers.clear()
		}
	}
}

/** 把微任务队列跑干净（模块里 onmarked → await onCode → finally） */
const settle = async () => {
	for (let index = 0; index < 6; index += 1) {
		await new Promise((done) => setImmediate(done))
	}
}

/** 触发到期定时器（假定时器不区分时间，全部当作已到期） */
const flushTimers = async (clock) => {
	while (clock.size() > 0) {
		const pending = []
		// 定时器回调里可能再注册新定时器（连续扫码就是这样），所以循环到空
		clock.drain(pending)
		pending.forEach((fn) => fn())
		await settle()
	}
}

function buildScanner(overrides = {}) {
	const fakePlus = overrides.plus || makeFakePlus()
	const webview = overrides.webview || makeFakeWebview()
	const clock = overrides.clock || makeClock()
	const events = { states: [], errors: [], codes: [] }
	const scanner = createBatchBarcodeScanner(
		Object.assign(
			{
				getPlus: () => {
					if (fakePlus === 'missing') return null
					if (fakePlus === 'no-barcode') return { os: { name: 'Android' } }
					return fakePlus
				},
				getWebview: () => webview,
				ensurePermission: overrides.ensurePermission || (async () => true),
				onCode:
					overrides.onCode ||
					(async (code, type) => {
						events.codes.push({ code, type })
						return { accepted: true }
					}),
				onError: (error, stage) => {
					events.errors.push({ stage, message: (error && error.message) || String(error) })
				},
				onStateChange: (state, previous) => {
					events.states.push(`${previous}->${state}`)
				},
				now: clock.now,
				setTimeout: (fn, ms) => clock.setTimeout(fn, ms),
				clearTimeout: (id) => clock.clearTimeout(id),
				log: () => {}
			},
			overrides.options || {}
		)
	)
	return { scanner, fakePlus, webview, clock, events }
}

// ---------------------------------------------------------------------------
section('启动链：create → append → start（P0）')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, webview } = buildScanner()
	const result = await scanner.start()

	equal(result.ok, true, 'start() 返回成功')
	equal(scanner.getState(), ScannerState.SCANNING, '启动后状态 = scanning')
	equal(fakePlus.created.length, 1, '只 create 一次')
	equal(webview.appended.length, 1, 'append 一次（原生控件才会显示）')
	equal(webview.appended[0], fakePlus.created[0], 'append 的就是 create 返回的对象（不需 getBarcodeById 回查）')
	equal(fakePlus.created[0].startCalls, 1, 'start 一次')
	equal(fakePlus.created[0].id, 'pr-batch-barcode-scanner', '控件 id 固定')
	equal(fakePlus.created[0].filters.length, 1, '默认只配 CODE128（实拍标签解码取证：粒子码只有 Code 128）')
	equal(fakePlus.created[0].filters[0], 128, '过滤器就是 plus.barcode.CODE128')
	equal(
		resolveFilters({ barcode: { CODE128: 128 } }, ['CODE128', 'CODE39', 'EAN13']).length,
		1,
		'真要加码制时按存在的加，缺失的跳过'
	)
	equal(fakePlus.created[0].autoDecodeCharset, false, 'create 第 4 参 = autoDecodeCharset=false')
	equal(fakePlus.created[0].onmarked !== null, true, '已绑定 onmarked')
	equal(fakePlus.created[0].onerror !== null, true, '已绑定 onerror')

	const stats = scanner.getStats()
	equal(stats.createCount, 1, '统计：createCount = 1')
	equal(stats.appendCount, 1, '统计：appendCount = 1')
	equal(stats.startCount, 1, '统计：startCount = 1')
}

// ---------------------------------------------------------------------------
section('连续扫码：每识别一枚后重新 start（本轮核心修复）')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock, events } = buildScanner()
	await scanner.start()
	const target = fakePlus.created[0]

	target.onmarked(128, '82062330000110301748')
	await settle()
	equal(events.codes.length, 1, '第一枚码进入业务层')
	equal(scanner.getState(), ScannerState.PROCESSING, '处理中状态 = processing')
	await flushTimers(clock)
	equal(target.startCalls, 2, '处理完自动重新 start（第 2 次）')
	equal(scanner.getState(), ScannerState.SCANNING, '重新 start 后回到 scanning')

	target.onmarked(128, '82062330000110301749')
	await settle()
	await flushTimers(clock)
	target.onmarked(128, '82062330000110301750')
	await settle()
	await flushTimers(clock)

	equal(events.codes.length, 3, '连续 3 枚码全部进入业务层')
	equal(target.startCalls, 4, '1 次初始 + 3 次重启 = 4 次 start')
	equal(fakePlus.created.length, 1, '全过程只 create 一次（禁止每枚码重建）')
	equal(target.closeCalls, 0, '扫描过程中不 close')
}

// ---------------------------------------------------------------------------
section('瞬时防抖：同码在窗口内静默忽略（真机压测拍板 2500ms）')
// ---------------------------------------------------------------------------

{
	equal(INSTANT_DEBOUNCE_MS, 2500, '防抖窗口常量 = 2500ms（原 1200ms，压测后放宽）')

	const { scanner, fakePlus, clock, events } = buildScanner()
	await scanner.start()
	const target = fakePlus.created[0]
	const code = '82062330000110301748'

	target.onmarked(128, code)
	await settle()
	await flushTimers(clock)
	equal(events.codes.length, 1, '第一次识别进入业务层')

	clock.advance(400)
	target.onmarked(128, code)
	await settle()
	await flushTimers(clock)
	equal(events.codes.length, 1, '400ms 内同码被瞬时防抖挡下，不进业务层')
	equal(scanner.getStats().rapidDuplicateCount, 1, '统计：rapidDuplicateCount = 1')
	equal(target.startCalls, 3, '被挡下也照样继续扫描（不停摄像头）')

	clock.advance(1500)
	target.onmarked(128, code)
	await settle()
	await flushTimers(clock)
	equal(events.codes.length, 1, '累计 1900ms 仍在 2500ms 窗口内，继续静默忽略（这是压测后新放宽的部分）')

	clock.advance(900)
	target.onmarked(128, code)
	await settle()
	await flushTimers(clock)
	equal(events.codes.length, 2, '累计 2800ms 超过窗口后，同码重新进入业务层（交给本罐 Set / 跨罐报警兜底）')
}

// ---------------------------------------------------------------------------
section('业务失败不停摄像头（格式错 / 重复码 / 跨罐报警）')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock, events } = buildScanner({
		onCode: async (code) => {
			events.codes.push({ code })
			if (code === 'bad') throw new Error('业务处理炸了')
			// 与页面真实契约一致：拒绝时要给 reason，统计才归得了类
			return { accepted: false, reason: 'CURRENT_BATCH_DUPLICATE' }
		}
	})
	await scanner.start()
	const target = fakePlus.created[0]

	target.onmarked(128, 'bad')
	await settle()
	await flushTimers(clock)
	equal(events.errors.length, 1, '业务异常上报一次')
	equal(events.errors[0].stage, 'onmarked', '错误阶段标记为 onmarked')
	equal(target.startCalls, 2, '业务异常后仍然重新 start')
	equal(scanner.getState(), ScannerState.SCANNING, '业务异常后扫描器仍在跑')

	target.onmarked(128, '82062330000110301751')
	await settle()
	await flushTimers(clock)
	equal(scanner.getStats().rejectedCount, 1, '统计：被业务拒绝 1 枚')
	equal(scanner.getStats().rejectReasonCodes.CURRENT_BATCH_DUPLICATE, 1, '统计：原始原因码归类到 CURRENT_BATCH_DUPLICATE')
	equal(scanner.getStats().rejectReasons.businessDuplicate, 1, '统计：四桶里 businessDuplicate = 1')
	equal(target.startCalls, 3, '被拒绝的码同样不打断连续扫描')
}

// ---------------------------------------------------------------------------
section('重入保护：狂点按钮只创建一个控件')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus } = buildScanner()
	const first = await scanner.start()
	const second = await scanner.start()
	const third = await scanner.start()

	equal(first.ok, true, '第一次点击启动成功')
	equal(second.ok, false, '第二次点击被挡下')
	equal(second.reason, 'ALREADY_RUNNING', '挡下原因 = ALREADY_RUNNING')
	equal(third.reason, 'ALREADY_RUNNING', '第三次点击同样被挡下')
	equal(fakePlus.created.length, 1, '只创建 1 个 Barcode 对象')
}

// ---------------------------------------------------------------------------
section('识别过程报错：onerror 有日志、状态进 ERROR、可重新启动')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, events } = buildScanner()
	await scanner.start()
	const target = fakePlus.created[0]

	target.onerror({ code: 8, message: '取景失败' })
	equal(events.errors.length, 1, 'onerror 上报一次')
	equal(events.errors[0].stage, 'onerror', '错误阶段标记为 onerror')
	equal(scanner.getState(), ScannerState.ERROR, '状态进 ERROR')

	const again = await scanner.start()
	equal(again.ok, true, 'ERROR 之后还能重新启动')
	equal(fakePlus.created.length, 2, '重新启动会重新 create（不复用旧对象）')
}

// ---------------------------------------------------------------------------
section('释放与重启：cancel + close，页面退出不留原生层')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock } = buildScanner()
	await scanner.start()
	const first = fakePlus.created[0]

	await scanner.stop('onHide')
	equal(first.cancelCalls, 1, 'stop 调用 cancel（关摄像头）')
	equal(first.closeCalls, 1, 'stop 调用 close（释放控件）')
	equal(first.onmarked, null, 'stop 后解绑 onmarked')
	equal(first.onerror, null, 'stop 后解绑 onerror')
	equal(scanner.getState(), ScannerState.IDLE, 'stop 后状态 = idle')
	equal(scanner.isActive(), false, 'stop 后 active = false')

	// 退出后重新进入：必须重新 create + append + start
	const { scanner: scanner2, fakePlus: plus2 } = buildScanner()
	await scanner2.start()
	equal(plus2.created.length, 1, '再次进入重新 create 一个全新控件')

	// 停止后残留的定时器不得再启动摄像头
	await flushTimers(clock)
	equal(first.startCalls, 1, '停止后定时器不会再 start')

	const noop = await scanner.stop()
	equal(noop.ok, true, '重复 stop 不抛异常')
}

// ---------------------------------------------------------------------------
section('权限与环境异常：明确失败，不改变页面业务模式')
// ---------------------------------------------------------------------------

{
	const denied = buildScanner({ ensurePermission: async () => false })
	const deniedResult = await denied.scanner.start()
	equal(deniedResult.ok, false, '权限被拒 → 启动失败')
	equal(deniedResult.reason, 'CAMERA_PERMISSION_DENIED', '失败原因 = CAMERA_PERMISSION_DENIED')
	equal(denied.fakePlus.created.length, 0, '权限没拿到就不 create 控件')
	equal(denied.scanner.getState(), ScannerState.ERROR, '状态进 ERROR（页面可提示重试）')

	const noPlus = buildScanner({ plus: 'missing' })
	const noPlusResult = await noPlus.scanner.start()
	equal(noPlusResult.ok, false, '没有 plus 环境 → 启动失败')
	equal(noPlusResult.reason, 'PLUS_UNAVAILABLE', '失败原因 = PLUS_UNAVAILABLE')

	const noModule = buildScanner({ plus: 'no-barcode' })
	const noModuleResult = await noModule.scanner.start()
	equal(noModuleResult.reason, 'PLUS_BARCODE_UNAVAILABLE', '缺 Barcode 模块 → PLUS_BARCODE_UNAVAILABLE')

	const noWebview = buildScanner({ options: { getWebview: () => { throw new Error('APP_WEBVIEW_UNAVAILABLE') } } })
	const noWebviewResult = await noWebview.scanner.start()
	equal(noWebviewResult.ok, false, '取不到 Webview → 启动失败')
	check(noWebview.fakePlus.created.length === 0, '取不到 Webview 时不会留下野控件')
}

// ---------------------------------------------------------------------------
section('五维统计与拒绝原因归类（rejectReasons 四个桶）')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock } = buildScanner({
		onCode: async (code) => {
			if (code === 'bad-char') return { accepted: false, reason: 'INVALID_FORMAT' }
			if (code === 'dup') return { accepted: false, reason: 'CURRENT_BATCH_DUPLICATE' }
			if (code === 'cross') return { accepted: false, reason: 'CROSS_CONTAINER_DUPLICATE' }
			if (code === 'weird') return { accepted: false, reason: 'SOMETHING_ELSE' }
			return { accepted: true }
		}
	})
	await scanner.start()
	const target = fakePlus.created[0]

	for (const code of ['ok-1', 'bad-char', 'dup', 'cross', 'weird']) {
		target.onmarked(128, code)
		await settle()
		await flushTimers(clock)
	}
	// 再补一次同码瞬时重复
	clock.advance(100)
	target.onmarked(128, 'ok-2')
	await settle()
	await flushTimers(clock)
	target.onmarked(128, 'ok-2')
	await settle()
	await flushTimers(clock)

	const stats = scanner.getStats()
	equal(stats.rejectReasons.instantIgnore, 1, '四桶：instantIgnore = 1（同码瞬时忽略）')
	equal(stats.rejectReasons.businessDuplicate, 2, '四桶：businessDuplicate = 2（本罐重复 + 跨罐重复）')
	equal(stats.rejectReasons.invalidChar, 1, '四桶：invalidChar = 1（格式不合法）')
	equal(stats.rejectReasons.unknown, 1, '四桶：unknown = 1（其它 reason）')
	equal(stats.rejectReasonCodes.CURRENT_BATCH_DUPLICATE, 1, '原始原因码仍保留（诊断用）')
	equal(stats.acceptedCount, 2, '入库 2 枚（ok-1 / ok-2）')
}

// ---------------------------------------------------------------------------
section('逐枚耗时：成功入库时间戳 → intervalMs / 平均 / 最大 / 最小')
// ---------------------------------------------------------------------------

{
	// 只有以 8206233 开头的码算入库，其余一律拒绝 —— 用来验证「被拒绝的码不进采样点」
	const { scanner, fakePlus, clock } = buildScanner({
		onCode: async (code) =>
			code.startsWith('8206233') ? { accepted: true } : { accepted: false, reason: 'INVALID_FORMAT' }
	})
	await scanner.start()
	const target = fakePlus.created[0]

	const gaps = [4000, 6000, 5000]
	for (let index = 0; index < gaps.length; index += 1) {
		if (index > 0) clock.advance(gaps[index - 1])
		target.onmarked(128, `820623300001103017${index}0`)
		await settle()
		await flushTimers(clock)
	}

	const timing = scanner.getTiming()
	equal(timing.count, 3, '采样点 = 3 枚成功入库')
	equal(timing.intervals.length, 2, '间隔数 = 2')
	equal(timing.intervals.join(','), '4000,6000', 'intervalMs 数组正确：4000 / 6000')
	equal(timing.totalMs, 10000, '总耗时 = 10 秒')
	equal(timing.avgMs, 5000, '平均间隔 = 5 秒')
	equal(timing.minMs, 4000, '最小间隔 = 4 秒')
	equal(timing.maxMs, 6000, '最大间隔 = 6 秒')
	equal(scanner.getStats().timing.avgMs, 5000, 'getStats() 里也带 timing（面板要用）')

	// 被拒绝的码不进采样点
	const before = scanner.getTiming().count
	clock.advance(1000)
	target.onmarked(128, 'x')
	await settle()
	await flushTimers(clock)
	equal(scanner.getTiming().count, before, '被拒绝的码不计入逐枚耗时采样')
}

// ---------------------------------------------------------------------------
section('盲区分档：入库 200ms / 业务拒绝 120ms / 瞬时忽略 60ms（漏扫主因修复）')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock } = buildScanner({
		onCode: async (code) => (code === 'bad' ? { accepted: false, reason: 'INVALID_FORMAT' } : { accepted: true })
	})
	await scanner.start()
	const target = fakePlus.created[0]

	target.onmarked(128, 'code-a')
	await settle()
	equal(clock.lastDelay(), 200, '入库成功 → 等 200ms（留时间给 UI / 震动 / 落盘）')
	await flushTimers(clock)

	target.onmarked(128, 'bad')
	await settle()
	equal(clock.lastDelay(), 120, '业务拒绝 → 只等 120ms（没写库，尽快恢复取景）')
	await flushTimers(clock)

	// 同一枚码再报一次 → 瞬时忽略，用最短的 60ms
	clock.advance(3000)
	target.onmarked(128, 'code-a')
	await settle()
	await flushTimers(clock)
	target.onmarked(128, 'code-a')
	await settle()
	equal(clock.lastDelay(), 60, '瞬时忽略 → 只等 60ms（同一枚码还在镜头里，越早恢复越好）')
	await flushTimers(clock)

	const restartStats = scanner.getStats()
	equal(restartStats.rapidDuplicateCount, 1, '那一枚确实走了瞬时忽略分支')
}

// ---------------------------------------------------------------------------
section('提示音开关：每轮 start 都取最新设置（可随时取消）')
// ---------------------------------------------------------------------------

{
	let soundOn = true
	const { scanner, fakePlus, clock } = buildScanner({
		options: { getFeedback: () => ({ vibrate: true, sound: soundOn ? 'default' : 'none' }) }
	})
	await scanner.start()
	const target = fakePlus.created[0]
	equal(target.lastOptions.sound, 'default', '默认开着提示音')
	equal(target.lastOptions.vibrate, true, '震动一直保留')

	soundOn = false
	target.onmarked(128, '82062330000110301700')
	await settle()
	await flushTimers(clock)
	equal(target.lastOptions.sound, 'none', '关掉之后，下一轮 start 立刻用 sound=none（不必重启扫码器）')
}

// ---------------------------------------------------------------------------
section('收工落盘：onRunSummary 带回本轮统计')
// ---------------------------------------------------------------------------

{
	const captured = []
	const { scanner, fakePlus, clock } = buildScanner({
		options: {
			onRunSummary: (summary, reason) => captured.push({ summary, reason })
		}
	})
	await scanner.start()
	fakePlus.created[0].onmarked(128, '82062330000110301700')
	await settle()
	await flushTimers(clock)
	clock.advance(3000)
	fakePlus.created[0].onmarked(128, '82062330000110301701')
	await settle()
	await flushTimers(clock)
	await scanner.stop('onUnload')

	equal(captured.length, 1, '收工时回调一次')
	equal(captured[0].reason, 'onUnload', '回调带上了退出原因')
	equal(captured[0].summary.timing.count, 2, '回调里含逐枚耗时采样点')
	equal(captured[0].summary.rejectReasons.instantIgnore, 0, '回调里含四桶原因分布')
	equal(captured[0].summary.markedCount, 2, '回调里含识别总数')
}

// ---------------------------------------------------------------------------
section('状态机迁移序列')
// ---------------------------------------------------------------------------

{
	const { scanner, fakePlus, clock, events } = buildScanner()
	await scanner.start()
	fakePlus.created[0].onmarked(128, '82062330000110301751')
	await settle()
	await flushTimers(clock)
	await scanner.stop()

	equal(
		events.states.join(' | '),
		'idle->starting | starting->scanning | scanning->processing | processing->scanning | scanning->stopping | stopping->idle',
		'完整状态序列：idle→starting→scanning→processing→scanning→stopping→idle'
	)
}

// ---------------------------------------------------------------------------
section('工具函数：filters 解析与 Webview 兜底')
// ---------------------------------------------------------------------------

{
	const plusLike = { barcode: { CODE128: 128, EAN13: 13 } }
	const filters = resolveFilters(plusLike, ['CODE128', 'CODE39', 'EAN13'])
	equal(filters.length, 2, '缺失的码制被跳过，不塞 undefined')
	equal(filters.join(','), '128,13', '只保留真实存在的码制常量')
	equal(resolveFilters({ barcode: {} }, ['QR']).length, 0, '一个都没有时返回空数组（create 会自己报错）')

	// getCurrentAppWebview：页面栈优先，currentWebview 兜底
	const fakeWebview = { name: 'wv' }
	globalThis.getCurrentPages = () => [{ $getAppWebview: () => fakeWebview }]
	equal(getCurrentAppWebview(), fakeWebview, '从页面栈取到 App Webview')

	globalThis.getCurrentPages = () => [{}, {}]
	globalThis.plus = { webview: { currentWebview: () => fakeWebview } }
	equal(getCurrentAppWebview(), fakeWebview, '页面栈拿不到时退回 plus.webview.currentWebview()')

	globalThis.getCurrentPages = () => []
	globalThis.plus = { webview: { currentWebview: () => null } }
	let threw = ''
	try {
		getCurrentAppWebview()
	} catch (error) {
		threw = error.message
	}
	equal(threw, 'APP_WEBVIEW_UNAVAILABLE', '都拿不到时抛 APP_WEBVIEW_UNAVAILABLE')
	delete globalThis.getCurrentPages
	delete globalThis.plus
}

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`批量连续扫码启动链单测全部通过（${passed} 项）。`)
process.exit(0)
