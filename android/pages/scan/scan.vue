<template>
	<view class="page">
		<!-- 顶部：当前任务与状态 -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">当前任务</text>
				<text :class="['badge', statusClass]">{{ statusLabel }}</text>
			</view>
			<view class="facts">
				<view class="fact">
					<text class="fact-key">批号</text>
					<text class="fact-value code">{{ batchNo || '未选择' }}</text>
				</view>
				<view class="fact">
					<text class="fact-key">罐</text>
					<text class="fact-value code">{{ currentCan }} / {{ plannedCanCount }}</text>
				</view>
				<view class="fact">
					<text class="fact-key">本罐粒子</text>
					<text class="fact-value code">{{ currentCanScanned }} / {{ currentCanPlanned }}</text>
				</view>
				<view class="fact">
					<text class="fact-key">总计</text>
					<text class="fact-value code">{{ actualTotal }} / {{ plannedTotal }}</text>
				</view>
			</view>
			<view class="progress">
				<view class="progress-bar" :style="{ width: canProgressPercent + '%' }"></view>
			</view>
		</view>

		<!-- 拦截 / 报警：颜色 + 文字，颜色不是唯一线索 -->
		<view v-if="blocked" class="alarm" :class="blocked.needsAlarm ? 'alarm-error' : 'alarm-warn'">
			<text class="alarm-title">{{ blocked.label }}</text>
			<text class="alarm-body">{{ blocked.message }}</text>
			<text v-if="blocked.detail && blocked.detail.usedAt" class="alarm-extra">
				已绑定位置：{{ blocked.detail.usedAt }}
			</text>
		</view>

		<view v-else-if="notice" class="alarm alarm-ok">
			<text class="alarm-title">{{ notice.label }}</text>
			<text class="alarm-body">{{ notice.message }}</text>
		</view>

		<view v-if="errorMessage" class="alarm alarm-error">
			<text class="alarm-title">操作被拒绝</text>
			<text class="alarm-body">{{ errorMessage }}</text>
		</view>

		<!-- 主操作：按服务端返回的状态决定该扫什么 -->
		<view class="card">
			<text class="card-title">{{ scanPrompt }}</text>
			<text class="hint">{{ scanHint }}</text>

			<button class="primary" :disabled="busy || !canScan" @click="doScan">
				{{ scanButtonText }}
			</button>

			<view v-if="status === 'box_confirm' || status === 'can_confirm'" class="actions">
				<button class="secondary" @click="confirmPending">确认</button>
				<button class="ghost" @click="rescan">重拍</button>
			</view>

			<view v-if="status === 'can_review'" class="actions">
				<button class="primary" @click="confirmPending">本罐确认无误</button>
				<button class="ghost" @click="rescan">还没好，继续拍</button>
			</view>

			<view v-if="status === 'next_can_prompt'" class="actions">
				<button class="primary" @click="nextCan(true)">继续下一罐</button>
				<button class="ghost" @click="nextCan(false)">提前结束</button>
			</view>

			<view v-if="status === 'overall_review'" class="actions">
				<button class="primary" @click="go('status')">前往整体核对</button>
			</view>
		</view>

		<!-- 手动输入：条码枪或人工输入兜底 -->
		<view class="card">
			<text class="card-title">手动输入</text>
			<view class="input-row">
				<input
					class="input code"
					v-model="manualCode"
					placeholder="粘贴或输入条码，回车提交"
					confirm-type="done"
					@confirm="submitManual"
				/>
				<button class="secondary small" @click="submitManual">提交</button>
			</view>
			<text class="hint">条码枪以回车结尾时会自动提交。</text>
		</view>

		<view class="card">
			<view class="row-between">
				<text class="card-title">连接</text>
				<text :class="['badge', connClass]">{{ connLabel }}</text>
			</view>
			<text class="hint">{{ serverHint }}</text>
			<button class="ghost" @click="refresh">刷新任务状态</button>
		</view>
	</view>
</template>

<script>
import { api, ApiError } from '../../services/api'
import { getServer, getDevice, setServer, ensureDefaults } from '../../services/store'

/**
 * 扫码采集页。

 * 关键约定：**状态一律以服务端返回为准**，页面不本地推进状态。
 * 所有拦截（多码、错层、重复、溢出）都由服务端判定，页面只负责展示与恢复路径。
 *
 * 一期识别管线在 Windows 服务端，移动端只用原生扫码能力拿单码；
 * 粒子批量多码（一张纸 6 枚）走「拍照上传 → 服务端识别」是二期二批的内容，
 * 那时复用一期的抗反光与同区域冲突拒绝，不需要在手机端重写识别。
 */
export default {
	data() {
		return {
			busy: false,
			manualCode: '',
			snapshot: null,
			blocked: null,
			notice: null,
			errorMessage: '',
			connState: 'unknown',
			batchNo: '',
			deviceName: ''
		}
	},

	computed: {
		status() {
			return (this.snapshot && this.snapshot.status) || 'idle'
		},
		statusLabel() {
			return (this.snapshot && this.snapshot.statusLabel) || '未连接'
		},
		statusClass() {
			const map = {
				box_scanning: 'badge-info',
				can_scanning: 'badge-info',
				particle_scanning: 'badge-info',
				box_confirm: 'badge-warn',
				can_confirm: 'badge-warn',
				can_review: 'badge-warn',
				next_can_prompt: 'badge-warn',
				overall_review: 'badge-ok',
				early_end: 'badge-error',
				idle: 'badge-neutral'
			}
			return map[this.status] || 'badge-neutral'
		},
		currentCan() {
			return (this.snapshot && this.snapshot.currentCanIndex) || 0
		},
		plannedCanCount() {
			return (this.snapshot && this.snapshot.plannedCanCount) || 0
		},
		currentCanPlanned() {
			return (this.snapshot && this.snapshot.currentCanPlanned) || 0
		},
		currentCanScanned() {
			return (this.snapshot && this.snapshot.currentCanScanned) || 0
		},
		actualTotal() {
			return (this.snapshot && this.snapshot.actualParticleTotal) || 0
		},
		plannedTotal() {
			return (this.snapshot && this.snapshot.plannedParticleTotal) || 0
		},
		canProgressPercent() {
			if (!this.currentCanPlanned) return 0
			const percent = (this.currentCanScanned / this.currentCanPlanned) * 100
			return Math.min(100, Math.round(percent * 10) / 10)
		},
		canScan() {
			return ['box_scanning', 'can_scanning', 'particle_scanning'].indexOf(this.status) >= 0
		},
		scanPrompt() {
			const map = {
				box_scanning: '请扫描箱号',
				can_scanning: `请扫描罐 ${this.currentCan} 号`,
				particle_scanning: `请扫描罐 ${this.currentCan} 的粒子`,
				box_confirm: '这是箱号吗？',
				can_confirm: `这是罐 ${this.currentCan} 号吗？`,
				can_review: `罐 ${this.currentCan} 已扫满`,
				next_can_prompt: '是否继续下一罐？',
				overall_review: '所有罐已完成',
				early_end: '已进入提前结束流程',
				idle: '当前批次还没有开始采集'
			}
			return map[this.status] || '请查看任务状态'
		},
		scanHint() {
			if (this.status === 'particle_scanning') {
				return `本罐剩余 ${(this.snapshot && this.snapshot.remainingInCan) || 0} 个槽位。每次扫一个码，满了自动进入核对。`
			}
			if (this.canScan) {
				return '扫描时画面里只能有一个条码；识别到多个会被服务端拒绝。'
			}
			return '按下方按钮继续。'
		},
		scanButtonText() {
			if (!this.canScan) return '当前无需扫描'
			return this.status === 'particle_scanning' ? '扫描粒子码' : '打开扫码'
		},
		connLabel() {
			const map = {
				unknown: '未检测',
				online: '已连接',
				offline: '连不上'
			}
			return map[this.connState] || '未检测'
		},
		connClass() {
			if (this.connState === 'online') return 'badge-ok'
			if (this.connState === 'offline') return 'badge-error'
			return 'badge-neutral'
		},
		serverHint() {
			const server = getServer()
			if (!server.baseUrl) {
				return '尚未设置服务地址。请到「连接设置」填写 Windows 主控机的局域网地址。'
			}
			return `${server.baseUrl}${this.deviceName ? ' · ' + this.deviceName : ''}`
		}
	},

	onShow() {
		this.deviceName = getDevice().name
		this.refresh()
	},

	methods: {
		go(page) {
			uni.switchTab({ url: `/pages/${page}/${page}` })
		},

		handleError(error) {
			if (error instanceof ApiError) {
				this.errorMessage = error.message
				this.blocked = null
				this.notice = null
				this.connState = error.code === 'NETWORK_ERROR' ? 'offline' : 'online'
				return
			}
			this.errorMessage = (error && error.message) || String(error)
		},

		applySnapshot(snapshot) {
			this.snapshot = snapshot
			this.connState = 'online'
			this.errorMessage = ''

			const server = getServer()
			if (server.batchId) {
				const cached = uni.getStorageSync('pharmrelate.batchNo')
				this.batchNo = cached || this.batchNo
			}

			const event = snapshot.lastEvent
			if (event && event.blocking) {
				this.blocked = event
				this.notice = null
				// 需要报警时震动，App 端没有 WebAudio，用原生震动代替提示音
				if (event.needsAlarm) {
					uni.vibrateLong()
				}
			} else {
				this.blocked = null
				this.notice = event || null
			}
		},

		async refresh() {
			ensureDefaults()
			const server = getServer()
			if (!server.baseUrl) {
				this.connState = 'unknown'
				return
			}
			this.busy = true
			try {
				if (!server.batchId) {
					const list = await api.listBatches('collecting')
					const first = (list.items || [])[0]
					if (!first) {
						this.errorMessage = '服务端没有处于「采集中」的批次。请先在 Windows 端开始采集。'
						this.connState = 'online'
						return
					}
					setServer({ batchId: first.id, batchNo: first.batchNo })
					uni.setStorageSync('pharmrelate.batchNo', first.batchNo)
					this.batchNo = first.batchNo
				}
				this.batchNo = getServer().batchNo
				this.applySnapshot(await api.scanSession(getServer().batchId))
			} catch (error) {
				this.handleError(error)
			} finally {
				this.busy = false
			}
		},

		doScan() {
			if (!this.canScan) return
			uni.scanCode({
				scanType: ['barCode', 'qrCode'],
				success: (result) => {
					this.submitCodes([result.result])
				},
				fail: (error) => {
					// 用户取消扫码不算错误，不打扰
					if (error && /cancel/i.test(error.errMsg || '')) return
					this.errorMessage = (error && error.errMsg) || '扫码失败'
				}
			})
		},

		async submitManual() {
			const value = (this.manualCode || '').trim()
			if (!value) return
			const codes = value.split(/[\s,;]+/).filter(Boolean)
			this.manualCode = ''
			await this.submitCodes(codes)
		},

		async submitCodes(codes) {
			const server = getServer()
			if (!server.batchId) {
				this.errorMessage = '尚未选择批次，请先刷新任务状态。'
				return
			}
			this.busy = true
			try {
				this.applySnapshot(await api.scanFrame(server.batchId, codes, []))
			} catch (error) {
				this.handleError(error)
			} finally {
				this.busy = false
			}
		},

		async confirmPending() {
			this.busy = true
			try {
				this.applySnapshot(await api.scanConfirm(getServer().batchId))
			} catch (error) {
				this.handleError(error)
			} finally {
				this.busy = false
			}
		},

		async rescan() {
			this.busy = true
			try {
				this.applySnapshot(await api.scanRescan(getServer().batchId))
			} catch (error) {
				this.handleError(error)
			} finally {
				this.busy = false
			}
		},

		async nextCan(proceed) {
			this.busy = true
			try {
				this.applySnapshot(await api.scanNextCan(getServer().batchId, proceed))
			} catch (error) {
				this.handleError(error)
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

.row-between {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 16rpx;
}

.facts {
	display: flex;
	flex-wrap: wrap;
}

.fact {
	width: 50%;
	margin-bottom: 16rpx;
}

.fact-key {
	display: block;
	font-size: 22rpx;
	color: #8697a3;
}

.fact-value {
	display: block;
	font-size: 32rpx;
	font-weight: 500;
	margin-top: 4rpx;
}

.progress {
	height: 12rpx;
	background: #ebeef1;
	border-radius: 999rpx;
	overflow: hidden;
	margin-top: 8rpx;
}

.progress-bar {
	height: 100%;
	background: #0e6e7a;
}

.alarm {
	border: 1rpx solid;
	border-radius: 12rpx;
	padding: 20rpx 24rpx;
	margin-bottom: 24rpx;
}

.alarm-title {
	display: block;
	font-size: 28rpx;
	font-weight: 600;
}

.alarm-body {
	display: block;
	font-size: 26rpx;
	margin-top: 8rpx;
}

.alarm-extra {
	display: block;
	font-size: 24rpx;
	color: #5a6b77;
	margin-top: 8rpx;
}

.alarm-error {
	color: #b91c1c;
	background: #fdeaea;
	border-color: #f0b4b4;
}

.alarm-warn {
	color: #b45309;
	background: #fdf3e5;
	border-color: #f0cfa0;
}

.alarm-ok {
	color: #15803d;
	background: #e6f4ea;
	border-color: #a8d5b5;
}

.hint {
	display: block;
	font-size: 24rpx;
	color: #5a6b77;
	margin-top: 8rpx;
}

button.primary {
	margin-top: 20rpx;
	background: #0e6e7a;
	color: #ffffff;
}

button.secondary {
	margin-top: 16rpx;
	background: #ffffff;
	color: #101a22;
	border: 1rpx solid #b6c2ca;
}

button.ghost {
	margin-top: 16rpx;
	background: transparent;
	color: #5a6b77;
}

.actions {
	display: flex;
	flex-direction: column;
}

.input-row {
	display: flex;
	align-items: center;
	margin-top: 16rpx;
}

.input {
	flex: 1;
	height: 72rpx;
	padding: 0 20rpx;
	background: #f8fafb;
	border: 1rpx solid #d6dee3;
	border-radius: 8rpx;
	font-size: 26rpx;
}

button.small {
	margin: 0 0 0 16rpx;
	width: 140rpx;
	height: 72rpx;
	line-height: 72rpx;
	font-size: 26rpx;
	padding: 0;
}
</style>
