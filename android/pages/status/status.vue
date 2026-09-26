<template>
	<view class="page">
		<view class="card">
			<view class="row-between">
				<text class="card-title">整体核对</text>
				<text :class="['badge', canExport ? 'badge-ok' : 'badge-error']">
					{{ canExport ? '可以导出' : '导出被禁止' }}
				</text>
			</view>
			<text class="hint">计划 vs 实际逐罐对照。缺漏未签名时禁止导出。</text>

			<view v-if="review" class="compare">
				<view class="compare-row compare-head">
					<text class="col-a">项目</text>
					<text class="col-b">计划</text>
					<text class="col-b">实际</text>
				</view>
				<view class="compare-row">
					<text class="col-a">罐</text>
					<text class="col-b code">{{ review.plan.canCount }}</text>
					<text class="col-b code">{{ review.actual.canCount }}</text>
				</view>
				<view class="compare-row">
					<text class="col-a">粒子</text>
					<text class="col-b code">{{ review.plan.particleTotal }}</text>
					<text class="col-b code">{{ review.actual.particleTotal }}</text>
				</view>
			</view>
		</view>

		<view v-if="review" class="card">
			<text class="card-title">逐罐明细</text>
			<view class="compare">
				<view class="compare-row compare-head">
					<text class="col-a">罐</text>
					<text class="col-b">计划</text>
					<text class="col-b">实际</text>
					<text class="col-c">缺漏</text>
				</view>
				<view
					v-for="row in review.perCan"
					:key="row.index"
					:class="['compare-row', row.missing > 0 ? 'row-missing' : '']"
				>
					<text class="col-a">{{ row.index }}</text>
					<text class="col-b code">{{ row.planned }}</text>
					<text class="col-b code">{{ row.scanned }}</text>
					<text class="col-c code">{{ row.missing > 0 ? '缺 ' + row.missing : '0' }}</text>
				</view>
			</view>
		</view>

		<view v-if="review" class="card">
			<text class="card-title">检查项</text>
			<view v-for="item in review.checks" :key="item.code" class="check-row">
				<text :class="['check-mark', item.passed ? 'mark-ok' : 'mark-bad']">
					{{ item.passed ? '✓' : '✕' }}
				</text>
				<view class="check-body">
					<text class="check-label">{{ item.label }}</text>
					<text class="check-detail">{{ item.detail }}</text>
				</view>
			</view>
		</view>

		<view v-if="review && review.blocking.length" class="card">
			<text class="card-title">阻断原因</text>
			<view v-for="item in review.blocking" :key="item.code" class="blocked-row">
				<text class="blocked-message">{{ item.message }}</text>
				<text class="blocked-action">→ {{ item.action }}</text>
			</view>
		</view>

		<view class="card">
			<text class="card-title">导出到手机</text>
			<text class="hint">
				XML 由 Windows 端生成（与电脑端导出是同一份产物、同一条导出记录），
				手机只负责保存与分享。文件名与电脑端一致：Relation_批号_时间戳.xml
			</text>
			<button class="primary" :disabled="busy || !canExport" @click="exportXml">
				导出 XML 到手机
			</button>
			<view v-if="exportedFile" class="info-row">
				<text class="info-key">文件</text>
				<text class="info-value code">{{ exportedFile.filename }}</text>
			</view>
			<view v-if="exportedFile && exportedFile.sha256" class="info-row">
				<text class="info-key">SHA-256</text>
				<text class="info-value code">{{ exportedFile.sha256.slice(0, 16) }}…</text>
			</view>
			<text v-if="exportedFile" class="hint code">{{ exportedFile.path }}</text>
			<button v-if="exportedFile" class="ghost" :disabled="busy" @click="shareXml">分享这个文件</button>
		</view>

		<view class="card">
			<text class="card-title">提前结束</text>
			<text class="hint">
				实际少于计划时导出被禁止，需办理提前结束并填写原因与操作人。
				实际数量由服务端填写，界面改不了。
			</text>

			<view v-if="earlyEnd" class="early-end-info">
				<text class="check-label">已登记：{{ earlyEnd.reason }}</text>
				<text class="check-detail">操作人 {{ earlyEnd.operator }} · {{ earlyEnd.at }}</text>
				<text class="check-detail code">
					实际 {{ earlyEnd.actualCanCount }} 罐 / {{ earlyEnd.actualParticleCount }} 粒
				</text>
			</view>

			<view v-else class="early-end-form">
				<input class="input" v-model="reason" placeholder="提前结束原因（必填）" />
				<input class="input" v-model="operator" placeholder="操作人（必填）" />
				<input class="input" v-model="note" placeholder="备注（可选）" />
				<button class="secondary" :disabled="busy" @click="submitEarlyEnd">登记提前结束</button>
			</view>
		</view>

		<view class="card">
			<text class="card-title">刷新</text>
			<button class="ghost" :disabled="busy" @click="load">重新读取核对结果</button>
			<text class="hint">{{ errorMessage || '数据来自服务端，界面不做本地判断。' }}</text>
		</view>
	</view>
</template>

<script>
import { api, ApiError, exportXmlUrl } from '../../services/api'
import { getDevice, getServer } from '../../services/store'

export default {
	data() {
		return {
			busy: false,
			review: null,
			errorMessage: '',
			reason: '',
			operator: '',
			note: '',
			/** 已导出的文件：保存路径 + 服务端记录的文件名与哈希 */
			exportedFile: null
		}
	},

	computed: {
		canExport() {
			return !!(this.review && this.review.canExport)
		},
		earlyEnd() {
			return (this.review && this.review.earlyEnd) || null
		}
	},

	onShow() {
		this.load()
	},

	methods: {
		async load() {
			const server = getServer()
			if (!server.batchId) {
				this.errorMessage = '尚未选择批次，请先到「扫码」页刷新任务状态。'
				return
			}
			this.busy = true
			try {
				this.review = await api.review(server.batchId)
				this.errorMessage = ''
			} catch (error) {
				this.errorMessage = error instanceof ApiError ? error.message : String(error)
			} finally {
				this.busy = false
			}
		},

		async submitEarlyEnd() {
			if (!this.reason.trim() || !this.operator.trim()) {
				this.errorMessage = '提前结束必须填写原因与操作人。'
				return
			}
			this.busy = true
			try {
				await api.registerEarlyEnd(getServer().batchId, this.reason.trim(), this.operator.trim(), this.note.trim())
				this.reason = ''
				this.note = ''
				await this.load()
			} catch (error) {
				this.errorMessage = error instanceof ApiError ? error.message : String(error)
			} finally {
				this.busy = false
			}
		},

		/**
		 * 导出 XML 到手机：下载 → 保存到应用存储 → 显示文件名与哈希。

		 * 文件内容不经过前端拼接，直接从服务端取；保存后可从导出记录里
		 * 拿到与电脑端完全相同的文件名与 SHA-256，便于两端核对是同一份。
		 */
		async exportXml() {
			const server = getServer()
			this.busy = true
			this.errorMessage = ''
			try {
				const url = exportXmlUrl(server.batchId, getDevice().name)
				const download = await new Promise((resolve, reject) => {
					uni.downloadFile({ url, timeout: 30000, success: resolve, fail: reject })
				})
				if (download.statusCode !== 200) {
					throw new Error(`导出被服务端拒绝（HTTP ${download.statusCode}），请先完成整体核对。`)
				}
				const saved = await new Promise((resolve, reject) => {
					uni.saveFile({ tempFilePath: download.tempFilePath, success: resolve, fail: reject })
				})
				let filename = ''
				let sha256 = ''
				try {
					const history = await api.exportHistory(server.batchId)
					const latest = (history.items || [])[0]
					if (latest) {
						filename = latest.filename
						sha256 = latest.sha256
					}
				} catch (error) {
					// 记录取不到不影响文件已保存这个事实
				}
				this.exportedFile = { path: saved.savedFilePath, filename, sha256 }
				uni.showToast({ title: '已保存到手机', icon: 'success' })
				await this.load()
			} catch (error) {
				this.errorMessage = error instanceof ApiError ? error.message : String(error)
			} finally {
				this.busy = false
			}
		},

		/** 系统分享面板（App 端原生能力，不需要额外 SDK 配置）。 */
		shareXml() {
			if (!this.exportedFile) return
			uni.shareWithSystem({
				type: 'file',
				filePath: this.exportedFile.path,
				summary: `籽关通导出文件：${this.exportedFile.filename || ''}`,
				success: () => uni.showToast({ title: '已打开系统分享', icon: 'none' }),
				fail: () =>
					uni.showToast({
						title: '系统分享不可用，请按上面的路径到文件管理器查找',
						icon: 'none'
					})
			})
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

.hint {
	display: block;
	font-size: 24rpx;
	color: #5a6b77;
	margin-top: 8rpx;
}

.compare {
	margin-top: 16rpx;
}

.compare-row {
	display: flex;
	padding: 12rpx 0;
	border-bottom: 1rpx solid #eef1f4;
}

.compare-head {
	color: #8697a3;
	font-size: 24rpx;
}

.col-a {
	width: 30%;
}

.col-b {
	width: 30%;
}

.col-c {
	width: 40%;
}

/* 缺漏行用左侧色条 + 红字，颜色不是唯一线索 */
.row-missing {
	background: #fdeaea;
	border-left: 6rpx solid #b91c1c;
	padding-left: 12rpx;
}

.row-missing .col-c {
	color: #b91c1c;
	font-weight: 600;
}

.check-row {
	display: flex;
	margin-top: 16rpx;
}

.check-mark {
	width: 40rpx;
	font-size: 28rpx;
}

.mark-ok {
	color: #15803d;
}

.mark-bad {
	color: #b91c1c;
}

.check-body {
	flex: 1;
}

.check-label {
	display: block;
	font-size: 28rpx;
}

.check-detail {
	display: block;
	font-size: 24rpx;
	color: #5a6b77;
	margin-top: 4rpx;
}

.blocked-row {
	margin-top: 16rpx;
	padding: 16rpx;
	background: #fdeaea;
	border: 1rpx solid #f0b4b4;
	border-radius: 8rpx;
}

.blocked-message {
	display: block;
	color: #b91c1c;
	font-size: 26rpx;
}

.blocked-action {
	display: block;
	color: #5a6b77;
	font-size: 24rpx;
	margin-top: 8rpx;
}

.early-end-form {
	margin-top: 16rpx;
}

.input {
	height: 76rpx;
	padding: 0 20rpx;
	margin-bottom: 16rpx;
	background: #f8fafb;
	border: 1rpx solid #d6dee3;
	border-radius: 8rpx;
	font-size: 26rpx;
}

.early-end-info {
	margin-top: 16rpx;
	padding: 16rpx;
	background: #fdf3e5;
	border: 1rpx solid #f0cfa0;
	border-radius: 8rpx;
}

button.secondary {
	background: #ffffff;
	color: #101a22;
	border: 1rpx solid #b6c2ca;
}

button.ghost {
	background: transparent;
	color: #0e6e7a;
	border: 1rpx solid #a9d3d9;
}
</style>
