<template>
	<view class="page">
		<!-- 无本地数据：只提示，不发请求、不报错 -->
		<view v-if="!hasData" class="card">
			<view class="row-between">
				<text class="card-title">整体核对</text>
				<text class="badge badge-neutral">暂无数据</text>
			</view>
			<text class="hint">请先完成扫码采集。</text>
			<button class="secondary" @click="go('scan')">去扫码采集</button>
		</view>

		<template v-else>
			<view class="card">
				<view class="row-between">
					<text class="card-title">整体核对</text>
					<text :class="['badge', canVerify ? 'badge-ok' : 'badge-error']">
						{{ canVerify ? '可以核对' : '存在缺漏' }}
					</text>
				</view>
				<text class="hint">计划 vs 实际逐罐对照；缺漏未签名时不允许确认核对。</text>

				<view class="compare">
					<view class="compare-row compare-head">
						<text class="col-a">项目</text>
						<text class="col-b">计划</text>
						<text class="col-b">实际</text>
					</view>
					<view class="compare-row">
						<text class="col-a">箱</text>
						<text class="col-b code">{{ review.plan.boxCount }}</text>
						<text class="col-b code">{{ review.actual.boxCount }}</text>
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

				<view class="info-row">
					<text class="info-key">本地批次</text>
					<text class="info-value code">{{ batch.batchNo }} · {{ review.statusLabel }}</text>
				</view>
				<view class="info-row">
					<text class="info-key">设备指纹</text>
					<text class="info-value code">{{ batch.deviceId || '（未记录）' }}</text>
				</view>
				<view v-if="review.earlyEnd" class="info-row">
					<text class="info-key">提前结束</text>
					<text class="info-value">{{ review.earlyEnd.reason }} · {{ review.earlyEnd.operator }}</text>
				</view>

				<button class="primary" :disabled="busy || !canVerify" @click="confirmReview">
					确认核对（置为已核对）
				</button>
				<text v-if="!canVerify" class="hint">补齐缺漏，或在下面登记提前结束（原因 + 操作人）后再确认。</text>
			</view>

			<view class="card">
				<text class="card-title">逐箱逐罐明细</text>
				<view v-for="box in review.perBox" :key="box.boxIndex" class="box-group">
					<view class="row-between box-head">
						<text class="box-title">箱 {{ box.boxIndex }}</text>
						<text class="hint">
							{{ box.boxCode || '（未扫箱号）' }} · 计划 {{ box.plannedCans }} 罐 / 实际 {{ box.scannedCans }} 罐
						</text>
					</view>
					<view class="compare">
						<view class="compare-row compare-head">
							<text class="col-a">罐</text>
							<text class="col-b">计划</text>
							<text class="col-b">实际</text>
							<text class="col-c">缺漏</text>
						</view>
						<view
							v-for="row in cansOfBox(box.boxIndex)"
							:key="box.boxIndex + '-' + row.canIndex"
							:class="['compare-row', row.missing > 0 ? 'row-missing' : '']"
						>
							<text class="col-a">{{ row.canIndex }}</text>
							<text class="col-b code">{{ row.planned }}</text>
							<text class="col-b code">{{ row.scanned }}</text>
							<text class="col-c code">{{ row.missing > 0 ? '缺 ' + row.missing : '0' }}</text>
						</view>
					</view>
				</view>
			</view>

			<view class="card">
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
				<view v-if="review.blocking.length" class="blocked">
					<text class="blocked-title">阻断原因</text>
					<text v-for="item in review.blocking" :key="item.code" class="blocked-message">
						· {{ item.label }}：{{ item.detail }}
					</text>
				</view>
			</view>

			<view class="card">
				<view class="row-between">
					<text class="card-title">本地固化数据预览</text>
					<text class="badge badge-info">本机生成的 XML</text>
				</view>
				<text class="hint">本机生成的 XML 预览（一期不产出文件，仅本地查看）。</text>
				<text v-if="skippedSlots" class="hint">已跳过 {{ skippedSlots }} 个未采集槽位。</text>
				<scroll-view scroll-y class="preview">
					<text class="preview-text code" selectable="true">{{ xmlText }}</text>
				</scroll-view>
				<button class="ghost" :disabled="busy" @click="refresh">重新读取本地数据</button>
				<button class="primary" :disabled="busy || !xmlText" @click="exportHtml">导出为 .html</button>
				<view v-if="exportRecord" class="export-box">
					<text class="export-line">最近导出：{{ exportRecord.name }}</text>
					<text class="export-line">大小：{{ exportRecord.size }} 字节 · 方式：{{ exportRecord.by }}</text>
					<text class="export-line">路径：{{ exportRecord.path }}</text>
					<button class="secondary" :disabled="busy" @click="openExport">用浏览器打开</button>
				</view>
			</view>

			<view class="card">
				<text class="card-title">提前结束</text>
				<text class="hint">
					实际少于计划时不能确认核对，需办理提前结束并填写原因与操作人。
					实际数量由本机数据算出，界面改不了。
				</text>
				<input class="input code" v-model="reason" placeholder="提前结束原因（必填）" />
				<input class="input code" v-model="operator" placeholder="操作人（必填）" />
				<input class="input code" v-model="note" placeholder="备注（可选）" />
				<button class="secondary" :disabled="busy" @click="submitEarlyEnd">登记提前结束</button>
				<button v-if="review.earlyEnd" class="ghost" :disabled="busy" @click="clearEarlyEnd">撤销提前结束登记</button>
			</view>

		</template>

	</view>
</template>

<script>
import { ensureDefaults } from '../../services/store'
import {
	clearEarlyEnd,
	getActiveBatch,
	registerEarlyEnd,
	review as reviewBatch,
	saveBatch,
	transition
} from '../../services/localBatch'
import { exportNodes, renderHtml, renderXml, xmlFileName } from '../../services/xmlGenerator'

export default {
	data() {
		return {
			batch: null,
			review: null,
			busy: false,
			reason: '',
			operator: '',
			note: '',
			// 本机生成的 XML（原样字符串，界面不做任何格式化）
			xmlText: '',
			skippedSlots: 0,
			// 最近一次导出的结构化记录：{ name, size, by, path }
			exportRecord: null
		}
	},

	computed: {
		hasData() {
			return !!(this.batch && this.batch.boxes && this.batch.boxes.length)
		},
		canVerify() {
			return !!(this.review && this.review.canVerify)
		}
	},

	onShow() {
		ensureDefaults()
		this.refresh()
	},

	methods: {
		/** 只读本机存储，不请求服务端（离线也能看）。 */
		refresh() {
			this.batch = getActiveBatch()
			this.review = this.hasData ? reviewBatch(this.batch) : null
			// 本机生成 XML（原样字符串，界面绝不二次格式化）
			this.xmlText = this.batch ? renderXml(this.batch) : ''
			this.skippedSlots = this.batch ? exportNodes(this.batch).skipped : 0
		},

		/** App 端：把内容写到 _doc 下的临时文件，返回 FileEntry。 */
		writeDocFile(name, content) {
			return new Promise((resolve, reject) => {
				plus.io.requestFileSystem(
					plus.io.PRIVATE_DOC,
					(fs) => {
						fs.root.getFile(
							name,
							{ create: true },
							(entry) => {
								entry.createWriter((writer) => {
									writer.onwrite = () => resolve(entry)
									writer.onerror = reject
									writer.write(content)
								}, reject)
							},
							reject
						)
					},
					reject
				)
			})
		},

		entrySize(entry) {
			return new Promise((resolve) => {
				entry.file((file) => resolve(file.size), () => resolve(0))
			})
		},

		/**
		 * 导出 .html（拍板决策 2：uni.saveFile 为主，失败降级 uni.shareWithSystem）。
		 *
		 * 阶段 0 实测：uni.saveFile 会把文件名改成随机号（如 17905503685290.html），
		 * 与「文件名严格按 Relation_{批号}_{时间}.html」冲突，所以落盘后再用 plus.io 改回规范名。
		 */
		async saveHtml(fileName, html) {
			// #ifdef APP-PLUS
			const tempEntry = await this.writeDocFile(fileName, html)
			// 用真实文件字节数（不是 JS 字符串长度：中文按 UTF-8 是多字节）
			const size = await this.entrySize(tempEntry)
			try {
				const savedPath = await new Promise((resolve, reject) => {
					uni.saveFile({ tempFilePath: tempEntry.fullPath, success: (res) => resolve(res.savedFilePath), fail: reject })
				})
				const savedEntry = await new Promise((resolve, reject) => {
					plus.io.resolveLocalFileSystemURL(savedPath, resolve, reject)
				})
				const dirEntry = await new Promise((resolve, reject) => {
					plus.io.requestFileSystem(
						plus.io.PRIVATE_DOC,
						(fs) => fs.root.getDirectory('uniapp_save', { create: true }, resolve, reject),
						reject
					)
				})
				try {
					const renamed = await new Promise((resolve, reject) => {
						savedEntry.moveTo(dirEntry, fileName, resolve, reject)
					})
					return { name: fileName, path: renamed.fullPath, size, by: 'saveFile' }
				} catch (renameError) {
					// 改不回规范名也不能算失败：文件已经落盘了，如实报告实际名字
					return { name: String(savedPath).split('/').pop(), path: savedPath, size, by: 'saveFile' }
				}
			} catch (error) {
				// 降级：系统分享面板（临时文件本身已经是规范名，分享出去名字就是对的）
				await new Promise((resolve, reject) => {
					uni.shareWithSystem({
						summary: `批次 ${this.batch ? this.batch.batchNo : ''} 关联关系 XML`,
						filePath: tempEntry.fullPath,
						success: resolve,
						fail: reject
					})
				})
				return { name: fileName, path: tempEntry.fullPath, size, by: 'shareWithSystem' }
			}
			// #endif
			// #ifndef APP-PLUS
			return Promise.reject(new Error('当前运行环境不支持导出，请在手机 App 里操作。'))
			// #endif
		},

		/** 「导出为 .html」按钮。 */
		/**
		 * 「用浏览器打开」：阶段 0 实测结论（`阶段0-打开能力实测结论.md`）——
		 * 主路径 `plus.runtime.openFile`（内部走 DCloud FileProvider + FLAG_GRANT_READ_URI_PERMISSION，
		 * 系统会弹「打开方式」选择器，实测能看到「HTML 查看器」）；
		 * 失败降级 `uni.openDocument({ fileType:'html', showMenu:true })`（html 不在官方支持列表，但实测能弹选择器）；
		 * 两条都不行就给明确提示，不静默。
		 */
		openExport() {
			if (!this.exportRecord || !this.exportRecord.path) return
			const { path, name } = this.exportRecord
			// #ifdef APP-PLUS
			// 先确认文件还在（导出目录是应用私有外部目录，文件可能被清理）
			plus.io.resolveLocalFileSystemURL(
				path,
				(entry) => {
					entry.file(
						() => this.openBySystem(path, name),
						() => uni.showToast({ title: '文件不存在或已被删除', icon: 'none' })
					)
				},
				() => uni.showToast({ title: '文件不存在或已被删除', icon: 'none' })
			)
			return
			// #endif
			// #ifndef APP-PLUS
			uni.showToast({ title: '请在手机 App 里打开导出的文件', icon: 'none' })
			// #endif
		},

		/** 主路径 + 降级路径（只在 App 端调用）。 */
		openBySystem(path, name) {
			plus.runtime.openFile(
				path,
				{},
				() => {},
				() => {
					uni.openDocument({
						filePath: path,
						fileType: 'html',
						showMenu: true,
						fail: () => {
							uni.showModal({
								title: '打不开这个文件',
								content: `没有找到能打开「${name}」的应用。请先装一个浏览器或文件管理器再试。`,
								showCancel: false
							})
						}
					})
				}
			)
		},

		async exportHtml() {
			if (!this.batch || !this.xmlText) return
			this.busy = true
			this.exportRecord = null
			try {
				const fileName = xmlFileName(this.batch.batchNo, new Date())
				const html = renderHtml(this.xmlText, this.batch.batchNo)
				const saved = await this.saveHtml(fileName, html)
				this.exportRecord = {
					name: saved.name,
					size: saved.size,
					by: saved.by,
					path: saved.path
				}
				uni.showToast({ title: 'HTML 文件已导出至应用存储', icon: 'none' })
			} catch (error) {
				uni.showModal({
					title: '导出失败',
					content: `保存与分享都没成功：${(error && (error.message || error.errMsg)) || '未知错误'}。请确认手机有可用的存储或分享应用后重试。`,
					showCancel: false
				})
			} finally {
				this.busy = false
			}
		},

		go(page) {
			uni.switchTab({ url: `/pages/${page}/${page}` })
		},

		/** 取某一箱的罐明细（模板里按箱分组渲染）。 */
		cansOfBox(boxIndex) {
			if (!this.review) return []
			return this.review.perCan.filter((row) => row.boxIndex === boxIndex)
		},

		confirmReview() {
			if (!this.canVerify) return
			const moved = transition(this.batch, 'verified')
			if (moved.event) {
				uni.showModal({ title: '无法确认核对', content: moved.event.message, showCancel: false })
				return
			}
			saveBatch(moved.batch)
			this.refresh()
			uni.showToast({ title: '已核对（本机）', icon: 'success' })
		},

		submitEarlyEnd() {
			const result = registerEarlyEnd(this.batch, {
				reason: this.reason,
				operator: this.operator,
				note: this.note
			})
			if (result.event && result.event.code !== 'OK') {
				uni.showModal({ title: '登记失败', content: result.event.message, showCancel: false })
				return
			}
			saveBatch(result.batch)
			this.reason = ''
			this.note = ''
			this.refresh()
			uni.showToast({ title: '已登记提前结束', icon: 'success' })
		},

		clearEarlyEnd() {
			saveBatch(clearEarlyEnd(this.batch).batch)
			this.refresh()
			uni.showToast({ title: '已撤销登记', icon: 'none' })
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
	width: 120rpx;
	font-size: 26rpx;
}

.col-b {
	flex: 1;
	font-size: 26rpx;
}

.col-c {
	width: 140rpx;
	font-size: 26rpx;
	text-align: right;
}

.row-missing {
	background: #fdeaea;
}

/* 多箱：逐箱分块，块内是该箱的罐明细表 */
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
	font-size: 26rpx;
}

.check-detail {
	display: block;
	font-size: 22rpx;
	color: #8697a3;
	/* 详情里可能出现长串数字（如每罐计划 1/1/1 · 5 罐一串），兜底折行 */
	word-break: break-all;
	word-wrap: break-word;
}

.blocked {
	margin-top: 16rpx;
	padding: 16rpx;
	background: #fdf3e5;
	border: 1rpx solid #f0cfa0;
	border-radius: 8rpx;
}

.blocked-title {
	display: block;
	font-size: 26rpx;
	color: #b45309;
	font-weight: 600;
}

.blocked-message {
	display: block;
	font-size: 24rpx;
	color: #b45309;
	margin-top: 6rpx;
	word-break: break-all;
	word-wrap: break-word;
}

.preview {
	/* 折行后内容会变高，留更大的可视区 + 纵向滚动（不加横向滚动） */
	height: 720rpx;
	margin-top: 12rpx;
	padding: 16rpx;
	background: #f8fafb;
	border: 1rpx solid #d6dee3;
	border-radius: 8rpx;
}

.preview-text {
	font-size: 20rpx;
	line-height: 1.75;
	color: #101a22;
	/* 关键：保留原有换行符，同时允许长行折行；20 位条码/长属性不再被右侧裁掉 */
	white-space: pre-wrap;
	word-break: break-all;
	word-wrap: break-word;
}

/* 最近导出：结构化分组 + 每行都能折行，文件名与完整路径绝不省略 */
.export-box {
	margin-top: 16rpx;
	padding: 16rpx 20rpx;
	background: #f7fafb;
	border: 1rpx solid #e2ebee;
	border-radius: 12rpx;
}

.export-line {
	display: block;
	font-size: 22rpx;
	line-height: 1.7;
	color: #101a22;
	white-space: pre-wrap;
	word-break: break-all;
	word-wrap: break-word;
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
	word-break: break-all;
	word-wrap: break-word;
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
</style>
