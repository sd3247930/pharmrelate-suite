<template>
	<view class="page">
		<!-- 顶部：当前任务（数据全部来自本机，断网也在） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">当前任务</text>
				<text :class="['badge', statusClass]">{{ statusLabel }}</text>
			</view>
			<view v-if="!batch" class="empty">
				<text class="hint">本机还没有批次。请先到「设置」填写批次基础信息并配置包装结构。</text>
				<button class="primary" @click="go('settings')">去设置建批次</button>
				<text class="hint">建好批次回到这一页，就能用下面的「打开摄像头」按钮扫码了。</text>
			</view>
			<template v-else>
				<view class="facts">
					<view class="fact">
						<text class="fact-key">批号</text>
						<text class="fact-value code">{{ batch.batchNo }}</text>
					</view>
					<view class="fact">
						<text class="fact-key">箱</text>
						<text class="fact-value code">{{ wizard.actualBoxes }} / {{ wizard.totalBoxes }}</text>
					</view>
					<view class="fact">
						<text class="fact-key">罐</text>
						<text class="fact-value code">{{ wizard.actualCans }} / {{ wizard.totalCans }}</text>
					</view>
					<view class="fact">
						<text class="fact-key">本罐粒子</text>
						<text class="fact-value code">{{ currentCanScanned }} / {{ currentCanPlanned }}</text>
					</view>
					<view class="fact">
						<text class="fact-key">总计</text>
						<text class="fact-value code">{{ wizard.actualParticles }} / {{ wizard.plannedParticles }}</text>
					</view>
					<view class="fact">
						<text class="fact-key">当前</text>
						<text class="fact-value code">
							箱 {{ wizard.boxIndex }} · 罐 {{ wizard.canIndex }}（本箱 {{ wizard.cansInBox }} 罐）
						</text>
					</view>
				</view>
				<view class="progress">
					<view class="progress-bar" :style="{ width: progressPercent + '%' }"></view>
				</view>
			</template>
		</view>

		<!-- 拦截 / 报警：颜色 + 文字，颜色不是唯一线索 -->
		<view v-if="event && event.needsAlarm" class="alarm alarm-error">
			<text class="alarm-title">{{ event.label }}</text>
			<text class="alarm-body">{{ event.message }}</text>
		</view>
		<view v-else-if="event" class="alarm alarm-ok">
			<text class="alarm-title">{{ event.label }}</text>
			<text class="alarm-body">{{ event.message }}</text>
		</view>

		<!-- 引导式向导（严格 1 → 2 → 3，多箱循环，不能跳步） -->
		<view v-if="batch" class="card">
			<view class="row-between">
				<text class="card-title">采集向导</text>
				<text class="badge badge-info">步骤 {{ wizard.step }} / 3</text>
			</view>
			<text class="hint">{{ wizard.prompt }}</text>

			<view class="step-row">
				<view :class="['step-dot', wizard.step >= 1 ? 'on' : '']"><text>1 箱号</text></view>
				<view :class="['step-dot', wizard.step >= 2 ? 'on' : '']"><text>2 罐号+粒子</text></view>
				<view :class="['step-dot', wizard.step >= 3 ? 'on' : '']"><text>3 整体核对</text></view>
			</view>

			<!-- 阶段 1 验收点：扫码是这个页面上最显眼的主按钮，直接调摄像头 -->
			<view v-if="wizard.phase === 'box'" class="actions">
				<button class="primary scan-btn" :disabled="busy" @click="scanBox">
					① 📷 扫描箱号条形码（第 {{ wizard.boxIndex }} / {{ wizard.totalBoxes }} 箱）
				</button>
				<button class="secondary" :disabled="busy" @click="capturePhoto('box')">② 🖼 拍照识别箱号</button>
				<button class="ghost" :disabled="busy" @click="toggleManual">
					③ ⌨ {{ manualOpen ? '收起手动输入箱号' : '手动输入箱号' }}
				</button>
				<view v-if="manualOpen" class="manual-box">
					<text class="hint">
						箱号在实物上是一维条形码，需为 20 位数字且前缀 8021761。输入框只在点开这一步时才聚焦。
					</text>
					<input
						class="input code"
						v-model="manualValue"
						:focus="manualFocus"
						placeholder="请输入 20 位箱号（前缀 8021761）"
						confirm-type="done"
						@confirm="submitManualLayer"
					/>
					<button class="primary" :disabled="busy" @click="submitManualLayer">确认箱号</button>
				</view>
			</view>
			<view v-else-if="wizard.phase === 'can'" class="actions">
				<button class="primary scan-btn" :disabled="busy" @click="scanCan">
					① 📷 扫描罐号方形码（箱 {{ wizard.boxIndex }} 罐 {{ wizard.canIndex }}）
				</button>
				<button class="ghost" :disabled="busy" @click="scanCan">重拍</button>
				<button class="secondary" :disabled="busy" @click="capturePhoto('can')">
					② 🖼 拍照识别罐号
				</button>
				<button class="ghost" :disabled="busy" @click="toggleManual">
					③ ⌨ {{ manualOpen ? '收起手动输入罐号' : '手动输入罐号' }}
				</button>
				<view v-if="manualOpen" class="manual-box">
					<text class="hint">
						罐号在实物上是方形二维码，需为 20 位数字且前缀 8021762；标签上印的连字符会在入库前自动去掉。输入框只在点开这一步时才聚焦。
					</text>
					<input
						class="input code"
						v-model="manualValue"
						:focus="manualFocus"
						placeholder="请输入 20 位罐号（前缀 8021762）"
						confirm-type="done"
						@confirm="submitManualLayer"
					/>
					<button class="primary" :disabled="busy" @click="submitManualLayer">确认罐号</button>
				</view>
			</view>
			<view v-else-if="wizard.phase === 'particle'" class="actions">
				<button class="primary scan-btn" :disabled="busy" @click="scanParticle">
					📷 打开摄像头拍粒子（{{ currentCanScanned }}/{{ currentCanPlanned }}）
				</button>
			</view>
			<view v-else-if="wizard.phase === 'can_review'" class="actions">
				<button class="primary" :disabled="busy" @click="confirmCanDone">本罐确认无误</button>
				<button class="ghost" :disabled="busy" @click="notYet">还没好，继续拍</button>
			</view>
			<view v-else-if="wizard.phase === 'box_review'" class="actions">
				<template v-if="wizard.isLastBox">
					<button class="primary" :disabled="busy" @click="finishLastBox">开始整体核对</button>
				</template>
				<template v-else>
					<button class="primary" :disabled="busy" @click="nextBox">继续拍下一箱</button>
					<button class="ghost" :disabled="busy" @click="endWholeBatch">结束并核对</button>
				</template>
			</view>
			<view v-else-if="wizard.phase === 'review'" class="actions">
				<button class="primary" :disabled="busy" @click="runReview">开始整体核对</button>
			</view>

			<text class="hint">
				箱号 = 一维条形码（前缀 8021761）；罐号 = 方形二维码（前缀 8021762），标签上的连字符自动清洗；粒子 = 20 位条码（前缀 8206233）。多码、错层、重复、溢出都会震动报警。
				现场没有条码或字迹不清时，用「拍照识别」把画面拍下来照着输入，或用「手动输入」直接键入。
			</text>
			<text v-if="cameraHint" class="alarm-hint">{{ cameraHint }}</text>
			<text v-if="batch.finishRequested" class="alarm-hint">
				已结束剩余箱/罐拍摄 —— 缺漏会在核对里如实显示，需要到「状态」页办提前结束签名。
			</text>
		</view>

		<!-- 槽位编辑：箱 → 罐 两级分组；替换 / 删除 / 撤销 / 重做（撤销栈 50） -->
		<view v-if="batch && slotRows.length" class="card">
			<view class="row-between">
				<text class="card-title">槽位（按采集顺序）</text>
				<text class="hint">撤销栈 {{ history.undoCount }}/{{ history.limit }}</text>
			</view>
			<view v-for="box in slotRows" :key="box.boxIndex" class="box-group">
				<view class="row-between box-head">
					<text class="box-title">箱 {{ box.boxIndex }}</text>
					<text class="hint code">{{ box.boxCode || '（未扫箱号）' }}</text>
				</view>
				<view v-for="row in box.cans" :key="row.canIndex" class="slot-row">
					<text class="slot-can">罐 {{ row.canIndex }}</text>
					<text class="slot-can-code code">{{ row.canCode || '（未扫罐号）' }}</text>
					<view class="slot-grid">
						<view
							v-for="slot in row.slots"
							:key="slot.index"
							:class="['slot', slot.code ? 'filled' : 'empty']"
							@click="openSlot(box.boxIndex, row.canIndex, slot.index)"
						>
							<text class="slot-index">{{ slot.index + 1 }}</text>
							<text class="slot-code code">{{ slot.code ? slot.code.slice(-6) : '空' }}</text>
						</view>
					</view>
				</view>
			</view>
			<view class="actions">
				<button class="secondary" :disabled="busy || !history.canUndo" @click="doUndo">撤销</button>
				<button class="ghost" :disabled="busy || !history.canRedo" @click="doRedo">重做</button>
			</view>
		</view>

		<!-- 手动输入兜底：默认折叠，点开才展开（避免空批次时被当成扫码框） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">手动输入（条码枪 / 粘贴）</text>
				<text class="badge badge-neutral">{{ pasteOpen ? '已展开' : '已折叠' }}</text>
			</view>
			<text class="hint">
				箱号 / 罐号请用上面的向导卡片（扫码 · 拍照识别 · 手动输入）。这一张留给条码枪与整段粘贴。
			</text>
			<button class="secondary" @click="pasteOpen = !pasteOpen">
				{{ pasteOpen ? '收起手动输入' : '展开手动输入条码' }}
			</button>
			<template v-if="pasteOpen">
				<input
					class="input code"
					v-model="pasteCode"
					placeholder="粘贴或输入条码，回车提交"
					confirm-type="done"
					@confirm="submitPaste"
				/>
				<button class="secondary" :disabled="busy || !batch" @click="submitPaste">提交</button>
				<text class="hint">支持空格或逗号分隔一次输入多个粒子码；条码枪以回车结尾会自动提交。</text>
			</template>
		</view>

		<!-- 本机与连接状态（离线不阻塞） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">连接</text>
				<text class="badge badge-neutral">{{ healthOk ? '已连接' : '离线模式' }}</text>
			</view>
			<text class="hint">本期采集不需要联网，数据保存在本机（{{ localId || '尚无本地批次' }}）。</text>
			<button class="ghost" :disabled="busy" @click="checkServer">查看主控机是否在线</button>
		</view>

		<!-- 槽位操作浮层 -->
		<view v-if="editing" class="overlay">
			<view class="sheet">
				<text class="sheet-title">
					箱 {{ editing.boxIndex + 1 }} · 罐 {{ editing.canIndex + 1 }} · 槽位 {{ editing.slotIndex + 1 }}
				</text>
				<text class="hint code">{{ editing.code || '（空）' }}</text>
				<input class="input code" v-model="replaceValue" placeholder="输入新的粒子码做替换" />
				<button class="primary" :disabled="busy" @click="doReplace">替换</button>
				<button class="danger" :disabled="busy" @click="doDelete">删除该槽位</button>
				<button class="ghost" @click="editing = null">取消</button>
			</view>
		</view>

		<!-- 拍照识别：识别失败/无识别引擎时的降级浮层（人工读数后用下框输入；照片用完即弃） -->
		<view v-if="photo" class="overlay">
			<view class="sheet">
				<view class="row-between">
					<text class="sheet-title">{{ photo.kind === 'box' ? '拍照识别箱号' : '拍照识别罐号' }}</text>
					<text class="badge badge-neutral">{{ photo.recognizing ? '识别中' : '人工确认' }}</text>
				</view>
				<text v-if="photo.recognizing" class="hint">正在识别…（本机没有识别引擎时会立刻降级为人工读数）</text>
				<text class="hint">
					本机暂无自动识别能力 / 识别不确定，请人工读数并输入：照着照片把数字看清楚，
					再点下面的按钮进输入框键入（识别只负责「看见什么数字」，上限与查重由业务层判断）。
				</text>
				<scroll-view scroll-y class="photo-wrap">
					<image
						class="photo"
						:src="photo.path"
						mode="aspectFit"
						:style="{ transform: 'rotate(' + photo.rotate + 'deg) scale(' + photo.scale + ')' }"
					/>
				</scroll-view>
				<view class="actions">
					<button class="secondary" @click="zoomPhoto(0.25)">放大</button>
					<button class="secondary" @click="zoomPhoto(-0.25)">缩小</button>
					<button class="secondary" @click="rotatePhoto">旋转 90°</button>
					<button class="secondary" @click="resetPhoto">复位</button>
				</view>
				<button class="primary" :disabled="busy" @click="goManualFromPhoto">
					照着照片输入{{ photo.kind === 'box' ? '箱号' : '罐号' }}
				</button>
				<button class="ghost" :disabled="busy" @click="capturePhoto(photo.kind)">重拍</button>
				<button class="ghost" :disabled="busy" @click="photo = null">取消</button>
			</view>
		</view>
	</view>
</template>

<script>
import { api } from '../../services/api'
import { recognizeNumber } from '../../services/numberRecognizer'
import { ensureDefaults } from '../../services/store'
import {
	ALARM_EVENTS,
	CODE_PREFIXES,
	EVENT,
	EVENT_LABELS,
	PHASE,
	STATUS_LABELS,
	applyCodes,
	cleanLayerCode,
	confirmBoxReview,
	confirmCanReview,
	deleteSlot,
	deriveWizard,
	describeCodeIssue,
	finishRemaining,
	findCan,
	findUsage,
	getActiveBatch,
	historyState,
	redo,
	replaceSlot,
	review,
	saveBatch,
	transition,
	undo
} from '../../services/localBatch'

/** 页面自有事件码的中文标题（数据层那套 EVENT_LABELS 之外的部分）。 */
const LOCAL_EVENT_LABELS = {
	ERROR: '出错了',
	RETRY: '已放弃',
	PHOTO: '照片已拍好',
	MANUAL: '手动输入',
	EDIT: '需要修改'
}

/**
 * 页面级事件：label 用中文（以前直接拿 code 当标题，界面上会冒「MULTI_CODE」这种原始码）。
 * needsAlarm 不传时按数据层的报警清单自动判定，避免漏震动。
 */
function eventOf(code, message, needsAlarm) {
	return {
		code,
		label: EVENT_LABELS[code] || LOCAL_EVENT_LABELS[code] || code,
		message,
		needsAlarm: typeof needsAlarm === 'boolean' ? needsAlarm : ALARM_EVENTS.indexOf(code) >= 0
	}
}

export default {
	data() {
		return {
			batch: null,
			wizard: {
				step: 1,
				phase: PHASE.BOX,
				boxIndex: 1,
				canIndex: 1,
				totalBoxes: 0,
				totalCans: 0,
				cansInBox: 0,
				isLastBox: true,
				plannedParticles: 0,
				actualBoxes: 0,
				actualCans: 0,
				actualParticles: 0,
				prompt: ''
			},
			history: { canUndo: false, canRedo: false, undoCount: 0, redoCount: 0, limit: 50 },
			event: null,
			busy: false,
			// 步骤 1 / 2.1 的「手动输入箱号/罐号」面板（默认折叠、只有点开才聚焦）
			manualOpen: false,
			manualFocus: false,
			manualValue: '',
			// 页面下方「手动输入（条码枪 / 粘贴）」兜底卡片
			pasteOpen: false,
			pasteCode: '',
			// 拍照识别：{ path, kind, rotate, scale }，只用于当场核对，不落本机
			photo: null,
			cameraHint: '',
			editing: null,
			replaceValue: '',
			healthOk: false,
			localId: ''
		}
	},

	computed: {
		statusLabel() {
			if (!this.batch) return '未建批次'
			return STATUS_LABELS[this.batch.status] || this.batch.status
		},
		statusClass() {
			if (!this.batch) return 'badge-neutral'
			if (this.batch.status === 'collecting') return 'badge-info'
			if (this.batch.status === 'pending_review') return 'badge-warn'
			if (this.batch.status === 'verified') return 'badge-ok'
			return 'badge-neutral'
		},
		currentCan() {
			if (!this.batch) return null
			return findCan(this.batch, this.wizard.boxIndex, this.wizard.canIndex)
		},
		currentCanScanned() {
			if (!this.currentCan) return 0
			return (this.currentCan.particles || []).filter((code) => !!code).length
		},
		currentCanPlanned() {
			return this.currentCan ? this.currentCan.plannedParticleCount : 0
		},
		progressPercent() {
			if (!this.wizard.plannedParticles) return 0
			const percent = (this.wizard.actualParticles / this.wizard.plannedParticles) * 100
			return Math.min(100, Math.round(percent * 10) / 10)
		},
		/** 槽位按「箱 → 罐」两级分组。 */
		slotRows() {
			if (!this.batch) return []
			return (this.batch.boxes || []).map((box, bIndex) => ({
				boxIndex: bIndex + 1,
				boxCode: box.boxCode,
				cans: (box.cans || []).map((can, cIndex) => ({
					canIndex: cIndex + 1,
					canCode: can.canCode,
					slots: (can.particles || []).map((code, sIndex) => ({ index: sIndex, code }))
				}))
			}))
		}
	},

	onShow() {
		ensureDefaults()
		this.reload()
	},

	methods: {
		/** 每次都从本机存储读回来（断网也一样）。 */
		reload() {
			this.batch = getActiveBatch()
			this.localId = this.batch ? this.batch.localId : ''
			this.wizard = this.batch
				? deriveWizard(this.batch)
				: Object.assign({}, this.wizard, {
						step: 1,
						phase: PHASE.BOX,
						boxIndex: 1,
						canIndex: 1,
						totalBoxes: 0,
						totalCans: 0,
						cansInBox: 0,
						isLastBox: true,
						plannedParticles: 0,
						actualBoxes: 0,
						actualCans: 0,
						actualParticles: 0,
						prompt: '请先建批次'
					})
			this.history = historyState(this.batch || {})
		},

		/** 统一处理本地状态机的结果：报警就震动 + 显示，成功就落盘。 */
		handle(result) {
			if (result.event) {
				this.event = result.event
				if (result.event.needsAlarm) uni.vibrateLong()
			}
			if (result.batch) {
				saveBatch(result.batch)
				this.reload()
			}
		},

		alarm(event) {
			this.event = event
			uni.vibrateLong()
		},

		go(page) {
			uni.switchTab({ url: `/pages/${page}/${page}` })
		},

		/**
		 * 链式弹窗：在上一个 showModal 的 success 回调里直接再调一次 showModal，
		 * H5 与 App 上第二个弹窗会拿到 DOM 却显示不出来（被上一个的隐藏动画吃掉），
		 * 表现为「向导卡住、等不到下一步提示」。统一延后一拍再弹。
		 */
		chainModal(options) {
			setTimeout(() => uni.showModal(options), 320)
		},

		/**
		 * 阶段 1 的关键改造：调 uni.scanCode 之前先动态申请相机权限。
		 * 荣耀/小米/OPPO/VIVO 上基座的相机权限被拒过时，scanCode 会直接失败，
		 * 这里提前拦住并给出「去系统设置开权限」的引导。
		 */
		ensureCamera() {
			// #ifdef APP-PLUS
			return new Promise((resolve) => {
				let settled = false
				const finish = (value) => {
					if (settled) return
					settled = true
					resolve(value)
				}
				try {
					plus.android.requestPermissions(
						['android.permission.CAMERA'],
						(result) => {
							const denied = (result.deniedPresent || []).concat(result.deniedAlways || [])
							if (denied.length) {
								this.cameraDenied()
								finish(false)
								return
							}
							finish(true)
						},
						() => {
							this.cameraDenied()
							finish(false)
						}
					)
				} catch (error) {
					// 拿不到 plus 环境（例如 H5 预览）时不要卡住流程，交给 scanCode 自己报错
					finish(true)
				}
				// 部分 ROM 的回调可能不回来，兜底放行，避免按钮永远点不动
				setTimeout(() => finish(true), 1500)
			})
			// #endif
			// #ifndef APP-PLUS
			return Promise.resolve(true)
			// #endif
		},

		/** 相机权限被拒：明确告知 + 一键跳系统设置。 */
		cameraDenied() {
			this.cameraHint = '需要相机权限：请在系统设置里允许本应用使用相机。'
			uni.showModal({
				title: '需要相机权限',
				content: '扫码要用摄像头。请在系统设置 → 应用 → 本应用 → 权限里允许「相机」，再回来重试。',
				confirmText: '去设置',
				cancelText: '稍后',
				success: (res) => {
					if (res.confirm) this.openAppSettings()
				}
			})
		},

		/** 跳到本应用的系统详情页（权限在那里改）。 */
		openAppSettings() {
			// #ifdef APP-PLUS
			try {
				const main = plus.android.runtimeMainActivity()
				const Intent = plus.android.importClass('android.content.Intent')
				const Settings = plus.android.importClass('android.provider.Settings')
				const Uri = plus.android.importClass('android.net.Uri')
				const intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
				intent.setData(Uri.fromParts('package', main.getPackageName(), null))
				main.startActivity(intent)
				return
			} catch (error) {
				// 落到下面的提示
			}
			// #endif
			uni.showToast({ title: '请到系统设置 → 应用 → 权限 里开启相机', icon: 'none' })
		},

		/**
		 * 调摄像头扫一个码。scanType 由调用方指定：箱号只认一维条形码、
		 * 罐号只认方形二维码、粒子只认条形码。
		 * 注意：部分国产 ROM 的基座会忽略 scanType 直接返回扫到的任意码，
		 * 所以「扫错类型」的最终拦截靠业务层的 20 位 + 前缀校验（describeCodeIssue）。
		 */
		scanCode(scanType, callback) {
			uni.scanCode({
				onlyFromCamera: true,
				scanType,
				success: (result) => {
					this.cameraHint = ''
					callback(result.result)
				},
				fail: (error) => {
					const message = (error && error.errMsg) || '扫码失败'
					if (/cancel/i.test(message)) return // 用户自己取消：不打扰
					if (/permission|denied|auth|not allowed/i.test(message)) {
						this.cameraDenied()
						return
					}
					this.event = eventOf('ERROR', `扫码未成功：${message}`, false)
				}
			})
		},

		/** 阶段 4：扫箱号（一维条形码；多箱循环，文案带第 X / 共 Y 箱）。 */
		async scanBox() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.BOX) return
			if (!(await this.ensureCamera())) return
			this.scanCode(['barCode'], (code) => this.considerSingle(code, 'box'))
		},

		/** 阶段 1 / 4：扫罐号（方形二维码）。 */
		async scanCan() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.CAN) return
			if (!(await this.ensureCamera())) return
			this.scanCode(['qrCode'], (code) => this.considerSingle(code, 'can'))
		},

		/** 阶段 2.2：粒子逐个扫码（C2：本期不做多码拍照）。 */
		async scanParticle() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.PARTICLE) return
			if (!(await this.ensureCamera())) return
			this.scanCode(['barCode'], (code) => this.handle(applyCodes(this.batch, [code])))
		},

		/**
		 * 业务层收口（识别层之外唯一的写入路径）：清洗 → 20 位 + 前缀校验 → 分层查重 → 写本地数据层。
		 * 这里再清洗一次是兜底：拍照识别通道会绕过 considerSingle 直接调进来。
		 */
		commitLayerCode(rawCode, kind) {
			if (!this.batch) return false
			const wizard = deriveWizard(this.batch)
			const expected = kind === 'box' ? 3 : 2
			const code = cleanLayerCode(rawCode, expected)
			if (wizard.phase !== (kind === 'box' ? PHASE.BOX : PHASE.CAN)) {
				this.event = eventOf(EVENT.WRONG_STATE, '步骤已经变了，请按当前提示操作。', false)
				return false
			}
			const label = kind === 'box' ? '箱号' : '罐号'
			const issue = describeCodeIssue(code, expected)
			if (issue) {
				uni.showModal({ title: `${label}格式不对`, content: issue, showCancel: false })
				return false
			}
			const used =
				kind === 'box'
					? findUsage(this.batch, code, 3, { excludeBoxIndex: wizard.boxIndex - 1 })
					: findUsage(this.batch, code, 2, { boxIndex: wizard.boxIndex - 1, excludeCanIndex: wizard.canIndex - 1 })
			if (used) {
				this.alarm(eventOf(EVENT.DUPLICATE_CODE, `${label} ${code} 已被使用于「${used.where}」，请勿重复录入。`, true))
				return false
			}
			this.handle(applyCodes(this.batch, [code]))
			if (this.manualOpen) {
				this.manualOpen = false
				this.manualFocus = false
				this.manualValue = ''
			}
			uni.showToast({ title: `已记录${label}`, icon: 'success' })
			return true
		},

		/**
		 * 扫码 / 手动输入 / 拍照识别三条通道的统一收口。
		 * 清洗放在最前面：罐号二维码内容带连字符（如 8021762-9000000001003），
		 * 必须在校验与弹窗之前剥掉，才能保证「弹窗显示什么，库里就存什么」。
		 */
		considerSingle(rawCode, kind) {
			const wizard = deriveWizard(this.batch)
			const expected = kind === 'box' ? 3 : 2
			const label = kind === 'box' ? '箱号' : '罐号'
			const code = cleanLayerCode(rawCode, expected)
			const issue = describeCodeIssue(code, expected)
			if (issue) {
				uni.showModal({ title: `${label}格式不对`, content: issue, showCancel: false })
				return
			}
			const prefix = CODE_PREFIXES[expected]
			uni.showModal({
				title:
					kind === 'box'
						? `这是第 ${wizard.boxIndex} 箱的箱号吗？(${prefix}...)`
						: `这是箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 号吗？(${prefix}...)`,
				content: code,
				confirmText: '是',
				cancelText: '否',
				success: (res) => {
					if (!res.confirm) {
						this.event = eventOf('RETRY', `已放弃 ${code}，请重拍或重新输入${label}。`, false)
						this.manualValue = ''
						return
					}
					this.commitLayerCode(code, kind)
				}
			})
		},

		/**
		 * 识别通道（Provider 返回 success:true）：确认框里展示 number 与 confidence，
		 * [是] 之后仍然走**业务层**校验与写入（识别层不做业务判断）。
		 */
		confirmRecognizedNumber(kind, result) {
			const wizard = this.wizard
			const label = kind === 'box' ? '箱号' : '罐号'
			const confidence = Number(result.confidence || 0).toFixed(2)
			const warn = result.needsConfirmation ? ' · 置信度偏低，请人工确认' : ''
			uni.showModal({
				title:
					kind === 'box'
						? `这是第 ${wizard.boxIndex} 箱的箱号吗？`
						: `这是箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 号吗？`,
				content: `识别结果 ${result.number}（置信度 ${confidence}）${warn}`,
				confirmText: '是',
				cancelText: '否',
				success: (res) => {
					if (!res.confirm) {
						this.event = eventOf('RETRY', `已放弃 ${result.number}，请重拍${label}。`, false)
						return
					}
					this.commitLayerCode(result.number, kind)
				}
			})
		},

		/** 本罐核对：确认无误 / 还没好。 */
		confirmCanDone() {
			const wizard = this.wizard
			uni.showModal({
				title: `箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 拍摄是否结束？`,
				content: '请检查无误。',
				confirmText: '确认无误',
				cancelText: '还没好',
				success: (res) => {
					if (!res.confirm) {
						this.handle(confirmCanReview(this.batch, false))
						return
					}
					this.handle(confirmCanReview(this.batch, true))
					this.afterCanConfirmed()
				}
			})
		},

		/** 本罐确认后：本箱拍完就问「是否继续拍下一箱」。 */
		afterCanConfirmed() {
			const next = deriveWizard(this.batch)
			if (next.phase !== PHASE.BOX_REVIEW) return
			if (next.isLastBox) {
				this.chainModal({
					title: '最后一箱已完成',
					content: `箱 ${next.boxIndex} 共 ${next.cansInBox} 罐已拍完，是否进入整体核对？`,
					confirmText: '去核对',
					cancelText: '再看看',
					success: (res) => {
						if (res.confirm) this.finishLastBox()
					}
				})
				return
			}
			this.chainModal({
				title: '本箱完成，是否继续拍下一箱？',
				content: `箱 ${next.boxIndex} 共 ${next.cansInBox} 罐已拍完，还有 ${next.totalBoxes - next.boxIndex} 箱没拍。`,
				confirmText: '继续拍下一箱',
				cancelText: '结束并核对',
				success: (res) => {
					if (res.confirm) {
						this.handle(confirmBoxReview(this.batch, true))
						return
					}
					this.chainModal({
						title: '还有箱未拍完，确定结束？',
						content: '结束后缺漏会在整体核对里如实显示，需要到「状态」页办提前结束签名。',
						confirmText: '确定结束',
						cancelText: '继续拍',
						success: (second) => {
							if (!second.confirm) return
							this.handle(finishRemaining(this.batch))
							this.askContinueToReview()
						}
					})
				}
			})
		},

		/** 最后一箱确认完成 → 直接进整体核对。 */
		finishLastBox() {
			this.handle(confirmBoxReview(this.batch, true))
			this.runReview()
		},

		/** 继续拍下一箱（把本箱标记完成 → 向导回到步骤 1）。 */
		nextBox() {
			this.handle(confirmBoxReview(this.batch, true))
		},

		/** 结束并核对：整批终止（决策 4）。 */
		endWholeBatch() {
			uni.showModal({
				title: '还有箱未拍完，确定结束？',
				content: '结束后缺漏会在整体核对里如实显示，需要到「状态」页办提前结束签名。',
				confirmText: '确定结束',
				cancelText: '继续拍',
				success: (res) => {
					if (!res.confirm) return
					this.handle(finishRemaining(this.batch))
					this.askContinueToReview()
				}
			})
		},

		notYet() {
			this.handle(confirmCanReview(this.batch, false))
		},

		askContinueToReview() {
			this.chainModal({
				title: '进入整体核对？',
				content: '所有箱已完成，接下来核对计划与实际是否一致。',
				confirmText: '去核对',
				cancelText: '再看看',
				success: (res) => {
					if (res.confirm) this.runReview()
				}
			})
		},

		/** 步骤 3：整体核对弹窗（一致 → 待核对；不一致 → 留下补拍/改槽位）。 */
		runReview() {
			const result = review(this.batch)
			this.chainModal({
				title: '整体核对',
				content: `计划 ${result.plan.boxCount} 箱 ${result.plan.canCount} 罐 ${result.plan.particleTotal} 粒子，实际识别 ${result.actual.boxCount} 箱 ${result.actual.canCount} 罐 ${result.actual.particleTotal} 粒子，是否一致？`,
				confirmText: '一致，生成',
				cancelText: '不一致，返回修改',
				success: (res) => {
					if (!res.confirm) {
						this.event = eventOf('EDIT', '请回到对应箱/罐补拍或修改槽位（顺序不会被重排）。', false)
						return
					}
					if (!result.canVerify) {
						this.chainModal({
							title: '存在缺漏',
							content: '缺漏未签名时不能置为待核对。请补齐，或到「状态」页登记提前结束（原因 + 操作人）。',
							showCancel: false
						})
						return
					}
					const moved = transition(this.batch, 'pending_review')
					this.handle(moved)
					uni.showToast({ title: '已固化到本机（待核对）', icon: 'success' })
					setTimeout(() => this.go('status'), 600)
				}
			})
		},

		/**
		 * 展开 / 收起「手动输入箱号·罐号」。
		 * 只有在这里（操作员主动点）才把焦点交给输入框，页面初始不聚焦、不弹输入法。
		 */
		toggleManual() {
			this.manualOpen = !this.manualOpen
			this.manualFocus = this.manualOpen
			if (!this.manualOpen) {
				this.manualValue = ''
				this.manualFocus = false
			}
		},

		/**
		 * 步骤 1 / 2.1 的手动输入：多号码报警 → 清洗 + 20 位前缀校验 → 确认弹窗 → 才写入。
		 * 与扫码/拍照通道走的是同一条收口（considerSingle），保证规则只有一份。
		 */
		submitManualLayer() {
			if (!this.batch) return
			const kind =
				this.wizard.phase === PHASE.BOX ? 'box' : this.wizard.phase === PHASE.CAN ? 'can' : ''
			if (!kind) {
				this.event = eventOf(EVENT.WRONG_STATE, `当前步骤是「${this.wizard.prompt}」，用手动输入不适用。`, false)
				return
			}
			const raw = (this.manualValue || '').trim()
			const label = kind === 'box' ? '箱号' : '罐号'
			if (!raw) return
			// 多号码（如「1 2」）按多码处理：震动报警 + 要求重拍，不进确认框
			const tokens = raw.split(/[\s,;、]+/).filter(Boolean)
			if (tokens.length > 1) {
				this.manualValue = ''
				this.alarm(
					eventOf(
						EVENT.MULTI_CODE,
						`一次输入了 ${tokens.length} 个号码（${tokens.join('、')}）；拍${label}时只能有一个，请重拍或重新输入。`,
						true
					)
				)
				return
			}
			// 校验 / 查重 / 确认弹窗 / 写入都在 considerSingle 里，避免两套规则
			this.considerSingle(tokens[0], kind)
		},

		/**
		 * 拍照识别（v1.3.4）：调系统相机拍一张静态照片，先交给识别契约层 `recognizeNumber()`。
		 *   - Provider 返回 success:true → 弹确认框（展示 number + confidence），[是] 后走业务层校验写入；
		 *   - candidates.length > 1 → 震动 + 多码报警，不进确认框，强制重拍；
		 *   - success:false（当前默认 Provider 就是这条路）→ 降级「照片确认浮层」，人工读数后手输。
		 * 照片**不落本机**、用完即弃（只放在页面内存里）。
		 */
		capturePhoto(kind) {
			const wizard = this.wizard
			if (kind === 'box' && wizard.phase !== PHASE.BOX) return
			if (kind === 'can' && wizard.phase !== PHASE.CAN) return
			uni.chooseImage({
				count: 1,
				sourceType: ['camera'],
				sizeType: ['compressed'],
				success: async (res) => {
					const paths = (res && res.tempFilePaths) || []
					if (!paths.length) {
						this.event = eventOf('ERROR', '没有拿到照片，请重拍。', false)
						return
					}
					const filePath = paths[0]
					const label = kind === 'box' ? '箱号' : '罐号'
					// 先把照片亮出来（识别期间操作员就能开始读数），识别结果回来再决定走哪条路
					this.photo = { path: filePath, kind, rotate: 0, scale: 1, recognizing: true, result: null }
					this.event = eventOf('PHOTO', `照片已拍好，正在识别${label}…`, false)

					const result = await recognizeNumber(filePath, { kind })
					// 识别期间操作员可能已经关掉浮层或重拍，这里就别再动界面了
					if (!this.photo || this.photo.path !== filePath) return

					if (result.candidates.length > 1) {
						this.photo = null
						this.manualValue = ''
						this.alarm(
							eventOf(
								EVENT.MULTI_CODE,
								`一次识别到 ${result.candidates.length} 个号码（${result.candidates.join('、')}）；拍${label}时只能有一个，请重拍。`,
								true
							)
						)
						return
					}

					if (result.success) {
						this.photo = null
						this.confirmRecognizedNumber(kind, result)
						return
					}

					// 降级：本机没有识别引擎 / 识别不确定 → 人工读数
					this.photo = Object.assign({}, this.photo, { recognizing: false, result })
					this.event = eventOf(
						'PHOTO',
						`本机暂无自动识别能力 / 识别不确定，请照着照片读数并输入${label}。`,
						false
					)
				},
				fail: (error) => {
					const message = (error && error.errMsg) || '拍照失败'
					if (/cancel/i.test(message)) return // 操作员自己取消，不打扰
					this.event = eventOf('ERROR', `拍照未成功：${message}`, false)
				}
			})
		},

		zoomPhoto(delta) {
			if (!this.photo) return
			const scale = Math.min(3, Math.max(0.5, Number((this.photo.scale + delta).toFixed(2))))
			this.photo = Object.assign({}, this.photo, { scale })
		},

		rotatePhoto() {
			if (!this.photo) return
			this.photo = Object.assign({}, this.photo, { rotate: (this.photo.rotate + 90) % 360 })
		},

		resetPhoto() {
			if (!this.photo) return
			this.photo = Object.assign({}, this.photo, { rotate: 0, scale: 1 })
		},

		/** 从照片浮层直接跳到手动输入：收起浮层并展开对应层级的输入面板。 */
		goManualFromPhoto() {
			const kind = this.photo ? this.photo.kind : 'box'
			this.photo = null
			this.manualOpen = true
			this.manualFocus = true
			this.event = eventOf('MANUAL', `请照着刚才的照片键入${kind === 'box' ? '箱号' : '罐号'}。`, false)
		},

		/** 手动输入兜底卡：空格 / 逗号分隔，一次可多个（条码枪 / 整段粘贴）。 */
		submitPaste() {
			if (!this.batch) return
			const raw = (this.pasteCode || '').trim()
			if (!raw) return
			const codes = raw.split(/[\s,;]+/).filter(Boolean)
			this.pasteCode = ''
			if (this.wizard.phase === PHASE.BOX || this.wizard.phase === PHASE.CAN) {
				if (codes.length > 1) {
					this.alarm(
						eventOf(EVENT.MULTI_CODE, `一次识别到 ${codes.length} 个号码；拍箱号/罐号时只能有一个，请重拍或分开提交。`, true)
					)
					return
				}
				this.considerSingle(codes[0], this.wizard.phase === PHASE.BOX ? 'box' : 'can')
				return
			}
			if (this.wizard.phase !== PHASE.PARTICLE) {
				this.event = eventOf(EVENT.WRONG_STATE, `当前步骤是「${this.wizard.prompt}」，不接受手动输入。`, false)
				return
			}
			this.handle(applyCodes(this.batch, codes))
		},

		openSlot(boxIndex, canIndex, slotIndex) {
			const can = findCan(this.batch, boxIndex, canIndex)
			if (!can) return
			this.editing = {
				boxIndex: boxIndex - 1,
				canIndex: canIndex - 1,
				slotIndex,
				code: (can.particles || [])[slotIndex] || ''
			}
			this.replaceValue = ''
		},

		doReplace() {
			if (!this.editing) return
			const { boxIndex, canIndex, slotIndex } = this.editing
			this.handle(replaceSlot(this.batch, boxIndex, canIndex, slotIndex, this.replaceValue))
			this.editing = null
		},

		doDelete() {
			if (!this.editing) return
			const { boxIndex, canIndex, slotIndex } = this.editing
			this.handle(deleteSlot(this.batch, boxIndex, canIndex, slotIndex))
			this.editing = null
		},

		doUndo() {
			this.handle(undo(this.batch))
		},

		doRedo() {
			this.handle(redo(this.batch))
		},

		/** 拓扑：主控机在不在只影响提示，不阻塞本地采集（阶段 6）。 */
		async checkServer() {
			this.busy = true
			try {
				const health = await api.health()
				this.healthOk = true
				uni.showToast({ title: `主控机在线 v${health.version}`, icon: 'none' })
			} catch (error) {
				this.healthOk = false
				uni.showToast({ title: '当前为离线模式，数据将保存在本机', icon: 'none' })
			} finally {
				this.busy = false
			}
		}
	}
}
</script>

<style scoped>
.page {
	padding: 24rpx;
}

.card {
	background: #ffffff;
	border: 1rpx solid #d6dee3;
	border-radius: 12rpx;
	padding: 24rpx;
	margin-bottom: 24rpx;
}

.card-title {
	font-size: 30rpx;
	font-weight: 600;
}

.hint {
	display: block;
	font-size: 24rpx;
	color: #5a6b77;
	margin-top: 8rpx;
}

.row-between {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.empty {
	margin-top: 12rpx;
}

.facts {
	display: flex;
	flex-wrap: wrap;
	margin-top: 16rpx;
}

.fact {
	width: 50%;
	margin-bottom: 12rpx;
}

.fact-key {
	font-size: 24rpx;
	color: #8697a3;
	margin-right: 8rpx;
}

.fact-value {
	font-size: 28rpx;
}

.progress {
	height: 16rpx;
	margin-top: 8rpx;
	background: #eef1f4;
	border-radius: 999rpx;
	overflow: hidden;
}

.progress-bar {
	height: 16rpx;
	background: #0e6e7a;
}

.alarm {
	padding: 20rpx 24rpx;
	margin-bottom: 24rpx;
	border-radius: 12rpx;
	border: 1rpx solid;
}

.alarm-error {
	color: #b91c1c;
	background: #fdeaea;
	border-color: #f0b4b4;
}

.alarm-ok {
	color: #15803d;
	background: #e6f4ea;
	border-color: #a8d5b5;
}

.alarm-title {
	display: block;
	font-size: 28rpx;
	font-weight: 600;
}

.alarm-body {
	display: block;
	font-size: 24rpx;
	margin-top: 6rpx;
}

.alarm-hint {
	display: block;
	margin-top: 12rpx;
	padding: 12rpx 16rpx;
	font-size: 24rpx;
	color: #b45309;
	background: #fdf3e5;
	border: 1rpx solid #f0cfa0;
	border-radius: 8rpx;
}

.step-row {
	display: flex;
	margin-top: 16rpx;
}

.step-dot {
	flex: 1;
	padding: 10rpx 0;
	margin-right: 8rpx;
	text-align: center;
	font-size: 22rpx;
	color: #8697a3;
	background: #f1f4f6;
	border-radius: 8rpx;
}

.step-dot.on {
	color: #0e6e7a;
	background: #e4f1f3;
	font-weight: 600;
}

.actions {
	margin-top: 16rpx;
}

.scan-btn {
	padding: 8rpx 0;
	font-size: 32rpx;
}

/* 手动输入箱号/罐号：默认折叠，展开后才是输入区 */
.manual-box {
	margin-top: 12rpx;
	padding: 16rpx 20rpx 8rpx;
	background: #f7fafb;
	border: 1rpx solid #e2ebee;
	border-radius: 12rpx;
}

/* 拍照识别的照片确认区：本机不做 OCR，只为让操作员看清楚数字 */
.photo-wrap {
	width: 100%;
	height: 36vh;
	margin-top: 16rpx;
	background: #101a22;
	border-radius: 12rpx;
	overflow: hidden;
}

.photo {
	width: 100%;
	height: 36vh;
}

.input {
	height: 76rpx;
	padding: 0 20rpx;
	margin: 16rpx 0;
	background: #f8fafb;
	border: 1rpx solid #d6dee3;
	border-radius: 8rpx;
	font-size: 26rpx;
}

.box-group {
	margin-top: 20rpx;
	padding: 16rpx 20rpx 4rpx;
	background: #f7fafb;
	border: 1rpx solid #e2ebee;
	border-radius: 12rpx;
}

.box-head {
	margin-bottom: 4rpx;
}

.box-title {
	font-size: 28rpx;
	font-weight: 600;
	color: #0e6e7a;
}

.slot-row {
	margin-top: 16rpx;
}

.slot-can {
	font-size: 26rpx;
	font-weight: 600;
	margin-right: 12rpx;
}

.slot-can-code {
	font-size: 22rpx;
	color: #5a6b77;
}

/* 20 位箱号 / 罐号在窄屏上必须能折行：
   不给 min-width:0 的话，flex 子项会直接溢出而不是换行。 */
.box-head .code,
.slot-can-code.code {
	flex: 1;
	min-width: 0;
	margin-left: 12rpx;
	text-align: right;
	word-break: break-all;
	word-wrap: break-word;
}

.slot-grid {
	display: flex;
	flex-wrap: wrap;
	margin-top: 10rpx;
}

.slot {
	width: 108rpx;
	height: 92rpx;
	margin: 0 10rpx 10rpx 0;
	border-radius: 8rpx;
	border: 1rpx solid #d6dee3;
	background: #ffffff;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
}

.slot.filled {
	border-color: #a8d5b5;
	background: #e6f4ea;
}

.slot.empty {
	color: #8697a3;
}

.slot-index {
	font-size: 20rpx;
	color: #8697a3;
}

.slot-code {
	font-size: 22rpx;
}

.overlay {
	position: fixed;
	left: 0;
	right: 0;
	top: 0;
	bottom: 0;
	background: rgba(16, 26, 34, 0.45);
	display: flex;
	align-items: flex-end;
}

.sheet {
	width: 100%;
	/* 内容比屏幕高时整块会被顶出屏幕（标题/降级提示看不见），所以限高并允许滚动 */
	max-height: 86vh;
	overflow-y: auto;
	padding: 32rpx;
	background: #ffffff;
	border-radius: 20rpx 20rpx 0 0;
}

.sheet-title {
	display: block;
	font-size: 30rpx;
	font-weight: 600;
	margin-bottom: 8rpx;
}

button.primary {
	background: #0e6e7a;
	color: #ffffff;
	margin-top: 16rpx;
}

button.secondary {
	background: #ffffff;
	color: #101a22;
	border: 1rpx solid #b6c2ca;
	margin-top: 16rpx;
}

button.ghost {
	background: transparent;
	color: #0e6e7a;
	border: 1rpx solid #a9d3d9;
	margin-top: 16rpx;
}

button.danger {
	background: #ffffff;
	color: #b91c1c;
	border: 1rpx solid #f0b4b4;
	margin-top: 16rpx;
}
</style>
