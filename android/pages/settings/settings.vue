<template>
	<view class="page">
		<view class="card">
			<text class="card-title">服务地址</text>
			<text class="hint">
				填写 Windows 主控机的局域网地址。Windows 端需以 `--host 0.0.0.0` 启动服务，
				否则手机连不上（默认只监听 127.0.0.1）。
			</text>
			<input class="input code" v-model="baseUrl" placeholder="http://192.168.1.20:17800" />
			<input class="input code" v-model="wsUrl" placeholder="ws://192.168.1.20:17801（留空则自动推导）" />
			<button class="secondary" :disabled="busy" @click="saveServer">保存</button>
		</view>

		<view class="card">
			<text class="card-title">连接测试</text>
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
			<text class="card-title">配对</text>
			<text class="hint">
				配对 Token 由 Windows 端签发，一次性、5 分钟过期，且绑定本机设备指纹。
				换个设备就失效 —— 这是防止 Token 被转发滥用。
			</text>
			<input class="input code" v-model="token" placeholder="粘贴配对 Token" />
			<button class="secondary" :disabled="busy" @click="saveToken">保存 Token</button>
		</view>

		<view class="card">
			<text class="card-title">当前批次</text>
			<text class="hint">默认自动选用 Windows 端第一个「采集中」的批次，也可以手动指定。</text>
			<button class="ghost" :disabled="busy" @click="loadBatches">读取批次列表</button>

			<view v-for="item in batches" :key="item.id" class="batch-row" @click="chooseBatch(item)">
				<view class="batch-main">
					<text class="code">{{ item.batchNo }}</text>
					<text class="hint">{{ item.statusLabel }} · {{ item.canCount }} 罐 / {{ item.actualParticleTotal }} 粒</text>
				</view>
				<text v-if="item.id === currentBatchId" class="badge badge-ok">已选</text>
			</view>
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
				<text class="info-key">系统</text>
				<text class="info-value">{{ systemInfo }}</text>
			</view>
		</view>

		<view class="card">
			<text class="card-title">一期没有的功能（别去找）</text>
			<text class="hint">账号登录（一期单机无账号体系）、离线补发、多端互斥锁的界面提示 —— 这些在二期后续批次。</text>
		</view>
	</view>
</template>

<script>
import { api, ApiError } from '../../services/api'
import { ensureDefaults, getDevice, getServer, setServer } from '../../services/store'

export default {
	data() {
		return {
			baseUrl: '',
			wsUrl: '',
			token: '',
			busy: false,
			healthOk: false,
			healthMessage: '',
			batches: [],
			currentBatchId: '',
			device: { name: '', fingerprint: '' },
			systemInfo: ''
		}
	},

	onShow() {
		ensureDefaults()
		const server = getServer()
		this.baseUrl = server.baseUrl
		this.wsUrl = server.wsUrl
		this.token = server.token
		this.currentBatchId = server.batchId
		this.device = getDevice()
		try {
			const info = uni.getSystemInfoSync()
			this.systemInfo = `${info.platform} ${info.system} / Android ${info.version || ''}`
		} catch (error) {
			this.systemInfo = '未知'
		}
	},

	methods: {
		normalize(value) {
			return (value || '').trim().replace(/\/$/, '')
		},

		saveServer() {
			setServer({ baseUrl: this.normalize(this.baseUrl), wsUrl: this.normalize(this.wsUrl) })
			uni.showToast({ title: '已保存', icon: 'success' })
		},

		saveToken() {
			setServer({ token: (this.token || '').trim() })
			uni.showToast({ title: '已保存', icon: 'success' })
		},

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
				this.healthMessage = error instanceof ApiError ? error.message : String(error)
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
					this.healthMessage = '服务端还没有批次。请先在 Windows 端创建批次并进入「采集中」。'
				}
			} catch (error) {
				this.healthMessage = error instanceof ApiError ? error.message : String(error)
			} finally {
				this.busy = false
			}
		},

		chooseBatch(item) {
			setServer({ batchId: item.id, batchNo: item.batchNo })
			uni.setStorageSync('pharmrelate.batchNo', item.batchNo)
			this.currentBatchId = item.id
			uni.showToast({ title: `已选 ${item.batchNo}`, icon: 'none' })
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

.input {
	height: 76rpx;
	padding: 0 20rpx;
	margin: 16rpx 0;
	background: #f8fafb;
	border: 1rpx solid #d6dee3;
	border-radius: 8rpx;
	font-size: 26rpx;
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
	margin-top: 16rpx;
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
</style>
