<template>
	<view class="page">
		<!-- ① 批次基础信息（v1.3.0 新增：手机端可独立建档，离线可用） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">批次基础信息</text>
				<text :class="['badge', statusClass]">{{ statusLabel }}</text>
			</view>
			<text class="hint">
				手机端可以独立建批次：填好基础信息 → 配包装结构 → 到「扫码」页按向导采集。
				数据保存在本机（离线可用），本期不与 Windows 主控端同步。
			</text>

			<text class="field-label">批号（必填）</text>
			<input class="input code" v-model="form.batchNo" placeholder="例如 20260927" />

			<text class="field-label">生产日期（必填）</text>
			<picker mode="date" :value="form.produceDate" @change="onProduceDate">
				<view class="input code picker-value">{{ form.produceDate || '请选择生产日期' }}</view>
			</picker>

			<text class="field-label">有效期（必填，需大于生产日期）</text>
			<picker mode="date" :value="form.expireDate" @change="onExpireDate">
				<view class="input code picker-value">{{ form.expireDate || '请选择有效期' }}</view>
			</picker>

			<button class="secondary" :disabled="busy" @click="saveBaseInfo">保存草稿</button>
			<button class="ghost" :disabled="busy" @click="goStructure">下一步：配置包装结构</button>

			<view class="fold" @click="fixedOpen = !fixedOpen">
				<text class="fold-title">系统固定参数（只读 · 由程序写死）</text>
				<text class="fold-mark">{{ fixedOpen ? '收起' : '展开' }}</text>
			</view>
			<view v-if="fixedOpen" class="fixed-list">
				<view v-for="item in fixedParams" :key="item.key" class="info-row">
					<text class="info-key">{{ item.label }}</text>
					<text class="info-value code">{{ item.value }}</text>
				</view>
				<text class="hint">cascade 是固定字面量，不随实际罐数或粒子数变化。</text>
			</view>
		</view>

		<!-- ② 包装结构 -->
		<view class="card" id="structureCard">
			<view class="row-between">
				<text class="card-title">包装结构</text>
				<text class="badge badge-neutral">{{ totalBoxes }} 箱 / {{ totalCans }} 罐</text>
			</view>
			<text class="hint">每箱罐数各自独立；单批粒子总数上限 {{ maxBatch }} 粒（超限会被挡住）。</text>

			<view class="row-between field">
				<text class="field-label">纸箱数（1～5）</text>
				<view class="stepper">
					<button class="step-btn" :disabled="!canEditStructure" @click="stepBox(-1)">－</button>
					<text class="step-value code">{{ totalBoxes }}</text>
					<button class="step-btn" :disabled="!canEditStructure" @click="stepBox(1)">＋</button>
				</view>
			</view>

			<view v-for="(counts, boxIndex) in boxPlan" :key="boxIndex" class="box-block">
				<view class="row-between box-head">
					<text class="box-title">箱 {{ boxIndex + 1 }}</text>
					<text class="hint">罐数 1～5</text>
				</view>
				<view class="row-between field">
					<text class="field-label">箱 {{ boxIndex + 1 }} 罐数</text>
					<view class="stepper">
						<button class="step-btn" :disabled="!canEditStructure" @click="stepCan(boxIndex, -1)">－</button>
						<text class="step-value code">{{ counts.length }}</text>
						<button class="step-btn" :disabled="!canEditStructure" @click="stepCan(boxIndex, 1)">＋</button>
					</view>
				</view>

				<view v-for="(item, canIndex) in counts" :key="canIndex" class="particle-row">
					<text class="field-label">箱 {{ boxIndex + 1 }} · 罐 {{ canIndex + 1 }} 粒子数（1～2500）</text>
					<input
						class="input code"
						type="number"
						:disabled="!canEditStructure"
						:value="String(item)"
						@input="onParticleInput(boxIndex, canIndex, $event)"
					/>
				</view>
			</view>

			<view class="stats">
				<view class="stat">
					<text class="stat-key">总箱数</text>
					<text class="stat-value code">{{ totalBoxes }}</text>
				</view>
				<view class="stat">
					<text class="stat-key">总罐数</text>
					<text class="stat-value code">{{ totalCans }}</text>
				</view>
				<view class="stat">
					<text class="stat-key">总粒子数</text>
					<text class="stat-value code">{{ totalParticles }}</text>
				</view>
			</view>

			<view class="progress-row">
				<text class="hint">
					总粒子数 <text class="code">{{ totalParticles }}</text> / {{ maxBatch }}
				</text>
				<view class="progress">
					<view class="progress-bar" :class="{ over: overBatch }" :style="{ width: progressPercent + '%' }"></view>
				</view>
			</view>
			<text v-if="overBatch" class="alarm-hint">已超过单批上限 {{ maxBatch }} 粒，请减少箱数、罐数或每罐粒子数。</text>
			<text v-if="!canEditStructure" class="hint">
				已进入采集，包装结构不可再改（要改请删除本地批次后重建）。
			</text>

			<button class="secondary" :disabled="busy || !canEditStructure" @click="saveStructureDraft">保存结构草稿</button>
			<button class="primary" :disabled="busy || !canEditStructure" @click="enterCollecting">
				保存结构，进入采集
			</button>
		</view>

		<!-- ③ 本地批次管理（离线可用；做完一批要能开下一批） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">本地批次</text>
				<text class="badge badge-neutral">本机 {{ localBatches.length }} 个</text>
			</view>
			<text class="hint">
				数据只存在本机。做完一批要开下一批时，先把当前批次删掉再重新建（删掉只影响本机，不可恢复）。
			</text>
			<view v-if="localBatches.length" class="batch-list">
				<view v-for="item in localBatches" :key="item.localId" class="batch-row">
					<view class="batch-main">
						<text class="batch-no code">{{ item.batchNo || '（未填批号）' }}</text>
						<text class="batch-meta">{{ statusText(item.status) }} · {{ item.localId }}</text>
					</view>
					<text v-if="item.localId === localId" class="badge badge-info">当前</text>
				</view>
			</view>
			<text v-else class="hint">本机还没有批次。</text>
			<button v-if="localId" class="secondary" :disabled="busy" @click="deleteCurrentBatch">删除当前批次</button>
			<button v-if="localBatches.length" class="ghost" :disabled="busy" @click="clearLocalBatches">
				清空本机全部批次
			</button>
		</view>

		<!-- ④ 联机设置（保留；本期不阻塞主流程） -->
		<view class="card">
			<view class="row-between">
				<text class="card-title">服务地址（可选）</text>
				<text class="badge badge-neutral">二期同步用</text>
			</view>
			<text class="hint">
				本期采集不需要联网。填了地址以后，「测试连接」可以顺手看看主控机在不在；
				连不上也不影响本地建批次与采集。
			</text>
			<input class="input code" v-model="baseUrl" placeholder="http://192.168.1.20:17800" />
			<input class="input code" v-model="wsUrl" placeholder="ws://192.168.1.20:17801（留空则自动推导）" />
			<button class="secondary" :disabled="busy" @click="saveServer">保存</button>
		</view>

		<view class="card">
			<text class="card-title">连接测试（可选）</text>
			<view class="row-between">
				<text class="hint">本地服务</text>
				<text :class="['badge', healthOk ? 'badge-ok' : 'badge-neutral']">
					{{ healthOk ? '已连接' : '未检测' }}
				</text>
			</view>
			<button class="ghost" :disabled="busy" @click="testHealth">测试连接</button>
			<text v-if="healthMessage" class="hint">{{ healthMessage }}</text>
		</view>

		<view class="card">
			<text class="card-title">配对（二期）</text>
			<text class="hint">
				配对 Token 由 Windows 端签发，一次性、5 分钟过期，且绑定本机设备指纹。
				本期只做界面预留。
			</text>
			<input class="input code" v-model="token" placeholder="粘贴配对 Token" />
			<button class="secondary" :disabled="busy" @click="saveToken">保存 Token</button>
		</view>

		<view class="card">
			<text class="card-title">本机信息</text>
			<view class="info-row">
				<text class="info-key">设备名</text>
				<text class="info-value">{{ device.name }}</text>
			</view>
			<view class="info-row">
				<text class="info-key">设备指纹</text>
				<text class="info-value code">{{ device.fingerprint }}</text>
			</view>
			<view class="info-row">
				<text class="info-key">本地批次</text>
				<text class="info-value code">{{ localId || '（无）' }}</text>
			</view>
			<view class="info-row">
				<text class="info-key">系统</text>
				<text class="info-value">{{ systemInfo }}</text>
			</view>
		</view>

		<view class="card">
			<text class="card-title">本版没有的功能（别去找）</text>
			<text class="hint">
				手机端不产出 XML（由主控机生成）、多码拍照识别（离线做不了，粒子逐个扫）、
				离线补发与多端互斥锁 —— 这些在二期。
			</text>
		</view>
	</view>
</template>

<script>
import { api, ApiError } from '../../services/api'
import { ensureDefaults, getDevice, getServer, setServer } from '../../services/store'
import {
	FIXED_PARAMS,
	MAX_BOXES,
	MAX_CANS,
	MAX_PARTICLES_PER_BATCH,
	MIN_BOXES,
	MIN_CANS,
	STATUS_LABELS,
	clearAll,
	createDraft,
	getActiveBatch,
	listBatches,
	planCounts,
	particleTotal,
	removeBatch,
	saveBatch,
	saveStructure,
	updateBaseInfo,
	validateBaseInfo,
	validateStructure
} from '../../services/localBatch'

export default {
	data() {
		return {
			busy: false,
			fixedParams: FIXED_PARAMS,
			maxBatch: MAX_PARTICLES_PER_BATCH,
			fixedOpen: false,
			localId: '',
			localStatus: 'draft',
			form: { batchNo: '', produceDate: '', expireDate: '' },
			// 箱 → 罐 → 粒子数字符串（boxPlan[0] = 第 1 箱的每罐粒子数）
			boxPlan: [['']],
			baseUrl: '',
			wsUrl: '',
			token: '',
			healthOk: false,
			healthMessage: '',
			batches: [],
			localBatches: [],
			currentBatchId: '',
			device: { name: '', fingerprint: '' },
			systemInfo: ''
		}
	},

	computed: {
		totalBoxes() {
			return this.boxPlan.length
		},
		totalCans() {
			return this.boxPlan.reduce((sum, counts) => sum + counts.length, 0)
		},
		canEditStructure() {
			return this.localStatus === 'draft'
		},
		statusLabel() {
			return STATUS_LABELS[this.localStatus] || '草稿'
		},
		statusClass() {
			if (this.localStatus === 'collecting') return 'badge-info'
			if (this.localStatus === 'pending_review') return 'badge-warn'
			if (this.localStatus === 'verified') return 'badge-ok'
			return 'badge-neutral'
		},
		totalParticles() {
			return particleTotal(this.boxPlan.map((counts) => counts.map((value) => Number(value) || 0)))
		},
		progressPercent() {
			const percent = (this.totalParticles / MAX_PARTICLES_PER_BATCH) * 100
			return Math.min(100, Math.round(percent * 10) / 10)
		},
		overBatch() {
			return this.totalParticles > MAX_PARTICLES_PER_BATCH
		}
	},

	onShow() {
		ensureDefaults()
		this.device = getDevice()
		this.refreshLocal()
		const server = getServer()
		this.baseUrl = server.baseUrl
		this.wsUrl = server.wsUrl
		this.token = server.token
		this.currentBatchId = server.batchId
		try {
			const info = uni.getSystemInfoSync()
			this.systemInfo = `${info.platform} ${info.system} / Android ${info.version || ''}`
		} catch (error) {
			this.systemInfo = '未知'
		}
	},

	methods: {
		/** 读回当前本地批次（离线也能读，不碰网络）。 */
		refreshLocal() {
			this.localBatches = listBatches()
			const batch = getActiveBatch()
			if (!batch) {
				this.localId = ''
				this.localStatus = 'draft'
				return
			}
			this.localId = batch.localId
			this.localStatus = batch.status
			this.form = {
				batchNo: batch.batchNo,
				produceDate: batch.produceDate,
				expireDate: batch.expireDate
			}
			// 结构已保存过 → 以本地批次为准；草稿还没保存过 → 保留用户正在输入的
			// 那一份（否则「保存草稿」这类回读会把刚敲好的罐数/粒子数冲成默认值）。
			const planned = planCounts(batch)
			if (planned.length) {
				this.boxPlan = planned.map((counts) => counts.map((value) => String(value)))
			} else if (!this.boxPlan.length) {
				this.boxPlan = [['']]
			}
		},

		normalize(value) {
			return (value || '').trim().replace(/\/$/, '')
		},

		onProduceDate(event) {
			this.form.produceDate = event.detail.value
			// 有效期默认给 30 天（与桌面端 validateDate = today + 30 的口径一致）：
			// 否则操作员很容易选成同一天，被"有效期必须大于生产日期"挡住而不知道为什么。
			const current = this.form.expireDate
			if (!current || current <= this.form.produceDate) {
				this.form.expireDate = addDays(this.form.produceDate, 30)
			}
		},

		onExpireDate(event) {
			this.form.expireDate = event.detail.value
		},

		/**
		 * 只把基础信息写进本地批次，**不回读界面**。
		 * 单独拆出来的原因：「保存结构，进入采集」里如果先 refreshLocal，
		 * 草稿批次的 plannedParticleCounts 还是空的，会把用户刚敲好的罐数/粒子数
		 * 冲回默认的 1 罐 0 粒，接着结构校验必然失败、跳转被拦下。
		 */
		persistBaseInfo() {
			const issues = validateBaseInfo(this.form)
			if (issues.length) {
				uni.showModal({
					title: '基础信息不完整',
					content: issues.map((item) => item.message).join('；'),
					showCancel: false
				})
				return false
			}
			const existing = getActiveBatch()
			if (!existing) {
				saveBatch(createDraft({ ...this.form, deviceId: this.device.fingerprint }))
			} else if (existing.status === 'draft') {
				saveBatch(updateBaseInfo(existing, this.form).batch)
			} else {
				uni.showModal({
					title: '已进入采集',
					content: '当前批次已经开始采集，基础信息只读。要新建请先删除本地批次。',
					showCancel: false
				})
				return false
			}
			return true
		},

		/** 「保存草稿」按钮：写存储 + 回读刷新状态徽章（阶段 2 验收点）。 */
		saveBaseInfo() {
			if (!this.persistBaseInfo()) return false
			this.refreshLocal()
			uni.showToast({ title: '已保存草稿', icon: 'success' })
			return true
		},

		goStructure() {
			if (!this.saveBaseInfo()) return
			uni.pageScrollTo({ selector: '#structureCard', duration: 300 })
		},

		/** 纸箱数步进：越界弹 Alert。 */
		stepBox(delta) {
			const next = this.boxPlan.length + delta
			if (next < MIN_BOXES || next > MAX_BOXES) {
				uni.showModal({
					title: '纸箱数超出范围',
					content: '纸箱数必须在 ' + MIN_BOXES + '～' + MAX_BOXES + ' 之间',
					showCancel: false
				})
				return
			}
			// 新增的箱子默认 1 罐、粒子数待填
			this.boxPlan = delta > 0 ? this.boxPlan.concat([['']]) : this.boxPlan.slice(0, next)
		},

		/** 某一箱的罐数步进：越界弹 Alert（每箱各自独立）。 */
		stepCan(boxIndex, delta) {
			const counts = this.boxPlan[boxIndex] || []
			const next = counts.length + delta
			if (next < MIN_CANS || next > MAX_CANS) {
				uni.showModal({
					title: '罐数超出范围',
					content: '罐数必须在 ' + MIN_CANS + '～' + MAX_CANS + ' 之间',
					showCancel: false
				})
				return
			}
			const list = this.boxPlan.map((item) => item.slice())
			list[boxIndex] = delta > 0 ? counts.concat(['']) : counts.slice(0, next)
			this.boxPlan = list
		},

		onParticleInput(boxIndex, canIndex, event) {
			const raw = (event.detail && event.detail.value) || ''
			const list = this.boxPlan.map((counts) => counts.slice())
			if (!list[boxIndex]) return
			list[boxIndex][canIndex] = raw
			this.boxPlan = list
		},

		structureIssues() {
			return validateStructure(this.boxPlan.map((counts) => counts.map((value) => Number(value))))
		},

		saveStructureDraft() {
			const issues = this.structureIssues()
			if (issues.length) {
				uni.showModal({
					title: '包装结构不合法',
					content: issues.map((item) => item.message).join('；'),
					showCancel: false
				})
				return false
			}
			uni.showToast({ title: '结构校验通过', icon: 'success' })
			return true
		},

		/** 硬校验通过 → 状态置「采集中」→ 跳扫码页（阶段 3 验收点）。 */
		enterCollecting() {
			// 先抓取用户此刻输入的包装结构：后面任何回读都不该动它。
			const counts = this.boxPlan.map((list) => list.map((value) => Number(value)))
			if (!this.persistBaseInfo()) return
			const issues = validateStructure(counts)
			if (issues.length) {
				uni.showModal({
					title: '包装结构不合法',
					content: issues.map((item) => item.message).join('；'),
					showCancel: false
				})
				return
			}
			let batch = getActiveBatch()
			if (batch && batch.status !== 'draft') {
				uni.switchTab({ url: '/pages/scan/scan' })
				return
			}
			if (!batch) {
				batch = saveBatch(createDraft({ ...this.form, deviceId: this.device.fingerprint }))
			}
			const result = saveStructure(batch, counts)
			if (result.issues && result.issues.length) {
				uni.showModal({
					title: '包装结构不合法',
					content: result.issues.map((item) => item.message).join('；'),
					showCancel: false
				})
				return
			}
			saveBatch(result.batch)
			this.refreshLocal()
			uni.showToast({ title: '已进入采集', icon: 'success' })
			setTimeout(() => uni.switchTab({ url: '/pages/scan/scan' }), 500)
		},

		saveServer() {
			setServer({ baseUrl: this.normalize(this.baseUrl), wsUrl: this.normalize(this.wsUrl) })
			uni.showToast({ title: '已保存', icon: 'success' })
		},

		statusText(status) {
			return STATUS_LABELS[status] || status
		},

		/** 删除当前批次（删掉才能重新建下一批）。 */
		deleteCurrentBatch() {
			if (!this.localId) return
			const target = this.localId
			uni.showModal({
				title: '删除当前批次？',
				content: '本机数据会被清掉，不可恢复。已采到的条码也会一起消失。',
				confirmText: '删除',
				cancelText: '取消',
				success: (res) => {
					if (!res.confirm) return
					removeBatch(target)
					this.refreshLocal()
					this.form = { batchNo: '', produceDate: '', expireDate: '' }
					this.boxPlan = [['']]
					uni.showToast({ title: '已删除', icon: 'success' })
				}
			})
		},

		/** 清空本机全部批次（换人/换线时用）。 */
		clearLocalBatches() {
			uni.showModal({
				title: '清空本机全部批次？',
				content: `本机 ${this.localBatches.length} 个批次都会被删掉，不可恢复。`,
				confirmText: '清空',
				cancelText: '取消',
				success: (res) => {
					if (!res.confirm) return
					clearAll()
					this.refreshLocal()
					this.form = { batchNo: '', produceDate: '', expireDate: '' }
					this.boxPlan = [['']]
					uni.showToast({ title: '已清空', icon: 'success' })
				}
			})
		},

		saveToken() {
			setServer({ token: (this.token || '').trim() })
			uni.showToast({ title: '已保存', icon: 'success' })
		},

		/** 测试连接：失败只提示离线模式，不阻塞（阶段 6 验收点）。 */
		async testHealth() {
			this.busy = true
			this.healthMessage = ''
			try {
				setServer({ baseUrl: this.normalize(this.baseUrl), wsUrl: this.normalize(this.wsUrl) })
				const health = await api.health()
				this.healthOk = true
				this.healthMessage = `服务版本 ${health.version}，Python ${health.python}，基准一致 ${health.goldenOk ? '是' : '否'}`
			} catch (error) {
				this.healthOk = false
				this.healthMessage = '当前为离线模式，数据将保存在本机（二期同步后才需要连主控机）。'
			} finally {
				this.busy = false
			}
		},

		async loadBatches() {
			this.busy = true
			try {
				setServer({ baseUrl: this.normalize(this.baseUrl) })
				const list = await api.listBatches()
				this.batches = list.items || []
				if (!this.batches.length) {
					this.healthMessage = '主控机还没有批次（也不影响本机建批次）。'
				}
			} catch (error) {
				this.healthMessage = '当前为离线模式，读不到主控机批次。'
			} finally {
				this.busy = false
			}
		},

		chooseBatch(item) {
			setServer({ batchId: item.id, batchNo: item.batchNo })
			this.currentBatchId = item.id
			uni.showToast({ title: `已选 ${item.batchNo}`, icon: 'none' })
		}
	}
}

/** 日期加天数：`YYYY-MM-DD` → `YYYY-MM-DD`（本地时区，不引第三方库）。 */
function addDays(iso, days) {
	const parts = String(iso || '').split('-').map((value) => Number(value))
	if (parts.length !== 3 || parts.some((value) => !Number.isFinite(value))) return ''
	const date = new Date(parts[0], parts[1] - 1, parts[2])
	date.setDate(date.getDate() + days)
	const month = String(date.getMonth() + 1).padStart(2, '0')
	const day = String(date.getDate()).padStart(2, '0')
	return `${date.getFullYear()}-${month}-${day}`
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

.field-label {
	display: block;
	font-size: 26rpx;
	color: #101a22;
	margin-top: 20rpx;
}

.row-between {
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.field {
	margin-top: 20rpx;
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

.picker-value {
	line-height: 76rpx;
}

.fold {
	display: flex;
	align-items: center;
	justify-content: space-between;
	margin-top: 24rpx;
	padding: 20rpx;
	background: #f1f4f6;
	border-radius: 8rpx;
}

.fold-title {
	font-size: 26rpx;
}

.fold-mark {
	font-size: 24rpx;
	color: #0e6e7a;
}

.fixed-list {
	margin-top: 12rpx;
}

.stepper {
	display: flex;
	align-items: center;
}

.step-btn {
	width: 72rpx;
	height: 72rpx;
	line-height: 72rpx;
	padding: 0;
	margin: 0 8rpx;
	background: #ffffff;
	border: 1rpx solid #b6c2ca;
	border-radius: 8rpx;
	font-size: 32rpx;
}

.step-value {
	min-width: 80rpx;
	text-align: center;
	font-size: 32rpx;
}

.particle-row {
	margin-top: 8rpx;
}

.progress-row {
	margin-top: 20rpx;
}

.progress {
	height: 16rpx;
	margin-top: 12rpx;
	background: #eef1f4;
	border-radius: 999rpx;
	overflow: hidden;
}

.progress-bar {
	height: 16rpx;
	background: #0e6e7a;
}

.progress-bar.over {
	background: #b91c1c;
}

.alarm-hint {
	display: block;
	margin-top: 12rpx;
	padding: 12rpx 16rpx;
	font-size: 24rpx;
	color: #b91c1c;
	background: #fdeaea;
	border: 1rpx solid #f0b4b4;
	border-radius: 8rpx;
}

.batch-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 20rpx 0;
	border-bottom: 1rpx solid #eef1f4;
}

.batch-main {
	flex: 1;
}

.batch-list {
	margin-top: 8rpx;
}

/* 多箱结构：每箱一块，块内是该箱的罐数步进器与每罐粒子数输入框 */
.box-block {
	margin-top: 16rpx;
	padding: 16rpx 20rpx 8rpx;
	background: #f7fafb;
	border: 1rpx solid #e2ebee;
	border-radius: 12rpx;
}

.box-head {
	margin-bottom: 6rpx;
}

.box-title {
	font-size: 28rpx;
	font-weight: 600;
	color: #0e6e7a;
}

.stats {
	display: flex;
	margin-top: 20rpx;
}

.stat {
	flex: 1;
	display: flex;
	flex-direction: column;
	align-items: center;
	padding: 16rpx 0;
	background: #f1f6f8;
	border-radius: 12rpx;
	margin-right: 12rpx;
}

.stat:last-child {
	margin-right: 0;
}

.stat-key {
	font-size: 22rpx;
	color: #8697a3;
}

.stat-value {
	margin-top: 6rpx;
	font-size: 32rpx;
	font-weight: 600;
}

.batch-no {
	display: block;
	font-size: 28rpx;
}

.batch-meta {
	display: block;
	margin-top: 6rpx;
	font-size: 22rpx;
	color: #8697a3;
}

.info-row {
	display: flex;
	margin-top: 12rpx;
}

.info-key {
	width: 180rpx;
	font-size: 26rpx;
	color: #8697a3;
}

.info-value {
	flex: 1;
	font-size: 26rpx;
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

button.primary {
	background: #0e6e7a;
	color: #ffffff;
	margin-top: 16rpx;
}
</style>
