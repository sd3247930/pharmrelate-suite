<template>
	<view class="page">
		<!--
			批量连续扫码（plus.barcode 原生控件）：这一张卡片就是给原生控件「留位」的。
			原生控件由 pages/scan 通过 utils/batchBarcodeScanner.js 挂到 App Webview 上，
			位置按这张卡片实测出来的矩形来定（position: static，随页面滚动），
			所以它不会盖住下面的按钮 —— 按钮照常可以点。
		-->
		<view v-if="batchPanelOpen" class="card batch-scan-card">
			<view class="row-between">
				<text class="card-title">批量连续扫码</text>
				<view class="batch-scan-head">
					<text :class="['badge', batchScanBadgeClass]">{{ batchScannerStateLabel }}</text>
					<button class="batch-scan-sound" @click="toggleScanSound">
						{{ scanSoundOn ? '🔔 提示音开' : '🔕 提示音关' }}
					</button>
				</view>
			</view>
			<view id="batch-scan-slot" class="batch-scan-slot">
				<text class="batch-scan-slot-hint">{{ batchScanSlotHint }}</text>
			</view>
			<text class="hint">
				对准条码逐个扫入：重复码自动忽略，跨罐重复会报警；扫完点下面「✅ 完成扫码」。
				取景卡住时点「🔄 重新启动扫码」，不必退出本罐。
			</text>
			<text v-if="batchScanStatsText" class="hint">{{ batchScanStatsText }}</text>
		</view>

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
				<template v-if="batchPanelOpen">
					<button class="primary scan-btn" :disabled="busy" @click="stopBatchScan(false)">
						✅ 完成扫码（已扫 {{ currentCanScanned }}/{{ currentCanPlanned }}）
					</button>
					<button class="secondary" :disabled="busy" @click="restartBatchScan">
						🔄 重新启动扫码
					</button>
				</template>
				<template v-else>
					<button class="primary scan-btn" :disabled="busy" @click="startBatchScan">
						📷 批量连续扫码（{{ currentCanScanned }}/{{ currentCanPlanned }}）
					</button>
					<button class="secondary" :disabled="busy" @click="scanParticle">单次扫码一个</button>
					<button class="ghost" :disabled="busy" @click="endCanEarly">本罐先结束（缺漏留给整体核对）</button>
				</template>
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

			<!-- 需求 7：漏扫高亮警告条（只在本罐没扫满时出现） -->
			<text v-if="underFilledHint" class="underfill-warn">{{ underFilledHint }}</text>

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
					<text class="hint code">{{ box.boxCode || '（未扫箱号）' }}</text>
					<text class="box-title">箱 {{ box.boxIndex }}{{ box.virtual ? '（虚拟箱）' : '' }}</text>
				</view>
				<view v-for="row in box.cans" :key="row.canIndex" class="slot-row">
					<view class="row-between can-head">
						<text class="slot-can-code code">{{ row.canCode || '（未扫罐号）' }}</text>
						<text class="slot-can">罐 {{ row.canIndex }}</text>
					</view>
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
				<textarea
					class="input code batch-input"
					v-model="pasteCode"
					auto-height
					:maxlength="-1"
					placeholder="粘贴或输入粒子码序列号：支持空格、换行、中英文逗号/分号分隔，一次可录入多个（例如 6 个）"
				/>
				<button class="secondary" :disabled="batchSubmitting || !batch" @click="submitPaste">
					{{ wizard.phase === 'box' || wizard.phase === 'can' ? '提交' : '解析并填入' }}
				</button>
				<button class="ghost" :disabled="batchSubmitting || !batch" @click="openAlbumAssist">
					🖼 从图库选图辅助录入
				</button>
				<text class="hint">
					只输 {{ particleShortLength }} 位序列号会自动补前缀 {{ particlePrefix }}；重复码、错误前缀会被挡下并汇总提示。
					图库那张图只用于放大看清数字，本机不做自动识别、照片用完即弃。
				</text>
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

		<!--
			renderjs 桥：:change:prop 触发视图层（WebView）里的解码器 —— 那里才有
			Blob / Image / canvas / createImageBitmap，wasm 才能真正跑起来（服务层 JSCore 会卡死）。
			这个 view 不显示任何东西，只用来传任务、收结果。
		-->
		<view class="decoder-bridge" :prop="decodeTask" :change:prop="imageDecoder.onTaskChange"></view>

		<!-- 槽位操作浮层 -->
		<!--
			隐藏画布：只用于「图库图片 → 像素」，像素交给 zxing-wasm 解码条码。
			为什么不用 Blob/canvas API 在 JS 里做：App 的 JS 在服务层（JSCore），没有 Blob/Image，
			所以走 uni-app 自己的 canvas API（视图层绘制、像素回传服务层）。
		-->
		<view v-if="editing" class="overlay">
			<view class="sheet">
				<text class="sheet-title">
					箱 {{ editing.boxIndex + 1 }} · 罐 {{ editing.canIndex + 1 }} · 槽位 {{ editing.slotIndex + 1 }}（{{ editing.code ? '改' : '补录' }}）
				</text>
				<text class="hint code">{{ editing.code || '（空槽位）' }}</text>
				<input
					class="input code"
					v-model="replaceValue"
					:placeholder="editing.code ? '输入新的粒子码做替换' : '输入粒子码做补录'"
				/>
				<text class="hint">
					只输 {{ particleShortLength }} 位序列号会自动补前缀 {{ particlePrefix }}；也可以直接粘贴完整 20 位码（不会重复加前缀）。
				</text>
				<button class="primary" :disabled="slotSubmitting" @click="doReplace">
					{{ editing.code ? '替换' : '填入' }}
				</button>
				<button class="danger" :disabled="busy" @click="doDelete">删除该槽位</button>
				<button class="ghost" @click="editing = null">取消</button>
			</view>
		</view>

		<!-- 拍照识别：识别失败/无识别引擎时的降级浮层（人工读数后用下框输入；照片用完即弃） -->
		<view v-if="photo" class="overlay">
			<view class="sheet">
				<view class="row-between">
					<text class="sheet-title">{{ photoTitle }}</text>
					<text class="badge badge-neutral">{{ photo.recognizing ? '识别中' : '人工确认' }}</text>
				</view>
				<text v-if="photo.recognizing" class="hint">正在识别…（本机没有识别引擎时会立刻降级为人工读数）</text>
				<text class="hint">{{ photoHint }}</text>
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
				<!-- 粒子环节：图库/拍照辅助 —— 照着图在同一个多行面板里批量录入 -->
				<template v-if="photo.kind === 'particle'">
					<!-- OCR 候选区：识别成功才出现；没有插件时这里显示"无 OCR 插件"，下面照样能手输 -->
					<view class="row-between ocr-head">
						<text class="card-title">识别结果</text>
						<text :class="['badge', ocrBadgeClass]">{{ ocrStatusLabel }}</text>
					</view>
					<text v-if="ocrMessage" class="hint">{{ ocrMessage }}</text>
					<text v-if="deletedOcrCount" class="hint hint-deleted">
						已手动删除 {{ deletedOcrCount }} 条（不计入填入，可用「重新识别」找回）
					</text>
					<view v-if="ocrListRows.length" class="ocr-list">
						<view v-for="row in ocrListRows" :key="row.key" :class="['ocr-row', { 'is-deleted': row.deleted }]">
							<text class="ocr-index">{{ row.index }}</text>
							<text class="ocr-code code">{{ row.code || row.input }}</text>
							<text :class="['badge', row.badge]">{{ row.status }}</text>
							<button class="ghost ocr-del" :disabled="row.deleted" @click="removeOcrCandidate(row)">
								{{ row.deleted ? '已删除' : '删除' }}
							</button>
						</view>
					</view>
					<view v-if="ocrListRows.length" class="actions">
						<button class="secondary" :disabled="ocrStatus === 'running'" @click="rerunOcr">重新识别</button>
						<button class="primary" :disabled="batchSubmitting || !ocrFillableCodes.length" @click="submitOcrCandidates">
							确认有效码并填入（{{ ocrFillableCodes.length }}）
						</button>
						<button class="ghost" @click="clearOcrCandidates()">清空识别结果</button>
					</view>

					<textarea
						class="input code batch-input"
						v-model="pasteCode"
						auto-height
						:maxlength="-1"
						placeholder="照着图片输入粒子码序列号：空格/换行/逗号分隔，可一次多个"
					/>
					<button class="primary" :disabled="batchSubmitting" @click="submitPasteFromPhoto">解析并填入</button>
					<button class="ghost" :disabled="batchSubmitting" @click="openAlbumAssist">换一张图</button>
				</template>
				<template v-else>
					<button class="primary" :disabled="busy" @click="goManualFromPhoto">
						照着照片输入{{ photo.kind === 'box' ? '箱号' : '罐号' }}
					</button>
					<button class="ghost" :disabled="busy" @click="capturePhoto(photo.kind)">重拍</button>
				</template>
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
	extractDigits,
	fillParticleCodesIntoEmptySlots,
	fillSlot,
	finishRemaining,
	findCan,
	findUsage,
	forceEndCan,
	getActiveBatch,
	historyState,
	redo,
	replaceSlot,
	review,
	saveBatch,
	transition,
	undo
} from '../../services/localBatch'
import {
	PARTICLE_PREFIX,
	PARTICLE_SHORT_LENGTH,
	barcodeResultsToBlocks,
	buildOcrCandidateRows,
	normalizeParticleCode,
	parseOcrParticleCandidates,
	parseParticleBatch,
	selectFillableOcrCodes,
	summarizeBatchParse
} from '../../services/particleInput'
import { recognizeImage } from '../../services/ocr'
import {
	DECODER_MAX_SIDE,
	DECODER_SOFT_TIMEOUT_MS,
	DECODER_TIMEOUT_MS,
	IMAGE_CODE_DECODER_ENABLED,
	readImageAsDataUrl,
	readWasmAsDataUrl
} from '../../services/imageCodeDecoder'
import { createBatchBarcodeScanner, getCurrentAppWebview } from '../../utils/batchBarcodeScanner'

/**
 * 批量连续扫码的重启延迟不再由页面指定：盲区大小按识别结果分档，统一在
 * utils/batchBarcodeScanner.js 里（入库 200ms / 业务拒绝 120ms / 瞬时忽略 60ms）。
 * 页面只负责把「提示音开关」这类反馈设置喂给扫码器。
 */
const STORAGE_SCAN_SOUND = 'pharmrelate.scan.sound'

/** 页面自有事件码的中文标题（数据层那套 EVENT_LABELS 之外的部分）。 */
const LOCAL_EVENT_LABELS = {
	ERROR: '出错了',
	RETRY: '已放弃',
	PHOTO: '照片已拍好',
	MANUAL: '手动输入',
	EDIT: '需要修改',
	ILLEGAL_CHAR: '条码含非法字符'
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
			// 槽位补录/替换 防连点（原来借用的 busy 只服务"检查主控机在线"，等于没防抖）
			slotSubmitting: false,
			// 批量录入 防连点
			batchSubmitting: false,
			// 模板里要用到的粒子码规则常量（单一来源：services/particleInput.js）
			particlePrefix: PARTICLE_PREFIX,
			particleShortLength: PARTICLE_SHORT_LENGTH,
			// 图库 OCR（阶段 2 可降级）：插件不存在时 ocrStatus = 'unavailable'，走手动录入
			ocrStatus: 'idle',
			ocrMessage: '',
			ocrCandidates: null,
			ocrDeleted: {},
			// renderjs 解码桥：decodeTask 变化即触发视图层解码（R1）
			decodeTask: null,
			decodeTimings: null,
			healthOk: false,
			localId: '',
			// 批量连续扫码（plus.barcode）：非空表示原生扫码视图正在跑
			batchScanner: null,
			// 面板是否展开：留位卡片与原生控件的位置都来自它
			batchPanelOpen: false,
			// 状态机当前状态（由 utils/batchBarcodeScanner.js 回调写入，界面只做展示）
			batchScannerState: '',
			// 最近一次初始化 / 运行失败的说明；非空时卡片里显示并允许「重新启动扫码」
			batchScanError: '',
			// 扫码器运行统计（识别 / 重启 / 瞬时重复），用于现场判断「摄像头还在不在跑」
			batchScanStats: null,
			// 扫码提示音开关（关掉后只留震动）：默认开，设置落盘，下次进来沿用
			scanSoundOn: true,
			// 会话去重用的 key（箱-罐-相位）。换罐时会清掉 Set。
			sessionScanKey: ''
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
				virtual: !!box.virtual,
				cans: (box.cans || []).map((can, cIndex) => ({
					canIndex: cIndex + 1,
					canCode: can.canCode,
					slots: (can.particles || []).map((code, sIndex) => ({ index: sIndex, code }))
				}))
			}))
		},
		/**
		 * 漏扫高亮提示（需求 7）：只在粒子相位、且没扫满时出现。
		 * 文案里同时给「已扫 / 还差」两个数，操作员不用自己算。
		 */
		underFilledHint() {
			if (!this.batch) return ''
			if (this.wizard.phase !== PHASE.PARTICLE) return ''
			const missing = this.currentCanPlanned - this.currentCanScanned
			if (missing <= 0) return ''
			return `⚠️ 可能漏扫：当前已扫 ${this.currentCanScanned} 个，还差 ${missing} 个未扫描`
			},
			/** 扫码器状态的中文标签（状态机原值在 batchScannerState 里）。 */
			/** 当前罐是否已满（满了相位会推进到"本罐核对"，但手动补录的提示要能说清原因）。 */
			currentCanIsFull() {
				return this.currentCanPlanned > 0 && this.currentCanScanned >= this.currentCanPlanned
			},
			batchScannerStateLabel() {
				const labels = {
					idle: '未启动',
					starting: '启动中',
					scanning: '扫描中',
					processing: '处理中',
					stopping: '正在停止',
					error: '异常'
				}
				return labels[this.batchScannerState] || '待启动'
			},
			/** 状态徽标的颜色：扫描中=绿、处理中=蓝、异常=橙、其余=灰。 */
			batchScanBadgeClass() {
				if (this.batchScannerState === 'scanning') return 'badge-ok'
				if (this.batchScannerState === 'processing') return 'badge-info'
				if (this.batchScannerState === 'error') return 'badge-warn'
				return 'badge-neutral'
			},
			/** 取景区里的提示文字：失败时显示原因，正常时显示占位说明。 */
			/** 照片/图库浮层标题与提示：箱号 / 罐号 / 粒子（图库辅助）三种用途。 */
			/** OCR 状态标签与徽标（无插件时明确显示"手动录入"）。 */
			ocrStatusLabel() {
				const labels = {
					idle: '待识别',
					decoding: '识别中',
					running: '识别中',
					success: '识别完成',
					done: '识别完成',
					partial: '部分识别',
					empty: '未识别到码',
					timeout: '识别超时',
					failed: '识别失败',
					unavailable: '无 OCR 插件'
				}
				return labels[this.ocrStatus] || '待识别'
			},
			ocrBadgeClass() {
				if (this.ocrStatus === 'done' || this.ocrStatus === 'success') return 'badge-ok'
				if (this.ocrStatus === 'running' || this.ocrStatus === 'decoding') return 'badge-info'
				if (this.ocrStatus === 'partial' || this.ocrStatus === 'empty' || this.ocrStatus === 'timeout') {
					return 'badge-warn'
				}
				if (this.ocrStatus === 'unavailable') return 'badge-warn'
				if (this.ocrStatus === 'failed') return 'badge-error'
				return 'badge-neutral'
			},
			/** 候选列表（有效 / 本次重复 / 批次内已存在 / 无效 四类一起列出来）。 */
			ocrListRows() {
				// 必须把 ocrDeleted 一起传进去：视图层要随删除实时变灰（纯函数见 services/particleInput.js）
				return buildOcrCandidateRows(this.ocrCandidates, this.ocrDeleted)
			},
			/** 当前可填入的有效码（排除操作员手动删掉的）。 */
			ocrFillableCodes() {
				return selectFillableOcrCodes(this.ocrListRows)
			},
			/** 已手动删除的条数（状态行提示用）。 */
			deletedOcrCount() {
				return this.ocrListRows.filter((row) => row.deleted).length
			},
			photoTitle() {
				if (!this.photo) return ''
				if (this.photo.kind === 'box') return '拍照识别箱号'
				if (this.photo.kind === 'can') return '拍照识别罐号'
				return '图库辅助录入粒子码'
			},
			photoHint() {
				if (!this.photo) return ''
				if (this.photo.kind === 'particle') {
					return '本机不做自动识别：请放大图片看清每枚标签上的序列号，在下面输入框里批量录入（13 位序列号会自动补前缀，重复码与错误前缀会被挡下）。'
				}
				return '本机暂无自动识别能力 / 识别不确定，请人工读数并输入：照着照片把数字看清楚，再点下面的按钮进输入框键入（识别只负责「看见什么数字」，上限与查重由业务层判断）。'
			},
			batchScanSlotHint() {
				if (this.batchScanError) return this.batchScanError
				if (this.batchScannerState === 'processing') return '已识别到一枚，正在写入…'
				return '原生扫码取景区（plus.barcode）：对准条码即可，无需反复点按钮'
			},
			/**
			 * 扫码器统计（现场判断摄像头是否还在跑、重复码有多少）：
			 * 五维口径：识别 / 自动重启 / 同码瞬时忽略 / 业务重复 / 异常，
			 * 有非法字符或其它拒绝时再补两项，另外带平均每枚间隔。
			 * 这批数字就是压测口径：识别→重启应始终 1:1，异常必须为 0。
			 */
			batchScanStatsText() {
				const stats = this.batchScanStats
				if (!stats) return ''
				const reasons = stats.rejectReasons || {}
				const parts = [
					`识别 ${stats.markedCount} 枚`,
					`自动重启 ${stats.restartCount} 次`,
					`同码瞬时忽略 ${reasons.instantIgnore || 0} 次`,
					`业务重复 ${reasons.businessDuplicate || 0} 次`,
					`异常 ${stats.errorCount} 次`
				]
				if (reasons.invalidChar) parts.push(`非法字符 ${reasons.invalidChar} 次`)
				const codes = stats.rejectReasonCodes || {}
				if (codes.WRONG_LAYER) parts.push(`扫错层 ${codes.WRONG_LAYER} 次`)
				if (reasons.unknown) parts.push(`其它拒绝 ${reasons.unknown} 次`)
				const timing = stats.timing
				if (timing && timing.avgMs) parts.push(`平均 ${(timing.avgMs / 1000).toFixed(1)} 秒/枚`)
				return parts.join(' · ')
		}
	},

	/**
	 * 会话去重集合只挂在实例上（不进 data）：
	 * Vue 不需要为 Set 建响应式，几万个码的查找仍是 O(1)。
	 */
	created() {
		this.sessionScanned = new Set()
		// 非响应式实例字段：解码任务序号与 renderjs 回调的 pending（不需要 Vue 建响应式）
		this.decodeSeq = 0
		this.decodePending = null
		// 提示音开关沿用上次的选择（现场普遍嫌每枚都响；关掉后还有震动反馈）
		try {
			const saved = uni.getStorageSync(STORAGE_SCAN_SOUND)
			if (saved === false || saved === 'false') this.scanSoundOn = false
		} catch (error) {
			// 读不到就用默认值（开）
		}
	},

	onShow() {
		ensureDefaults()
		this.reload()
	},

	// 离开页面 / 切到其它 Tab：必须把原生扫码视图收掉，否则摄像头一直被占着
	onHide() {
		this.stopBatchScan(true)
	},

	onUnload() {
		this.stopBatchScan(true)
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
			// 换箱 / 换罐 / 换相位就把「会话内去重」清掉 ——
			// 否则跨罐的真码会被当成「刚扫过的重复」静默忽略掉。
			const key = `${this.wizard.boxIndex}-${this.wizard.canIndex}-${this.wizard.phase}`
			if (this.sessionScanKey !== key) {
				this.sessionScanKey = key
				if (this.sessionScanned) this.sessionScanned.clear()
			}
			// 相位一旦离开粒子采集，原生扫码视图必须收掉（否则摄像头一直占着）
			if (this.wizard.phase !== PHASE.PARTICLE) this.stopBatchScan(true)
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
		 * 批量连续扫码（需求 5）：在当前 webview 里挂一个 plus.barcode 原生扫码视图。
		 *
		 * 为什么不用 uni.scanCode：它是「一次调一个码」的系统扫码界面，扫几十个竖向条码
		 * 要反复开合，效率不可接受。plus.barcode.create() 是常驻视图，onmarked 每识别到一个
		 * 就回调一次，可以连续扫。
		 *
		 * 资源释放：退出方式有四条 —— 点「完成扫码」、切 Tab（onHide）、离开页面（onUnload）、
		 * 相位离开粒子采集（reload 里判断）。四条都会走 stopBatchScan()。
		 */
		async startBatchScan() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.PARTICLE) return
			// #ifndef APP-PLUS
			this.event = eventOf('ERROR', '批量连续扫码只在 App 端可用（H5 没有 plus.barcode），请用「单次扫码一个」。', false)
			return
			// #endif
			// #ifdef APP-PLUS
			// 先展开面板：留位卡片要先出现在页面上，才有矩形可以量给原生控件
			this.batchPanelOpen = true
			this.batchScanError = ''
			await this.launchBatchScanner()
			// #endif
		},

		/**
		 * 真正拉起原生控件：量留位卡片 → 交给模块 start()。
		 * 启动链的每一步（权限 → 释放残留 → create → 绑事件 → append → start）都在
		 * utils/batchBarcodeScanner.js 里，页面不再直接碰 plus.barcode。
		 */
		async launchBatchScanner() {
			if (!this.batchScanner) this.batchScanner = this.createBatchScanner()
			const styles = await this.measureBatchSlot()
			const result = await this.batchScanner.start({ styles })
			if (!result.ok) {
				this.batchScanError = this.describeScannerError(result.reason)
				this.event = eventOf('ERROR', `${this.batchScanError}。可点「🔄 重新启动扫码」重试。`, false)
				return
			}
			this.batchScanError = ''
			if (this.sessionScanned) this.sessionScanned.clear()
			this.event = eventOf('PHOTO', '连续扫码已开始：对准条码逐个扫入，重复的会自动忽略；扫完点「✅ 完成扫码」。', false)
		},

		/**
		 * 扫码提示音开关（现场要求「提示音要能取消」）：
		 * 关掉后 plus.barcode 不再「嘀」，震动反馈保留；设置落盘，下次进来沿用；
		 * 因为 sound 是 start 参数，下一轮识别（几十毫秒后）就生效。
		 */
		toggleScanSound() {
			this.scanSoundOn = !this.scanSoundOn
			try {
				uni.setStorageSync(STORAGE_SCAN_SOUND, this.scanSoundOn)
			} catch (error) {
				console.warn('[BatchScan] 提示音设置落盘失败', error)
			}
			uni.showToast({
				title: this.scanSoundOn ? '扫码提示音已开启' : '扫码提示音已关闭（只留震动）',
				icon: 'none'
			})
		},

		/** 取景卡住 / 异常后的手动重启：先 stop（cancel + close）再重新 create + start。 */
		async restartBatchScan() {
			if (!this.batchPanelOpen) {
				await this.startBatchScan()
				return
			}
			if (!this.batchScanner) this.batchScanner = this.createBatchScanner()
			this.batchScanError = ''
			const styles = await this.measureBatchSlot()
			const result = await this.batchScanner.restart({ styles })
			if (result.ok) {
				this.event = eventOf('PHOTO', '扫码已重新启动，继续对准条码即可。', false)
				return
			}
			this.batchScanError = this.describeScannerError(result.reason)
			this.event = eventOf('ERROR', `${this.batchScanError}。`, false)
		},

		/** 构造扫码器：页面只注入「权限 / Webview / 业务处理 / 状态回调」四件事。 */
		createBatchScanner() {
			return createBatchBarcodeScanner({
				pageVm: this,
				getWebview: () => getCurrentAppWebview(this),
				// 复用单码扫码那套相机权限申请与「去系统设置」引导
				ensurePermission: () => this.ensureCamera(),
				// 提示音开关：每轮 start 都会重新取一次，关掉后只留震动
				getFeedback: () => ({ vibrate: true, sound: this.scanSoundOn ? 'default' : 'none' }),
				onCode: (code, type) => this.onBatchCode(code, type),
				onError: (error, stage) => this.handleBatchScanError(error, stage),
				onStateChange: (state) => {
					this.batchScannerState = state
					// 统计随状态刷新：每识别一枚都会走 processing → scanning，这里能拿到最新计数
					this.batchScanStats = this.batchScanner ? this.batchScanner.getStats() : null
				},
				// 收工（含「重新启动扫码」）时把本轮统计落盘：
				// HBuilderX 基座的 console 在电脑上读不到，真机压测的逐枚耗时只能这么带出来。
				onRunSummary: (summary, reason) => {
					try {
						uni.setStorageSync('pharmrelate.batchscan.lastRun', {
							at: new Date().toISOString(),
							reason,
							summary
						})
					} catch (error) {
						console.warn('[BatchScan] 统计落盘失败', error)
					}
				}
			})
		},

		/**
		 * 量出留位卡片的真实矩形，换算成原生控件的 styles。
		 *
		 * position 用 'static' 是有意的：页面滚动时原生控件跟着内容走，才不会和留位卡片错位；
		 * top 取「视口内偏移 + 滚动量」，所以先滚到顶再量，量到的就是内容坐标系里的位置。
		 */
		async measureBatchSlot() {
			uni.pageScrollTo({ scrollTop: 0, duration: 0 })
			await this.$nextTick()
			await new Promise((resolve) => setTimeout(resolve, 80))
			const rect = await new Promise((resolve) => {
				uni.createSelectorQuery()
					.in(this)
					.select('#batch-scan-slot')
					.boundingClientRect((data) => resolve(data || null))
					.exec()
			})
			if (!rect || !rect.width || !rect.height) return null
			const scroll = await new Promise((resolve) => {
				uni.createSelectorQuery()
					.in(this)
					.selectViewport()
					.scrollOffset((data) => resolve(data || { scrollTop: 0 }))
					.exec()
			})
			const top = Math.round((rect.top || 0) + ((scroll && scroll.scrollTop) || 0))
			return {
				top: `${top}px`,
				left: `${Math.round(rect.left || 0)}px`,
				width: `${Math.round(rect.width)}px`,
				height: `${Math.round(rect.height)}px`,
				position: 'static',
				background: '#101a22',
				frameColor: '#2563EB',
				scanbarColor: '#2563EB'
			}
		},

		/** 把模块的英文错误码翻译成操作员照着就能做的一句话。 */
		describeScannerError(reason) {
			const messages = {
				CAMERA_PERMISSION_DENIED: '相机权限被拒绝：请在系统设置 → 应用 → 权限里允许「相机」',
				PLUS_UNAVAILABLE: '当前不是 App 运行环境，取不到 plus（H5 请用「单次扫码一个」）',
				PLUS_BARCODE_UNAVAILABLE: '当前基座没有 Barcode 模块，请用 HBuilderX 重新打包基座',
				APP_WEBVIEW_UNAVAILABLE: '取不到当前页面 Webview，无法挂载原生扫码控件',
				BARCODE_CREATE_RETURNED_NULL: '原生扫码控件创建失败（plus.barcode.create 返回空）'
			}
			return messages[reason] || `扫码器启动失败：${reason || '未知原因'}`
		},

		/** 模块报错（初始化 / onerror / 业务处理）统一落到界面与日志。 */
		handleBatchScanError(error, stage) {
			const message = (error && (error.message || error.errMsg)) || String(error || '')
			console.error('[BatchScan] ERROR', stage, message)
			if (stage === 'onmarked') {
				// 业务处理失败：摄像头不停，只提示
				uni.showToast({ title: '扫码结果处理失败，请再扫一次', icon: 'none' })
				return
			}
			this.batchScanError = this.describeScannerError(message)
			uni.showToast({ title: '扫码器异常，可点「重新启动扫码」', icon: 'none' })
		},

		/** 收掉原生扫码控件并释放摄像头。silent=true 时不弹 Toast（切页/切 Tab 用）。 */
		async stopBatchScan(silent) {
			if (this.batchScanner) await this.batchScanner.stop('stop')
			this.batchScanError = ''
			this.batchScannerState = ''
			this.batchScanStats = null
			if (this.batchPanelOpen) {
				this.batchPanelOpen = false
				if (!silent) uni.showToast({ title: '已结束连续扫码', icon: 'none' })
			}
		},

		/**
		 * 连续扫码每收到一个码就走这里（业务层的第 2、3 层去重；第 1 层「瞬时防抖」
		 * 在 utils/batchBarcodeScanner.js 里，所以这里不会再看到同一枚码连刷）。
		 *
		 *   1. 含非数字字符 → 报警拒绝（绝不做 \D 全剔，避免把错码洗成合法码）；
		 *   2. 本罐 / 本次会话内已扫过 → 震动 + Toast，静默忽略、不写库（真重复）；
		 *   3. 跨罐 / 跨箱已存在 → 交给 applyCodes 报警 + 弹窗核对（可能扫错了别的罐）。
		 *
		 * 返回值只给模块做统计用；**无论返回什么，模块都会继续下一次 start**，
		 * 所以业务校验失败不会停摄像头。
		 */
		onBatchCode(raw, type) {
			if (!this.batch) return { accepted: false, reason: 'NO_BATCH' }
			if (this.wizard.phase !== PHASE.PARTICLE) return { accepted: false, reason: 'NOT_PARTICLE_PHASE' }
			const extract = extractDigits(raw, 1)
			if (extract.illegal) {
				this.alarm(
					eventOf(
						'ILLEGAL_CHAR',
						`条码 ${raw} 含非数字字符「${extract.illegal}」，已忽略。请核对标签后重扫（不会自动把字母换成数字）。`,
						true
					)
				)
				return { accepted: false, reason: 'INVALID_FORMAT' }
			}
			const code = extract.code
			if (this.sessionScanned && this.sessionScanned.has(code)) {
				// 这一层是「本罐本次已扫过」的正常重复（压测里占大头）：
				// 只给轻提示，不用长震动 —— 现场一次连扫几十枚，长震动会把人震麻。
				uni.vibrateShort({ type: 'light' })
				uni.showToast({ title: '本次已扫过，重复码忽略', icon: 'none' })
				return { accepted: false, reason: 'CURRENT_BATCH_DUPLICATE' }
			}
			const result = applyCodes(this.batch, [code])
			const eventCode = result.event && result.event.code
			if (eventCode === EVENT.OK) {
				if (this.sessionScanned) this.sessionScanned.add(code)
			} else if (eventCode === EVENT.DUPLICATE_CODE) {
				// 跨罐 / 跨箱：不能静默，弹窗要求核对（连续扫码时保持扫码视图不关，核对完继续扫）
				uni.showModal({
					title: '条码已存在',
					content: `${code} 已被使用过，可能扫到了别的罐的标签。请核对后再继续。`,
					showCancel: false,
					confirmText: '知道了'
				})
			}
			this.handle(result)
			return { accepted: eventCode === EVENT.OK, reason: eventCode || 'UNKNOWN' }
		},

		/**
		 * 本罐先结束（需求 7 的二次确认入口）。
		 * 为什么需要它：deriveWizard() 只有在「已扫满」之后才会推出 CAN_REVIEW 相位，
		 * 所以「没扫满就想收尾」在原来根本走不到「本罐确认无误」那个按钮上。
		 */
		endCanEarly() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.PARTICLE) return
			const missing = this.currentCanPlanned - this.currentCanScanned
			if (missing <= 0) {
				this.event = eventOf(EVENT.OK, '本罐已经扫满，请回到「本罐确认无误」。', false)
				return
			}
			uni.showModal({
				title: '本罐未填满',
				content: `当前罐未填满（已扫 ${this.currentCanScanned} / 计划 ${this.currentCanPlanned}），确定要强制结束本罐采集吗？缺漏会在整体核对里如实显示。`,
				confirmText: '强制结束',
				cancelText: '继续扫',
				success: (res) => {
					if (!res.confirm) return
					this.stopBatchScan(true)
					this.handle(forceEndCan(this.batch))
				}
			})
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
			// 严格提取：只清已知分隔符。残留非数字字符 → 报警拒绝，绝不 \D 全剔
			const extract = extractDigits(rawCode, expected)
			if (extract.illegal) {
				this.alarm(
					eventOf(
						'ILLEGAL_CHAR',
						`${label} ${rawCode} 里含非数字字符「${extract.illegal}」，已拒绝。请核对标签后重扫（不会自动把字母换成数字）。`,
						true
					)
				)
				return
			}
			const code = extract.code
			const issue = describeCodeIssue(code, expected)
			if (issue) {
				uni.showModal({ title: `${label}格式不对`, content: issue, showCancel: false })
				return
			}
			const prefix = CODE_PREFIXES[expected]
			uni.showModal({
				title:
					kind === 'box'
						? `这是箱号吗？(${prefix}...)`
						: `这是箱 ${wizard.boxIndex} 罐 ${wizard.canIndex} 号吗？(${prefix}...)`,
				content: kind === 'box' ? `第 ${wizard.boxIndex} 箱 / 共 ${wizard.totalBoxes} 箱\n${code}` : code,
				confirmText: '正确',
				cancelText: '不正确',
				success: (res) => {
					if (!res.confirm) {
						this.event = eventOf('RETRY', `已放弃 ${code}，请重新扫描${label}。`, false)
						this.manualValue = ''
						// 需求 2/4：点「不正确」直接重新调起摄像头，不用再点一次按钮。
						// 延后一拍：弹窗还在收起时开相机会被吞掉（与 chainModal 同一个坑）。
						setTimeout(() => {
							if (kind === 'box') this.scanBox()
							else this.scanCan()
						}, 320)
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
			// 防御性检查（需求 7）：正常流程里能进 CAN_REVIEW 就说明已扫满，
			// 这条分支是给「以后新增了别的收尾路径」兜底的，不指望它天天触发。
			const missing = this.currentCanPlanned - this.currentCanScanned
			if (missing > 0) {
				uni.showModal({
					title: '本罐未填满',
					content: `当前罐未填满（已扫 ${this.currentCanScanned} / 计划 ${this.currentCanPlanned}），确定要强制结束本罐采集吗？缺漏会在整体核对里如实显示。`,
					confirmText: '强制结束',
					cancelText: '继续扫',
					success: (res) => {
						if (!res.confirm) return
						this.handle(confirmCanReview(this.batch, true))
						this.afterCanConfirmed()
					}
				})
				return
			}
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
				// 阶段 C：拍照识别不再只认相机 —— 现场常常是"别人微信发来的标签照片"，
				// 所以要能直接从图库选图（选图后仍是人工读数，本机不做自动识别）。
				sourceType: ['camera', 'album'],
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
			if (this.batchSubmitting) return
			const raw = (this.pasteCode || '').trim()
			if (!raw) {
				uni.showToast({ title: '输入不能为空，请粘贴或输入粒子码', icon: 'none' })
				return
			}
			const codes = raw.split(/[\s,;]+/).filter(Boolean)
			if (this.wizard.phase === PHASE.BOX || this.wizard.phase === PHASE.CAN) {
				if (codes.length > 1) {
					this.alarm(
						eventOf(EVENT.MULTI_CODE, `一次识别到 ${codes.length} 个号码；拍箱号/罐号时只能有一个，请重拍或分开提交。`, true)
					)
					return
				}
				this.pasteCode = ''
				this.considerSingle(codes[0], this.wizard.phase === PHASE.BOX ? 'box' : 'can')
				return
			}
			// 罐已满时相位会推进到「本罐核对」，但操作员仍可能往里粘贴 —— 交给数据层
			// 给出「当前罐已满」这个具体原因，而不是笼统的"当前步骤不接受输入"。
			if (this.wizard.phase !== PHASE.PARTICLE && !this.currentCanIsFull) {
				this.event = eventOf(EVENT.WRONG_STATE, `当前步骤是「${this.wizard.prompt}」，不接受手动输入。`, false)
				return
			}
			this.submitBatchParticleText(raw)
		},

		/**
		 * 批量粒子码录入（阶段 B）：手动粘贴与"图库辅助人工读数"共用这一条路径。
		 *
		 * 口径（2026-10-02 拍板）：
		 *   - 13 位序列号自动补前缀 8206233；20 位码原样；错前缀/错长度/含字母一律判无效；
		 *   - 输入内重复、本罐/跨罐已存在的重复都挡下；
		 *   - **超出计划不再整帧拒绝**：能填的先填，多出来的明确列出来（不静默丢弃）；
		 *   - 汇总一次提示，绝不连弹几十个 Toast。
		 */
		submitBatchParticleText(raw) {
			const parsed = parseParticleBatch(raw)
			if (!parsed.total) return null
			if (!parsed.valid.length) {
				const first = parsed.invalid[0]
				uni.showToast({
					title: first ? first.message : '没有解析到可用的粒子码',
					icon: 'none'
				})
				this.event = eventOf(
					'ILLEGAL_CHAR',
					`${summarizeBatchParse(parsed)}；没有任何有效粒子码写入。`,
					false
				)
				return null
			}
			const outcome = this.writeParticleCodes(
				parsed.valid.map((item) => item.code),
				`本次解析 ${parsed.total} 条：有效 ${parsed.valid.length} 条`
			)
			return outcome ? { parsed, info: outcome.info } : null
		},

		/**
		 * 批量写入的**唯一出口**：手动粘贴与 OCR 确认都走这里。
		 * 成功返回 { info }；失败返回 null（已 Toast 提示，弹窗/浮层保持不动）。
		 */
		writeParticleCodes(codes, headline) {
			this.batchSubmitting = true
			const result = fillParticleCodesIntoEmptySlots(this.batch, codes)
			this.batchSubmitting = false
			const info = result.result || {}
			this.handle(result)
			if (!(result.event && result.event.code === EVENT.OK)) {
				uni.showToast({ title: (result.event && result.event.message) || '未写入，请检查后重试', icon: 'none' })
				return null
			}
			const segments = [headline]
			if (info.duplicates && info.duplicates.length) segments.push(`重复 ${info.duplicates.length} 条`)
			if (info.invalid && info.invalid.length) segments.push(`无效 ${info.invalid.length} 条`)
			if (info.overflow && info.overflow.length) segments.push(`超出计划 ${info.overflow.length} 条未写入`)
			const lines = [segments.join('，')]
			if (info.overflow && info.overflow.length) {
				// 未写入的码留在输入框里，操作员能复制到别处 / 补到下一罐
				this.pasteCode = info.overflow.map((code) => code).join('\n')
				lines.push(`未写入：${info.overflow.join('、')}`)
			} else {
				this.pasteCode = ''
			}
			this.event = eventOf(EVENT.OK, lines.join('\n'), false)
			uni.showToast({ title: segments.join('，'), icon: 'none' })
			return { info }
		},

		/** renderjs 视图层解码完成的回调（R1：结果从视图层回传）。 */
		onDecodeResult(payload) {
			const pending = this.decodePending
			if (!pending || !payload || payload.taskId !== pending.taskId) return
			this.decodePending = null
			this.decodeTimings = Object.assign({}, pending.timings || {}, payload.timings || {})
			this.decodeDebug = payload.debug || null
			pending.resolve(payload)
		},

		/** 等 renderjs 的回调，带硬超时（超时也必须给页面一个结果）。 */
		waitDecodeResult(taskId, timeoutMs) {
			return new Promise((resolve) => {
				const timer = setTimeout(() => {
					if (this.decodePending && this.decodePending.taskId === taskId) {
						this.decodePending = null
						resolve({ taskId, ok: false, timeout: true, message: '识别超时', codes: [], timings: {} })
					}
				}, timeoutMs)
				this.decodePending = {
					taskId,
					timings: {},
					resolve: (payload) => {
						clearTimeout(timer)
						resolve(payload)
					}
				}
			})
		},

		/**
		 * 图库选图后的自动识别（R1/R3/R7）：
		 *   ① 条码解码（renderjs 视图层，免插件，条码自带校验位最准）
		 *   ② 不够目标数量才补 ML Kit OCR（只有自定义基座才有插件）
		 *   ③ 都不行 → 如实说明 + 手动录入（永远可用，12s 内必给结果）
		 *
		 * 目标数量 expectedCount = 当前罐剩余空槽位（为空/已满则直接跳过自动识别）。
		 */
		async runOcrAssist(path) {
			this.ocrCandidates = null
			this.ocrDeleted = {}
			this.decodeTimings = null
			const isStale = () => !this.photo || this.photo.path !== path
			const started = Date.now()

			// R3：当前罐还剩几个空槽位（业务预期数量），满了就没必要识别
			const expectedCount = Math.max(0, this.currentCanPlanned - this.currentCanScanned)
			if (!expectedCount) {
				this.ocrStatus = 'unavailable'
				this.ocrMessage = '当前罐已满，无需自动识别；要补录请先删除槽位或进入下一罐。'
				return
			}
			if (!IMAGE_CODE_DECODER_ENABLED) {
				this.ocrStatus = 'unavailable'
				this.ocrMessage = '本机自动识别暂未启用，请放大图片后手动录入。'
				return
			}

			this.ocrStatus = 'decoding'
			this.ocrMessage = `正在本机识别…（目标 ${expectedCount} 个粒子码）`
			const softTimer = setTimeout(() => {
				if (this.ocrStatus === 'decoding') this.ocrMessage = `仍在识别中…（已等 ${Math.round(DECODER_SOFT_TIMEOUT_MS / 1000)}s，可继续等待或直接手输）`
			}, DECODER_SOFT_TIMEOUT_MS)

			try {
				// 图片与 wasm 都读成 data URL（wasm 走单例缓存，只读一次）
				const readStart = Date.now()
				const [imageBase64, wasmBase64] = await Promise.all([
					readImageAsDataUrl(path),
					readWasmAsDataUrl()
				])
				const loadImageMs = Date.now() - readStart
				if (isStale()) return

				const taskId = `d${++this.decodeSeq}`
				const result = await (async () => {
					const pending = this.waitDecodeResult(taskId, DECODER_TIMEOUT_MS)
					// 触发 renderjs（:change:prop）：带上 wasm 与图片，视图层收到就开始解码
					this.decodeTask = { taskId, imageBase64, wasmBase64, maxSide: DECODER_MAX_SIDE, expectedCount }
					return pending
				})()
				if (isStale()) return

				const timings = Object.assign({ loadImageMs }, this.decodeTimings || {}, {
					totalMs: Date.now() - started
				})
				timings.debug = this.decodeDebug || null
				const barcodeCodes = (result && result.codes) || []
				const parsedBarcode = barcodeCodes.length
					? parseOcrParticleCandidates(barcodeResultsToBlocks(barcodeCodes), {
							isUsed: (code) => findUsage(this.batch, code, 1)
						})
					: null
				let candidates = parsedBarcode
				const parseStart = Date.now()
				let ocrUsed = false

				// ② 条码不够目标数量 → 补 ML Kit OCR（没有插件就跳过，不算失败）
				if (!result.ok || !candidates || candidates.valid.length < expectedCount) {
					const ocr = await recognizeImage(path)
					if (isStale()) return
					if (ocr.success && ocr.blocks && ocr.blocks.length) {
						ocrUsed = true
						const parsedOcr = parseOcrParticleCandidates(ocr.blocks, {
							isUsed: (code) => findUsage(this.batch, code, 1)
						})
						candidates = this.mergeCandidates(candidates, parsedOcr)
						timings.ocrBlocks = ocr.blocks.length
					} else if (ocr.code !== 'OCR_PLUGIN_MISSING') {
						timings.ocrError = ocr.message
					}
				}
				timings.parseMs = Date.now() - parseStart
				timings.totalMs = Date.now() - started
				timings.expectedCount = expectedCount
				timings.validCount = candidates ? candidates.valid.length : 0
				timings.ocrUsed = ocrUsed
				this.persistDecodeTimings(timings)

				if (candidates && (candidates.valid.length || candidates.duplicateInCurrentBatch.length)) {
					this.ocrCandidates = candidates
					const enough = candidates.valid.length >= expectedCount
					this.ocrStatus = enough ? 'success' : 'partial'
					const parts = [
						`条码识别 ${barcodeCodes.length} 枚`,
						ocrUsed ? `OCR 补充 ${timings.ocrBlocks || 0} 块` : '',
						`有效 ${candidates.valid.length}/${expectedCount}`,
						`${timings.totalMs}ms`
					].filter(Boolean)
					this.ocrMessage = enough
						? `${parts.join(' · ')}，已足够，请核对后确认。`
						: `${parts.join(' · ')}，不足目标数量，可确认现有结果后手动补录。`
					return
				}

				// ③ 没有任何候选 → 如实说明原因，手动录入照常
				const reason = result.ok
					? `本机条码解码没找到可用粒子码（${timings.barcodeDecodeMs || 0}ms）`
					: result.timeout
						? '自动识别超时'
						: `解码失败：${result.message || '未知原因'}`
				this.ocrStatus = result.timeout ? 'timeout' : 'unavailable'
				this.ocrMessage = `${reason}（共 ${timings.totalMs}ms）。请核对图片或改为手动录入。`
			} catch (error) {
				if (isStale()) return
				this.ocrStatus = 'unavailable'
				this.ocrMessage = `自动识别未完成：${(error && error.message) || error}。请改为手动录入。`
			} finally {
				clearTimeout(softTimer)
			}
		},

		/** 条码候选 + OCR 候选合并（同一枚码只留一条，T8）。 */
		mergeCandidates(first, second) {
			if (!first) return second
			if (!second) return first
			const seen = {}
			const valid = []
			first.valid.concat(second.valid).forEach((item) => {
				if (seen[item.code]) return
				seen[item.code] = true
				valid.push(item)
			})
			const dedupe = (list) => {
				const out = []
				list.forEach((item) => {
					if (item.code && seen[item.code]) return
					if (item.code) seen[item.code] = true
					out.push(item)
				})
				return out
			}
			return {
				valid,
				duplicateInInput: first.duplicateInInput.concat(second.duplicateInInput),
				duplicateInCurrentBatch: dedupe(
					first.duplicateInCurrentBatch.concat(second.duplicateInCurrentBatch)
				),
				invalid: first.invalid.concat(second.invalid),
				rawText: `${first.rawText}\n${second.rawText}`,
				blockCount: (first.blockCount || 0) + (second.blockCount || 0),
				mergedCount: (first.mergedCount || 0) + (second.mergedCount || 0)
			}
		},

		/** 分段耗时落盘（与"逐枚耗时"同一套路：基座 console 读不到，只能落盘再取）。 */
		persistDecodeTimings(timings) {
			try {
				uni.setStorageSync('pharmrelate.batchscan.lastDecode', {
					at: new Date().toISOString(),
					timings
				})
			} catch (error) {
				console.warn('[BatchScan] 识别耗时落盘失败', error)
			}
		},

		rerunOcr() {
			if (!this.photo) return
			if (this.ocrStatus === 'running') return
			this.runOcrAssist(this.photo.path)
		},

		removeOcrCandidate(row) {
			if (!row || !row.key) return
			// 幂等：已删除的行再点一次不做任何事（按钮本身也会被 disabled）
			if (this.ocrDeleted[row.key]) return
			// 不可变替换：整对象换新引用，computed 才会重算（视图随删除实时更新）
			this.ocrDeleted = Object.assign({}, this.ocrDeleted, { [row.key]: true })
		},

		clearOcrCandidates(message) {
			this.ocrCandidates = null
			this.ocrDeleted = {}
			this.ocrStatus = 'idle'
			this.ocrMessage = typeof message === 'string' ? message : '已清空识别结果。'
		},

		/** 确认有效码 → 走唯一的批量写入出口（严禁 OCR 直接写槽位）。 */
		submitOcrCandidates() {
			// 双保险：入口再按 deleted 过滤一次（数据源与视图同源，被删的码绝不写入）
			const codes = selectFillableOcrCodes(this.ocrListRows)
			if (!codes.length) {
				uni.showToast({ title: '没有可填入的有效码', icon: 'none' })
				return
			}
			const validTotal = (this.ocrCandidates && this.ocrCandidates.valid.length) || 0
			const outcome = this.writeParticleCodes(codes, `OCR 有效 ${validTotal} 条（本次确认 ${codes.length} 条）`)
			if (!outcome) return
			this.clearOcrCandidates(`已填入 ${outcome.info.written.length} 枚。`)
			if (!this.pasteCode) this.photo = null
		},

		/** 图库辅助浮层里的「解析并填入」：复用同一条批量录入路径，写干净了就收起图片。 */
		submitPasteFromPhoto() {
			const outcome = this.submitBatchParticleText((this.pasteCode || '').trim())
			if (!outcome) return
			// 没有遗留未写入的码 → 图片已经没用了，收起来（照片本来就只在内存里，用完即弃）
			if (!this.pasteCode) this.photo = null
		},

		/**
		 * 图库辅助录入（阶段 C）：从相机或相册取一张标签照片，放大看清数字后，
		 * 在浮层下方用同一个多行面板人工录入。**本机不做自动识别**（没有原生 OCR），
		 * 所以这里如实提示"照着照片读数"，不做无法兑现的承诺。
		 */
		openAlbumAssist() {
			if (!this.batch) return
			if (this.wizard.phase !== PHASE.PARTICLE) {
				this.event = eventOf(EVENT.WRONG_STATE, '图库辅助录入只在粒子环节可用。', false)
				return
			}
			uni.chooseImage({
				count: 1,
				sourceType: ['camera', 'album'],
				// 用原图而不是压缩图：真机实测压缩副本只有 1080x1440，同一张 9 码标签页
				// 只能解出 6 枚（原图 9 枚全解出）。解码准确性优先，空间由本机临时目录承担。
				sizeType: ['original'],
				success: (res) => {
					const paths = (res && res.tempFilePaths) || []
					if (!paths.length) {
						this.event = eventOf('ERROR', '没有拿到图片，请重选。', false)
						return
					}
					this.photo = { path: paths[0], kind: 'particle', rotate: 0, scale: 1, recognizing: false, result: null }
					this.event = eventOf('PHOTO', '图片已打开：放大看清数字后，在下面输入框里批量录入。', false)
					// 有 OCR 插件就自动识别（识别结果只做候选，必须操作员确认才写槽位）
					this.runOcrAssist(paths[0])
				},
				fail: (error) => {
					const message = (error && error.errMsg) || '选择图片失败'
					if (/cancel/i.test(message)) return
					this.event = eventOf('ERROR', `选择图片未成功：${message}`, false)
				}
			})
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
			this.slotSubmitting = false
		},

		/**
		 * 槽位「填入 / 替换」（阶段 A）：
		 *   1. 先用 particleInput 解析：13 位补前缀、20 位原样、其余判非法；
		 *   2. 空输入 / 非法 → **Toast 提示且弹窗保持打开**（旧实现无条件关窗，操作员以为没反应）；
		 *   3. 合法才写库：空槽走 fillSlot()，已填槽走 replaceSlot()，两者都带全批次去重；
		 *   4. 只有写入成功才关窗，并带防连点标志。
		 */
		doReplace() {
			if (!this.editing) return
			if (this.slotSubmitting) return
			const parsed = normalizeParticleCode(this.replaceValue)
			if (!parsed.ok) {
				// Toast 会自己消失，所以同时写进页面事件条（操作员回头还能看到原因）
				this.event = eventOf('ERROR', parsed.message, false)
				uni.showToast({ title: parsed.message, icon: 'none' })
				return
			}
			const { boxIndex, canIndex, slotIndex } = this.editing
			this.slotSubmitting = true
			const target = this.editing.code ? replaceSlot : fillSlot
			const result = target(this.batch, boxIndex, canIndex, slotIndex, parsed.code)
			this.slotSubmitting = false
			const ok = result.event && result.event.code === EVENT.OK
			this.handle(result)
			if (ok) {
				this.editing = null
				this.replaceValue = ''
				return
			}
			// 失败：弹窗保持打开，Toast 说清原因（重复 / 越界 / 状态不对）
			uni.showToast({ title: (result.event && result.event.message) || '未写入，请检查后重试', icon: 'none' })
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

<!--
	renderjs 视图层解码器（R1）

	为什么必须放视图层：真机实测 `readBarcodes()` 在服务层（JSCore）永不返回
	（12MP / 3.4MP / 800px 全卡 >35s，Node 同算法 97~171ms），因为服务层没有
	Blob / Image / canvas / createImageBitmap。视图层是完整浏览器环境，同一套代码可用。

	职责边界（与业务解耦）：
	   图片（data URL）→ createImageBitmap(按 EXIF 方向) → canvas 取像素 → zxing-wasm 解码
	   → 回传 [{text,left,top,right,bottom,source:'barcode'}] + 各阶段耗时
	   业务规则（前缀/13·20 位/去重/槽位）一律不在这里做，全部回到服务层 JS。

	wasm 不走网络也不 fetch file://：由服务层用 plus.io 读成 base64 传进来，
	以 `wasmBinary` 注入（模块作用域单例缓存，只注入一次）。
-->
<script module="imageDecoder" lang="renderjs">
import { readBarcodes, prepareZXingModule, setZXingModuleOverrides } from '../../services/zxing/reader.js'

/** wasm 二进制：只在第一次任务时注入（之后复用，不再重复初始化）。 */
let wasmBinaryCache = null
let wasmReady = null
let wasmInitMs = 0

/** data URL → ArrayBuffer（纯 JS，视图层有 atob，但保持与另一条路径一致的实现）。 */
function dataUrlToBytes(dataUrl) {
	const clean = String(dataUrl || '').replace(/^data:[^,]*,/, '').replace(/[^A-Za-z0-9+/=]/g, '')
	const binary = atob(clean)
	const bytes = new Uint8Array(binary.length)
	for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
	return bytes
}

/** 懒加载 + 单例：wasm 只注入/实例化一次。 */
function ensureWasm(base64) {
	if (base64 && !wasmBinaryCache) wasmBinaryCache = dataUrlToBytes(base64).buffer
	if (!wasmReady) {
		if (!wasmBinaryCache) return Promise.reject(new Error('wasm 尚未注入'))
		const started = Date.now()
		const overrides = { wasmBinary: wasmBinaryCache, locateFile: (file) => file }
		setZXingModuleOverrides(overrides)
		// 说明：打包后的 renderjs chunk 里 `prepareZXingModule` 的具名导入可能取不到
		// （实测返回 undefined → "Cannot read properties of undefined (reading 'then')"）。
		// 这里改为：只设置 overrides，让 zxing-wasm 在第一次 readBarcodes 时按需初始化 ——
		// 这也是它官方推荐的用法（overrides 在模块初始化时生效）。
		const prepared = typeof prepareZXingModule === 'function' ? prepareZXingModule({ overrides }) : null
		wasmReady = Promise.resolve(prepared).then(() => {
			wasmInitMs = Date.now() - started
			return true
		})
	}
	return wasmReady
}

/**
 * 图片 → ImageData。
 * createImageBitmap 的 `imageOrientation:'from-image'` 顺便把 EXIF 方向归一（R6）：
 * 竖拍照片（orientation 6/8）在像素层面就被转正，避免解码失败。
 * 目标尺寸按最长边限制（默认 2400），缩放在 canvas 绘制时完成，比在 JS 里手写采样快。
 */
async function imageToImageData(imageDataUrl, maxSide) {
	const response = await fetch(imageDataUrl)
	const blob = await response.blob()
	let bitmap = null
	let oriented = false
	try {
		bitmap = await createImageBitmap(blob, { imageOrientation: 'from-image' })
		oriented = true
	} catch (error) {
		bitmap = await new Promise((resolve, reject) => {
			const image = new Image()
			image.onload = () => resolve(image)
			image.onerror = () => reject(new Error('图片加载失败'))
			image.src = imageDataUrl
		})
	}
	const sourceWidth = bitmap.width || bitmap.naturalWidth || 0
	const sourceHeight = bitmap.height || bitmap.naturalHeight || 0
	if (!sourceWidth || !sourceHeight) throw new Error('拿不到图片尺寸')
	const scale = Math.min(1, (maxSide || 2400) / Math.max(sourceWidth, sourceHeight))
	const width = Math.max(1, Math.round(sourceWidth * scale))
	const height = Math.max(1, Math.round(sourceHeight * scale))
	const canvas = document.createElement('canvas')
	canvas.width = width
	canvas.height = height
	const context = canvas.getContext('2d')
	context.fillStyle = '#ffffff'
	context.fillRect(0, 0, width, height)
	context.drawImage(bitmap, 0, 0, width, height)
	const pixels = context.getImageData(0, 0, width, height)
	const result = { data: pixels.data, width, height, sourceWidth, sourceHeight, oriented, scale }
	// 视图层 canvas 显式释放，避免内存累积（R1 注意事项）
	canvas.width = 0
	canvas.height = 0
	if (bitmap && typeof bitmap.close === 'function') bitmap.close()
	return result
}

export default {
	methods: {
		/**
		 * 服务层通过 :change:prop 触发（每次任务带唯一 taskId，避免重复执行）。
		 * task = { taskId, imageBase64, wasmBase64, maxSide, formats, maxNumberOfSymbols, expectedCount }
		 */
		async onTaskChange(task) {
			if (!task || !task.taskId) return
			if (this.currentTaskId === task.taskId) return
			this.currentTaskId = task.taskId
			const timings = { wasmInitMs: 0, wasmReuse: !!wasmReady, imageDecodeMs: 0, barcodeDecodeMs: 0 }
			try {
				await ensureWasm(task.wasmBase64)
				timings.wasmInitMs = wasmInitMs
				timings.wasmReuse = !!task.wasmBase64 ? false : true
				const decodeStart = Date.now()
				const image = await imageToImageData(task.imageBase64, task.maxSide)
				timings.imageDecodeMs = Date.now() - decodeStart
				timings.imageWidth = image.width
				timings.imageHeight = image.height
				timings.oriented = image.oriented
				const barcodeStart = Date.now()

				const results = await readBarcodes(
					{ data: image.data, width: image.width, height: image.height },
					{
						formats: task.formats || ['Code128'],
						maxNumberOfSymbols: task.maxNumberOfSymbols || 64,
						tryHarder: true
					}
				)
				timings.barcodeDecodeMs = Date.now() - barcodeStart
				// 调试信息（真机排查用）：像素是否真的有内容、条码引擎回了什么
				const debug = {
					iw: image.width,
					ih: image.height,
					oriented: image.oriented,
					pixels: image.data ? image.data.length : 0,
					raw: (Array.isArray(results) ? results : []).length
				}
				if (image.data && image.data.length) {
					let sum = 0
					const step = Math.max(4, Math.floor(image.data.length / 4000 / 4) * 4)
					let samples = 0
					for (let index = 0; index < image.data.length; index += step) {
						sum += image.data[index]
						samples += 1
					}
					debug.meanR = Math.round(sum / Math.max(1, samples))
				}
				const codes = (Array.isArray(results) ? results : [])
					.filter((item) => item && typeof item.text === 'string' && item.text !== '')
					.map((item) => {
						const corners = item.position
							? [item.position.topLeft, item.position.topRight, item.position.bottomRight, item.position.bottomLeft]
							: []
						const xs = corners.map((point) => Number(point && point.x)).filter((value) => Number.isFinite(value))
						const ys = corners.map((point) => Number(point && point.y)).filter((value) => Number.isFinite(value))
						const box =
							xs.length && ys.length
								? {
										left: Math.round(Math.min.apply(null, xs) / image.scale),
										top: Math.round(Math.min.apply(null, ys) / image.scale),
										right: Math.round(Math.max.apply(null, xs) / image.scale),
										bottom: Math.round(Math.max.apply(null, ys) / image.scale)
									}
								: null
						return Object.assign({ text: item.text, source: 'barcode' }, box || {})
					})
				this.$ownerInstance.callMethod('onDecodeResult', {
					taskId: task.taskId,
					ok: true,
					codes,
					timings,
					debug
				})
			} catch (error) {
				this.$ownerInstance.callMethod('onDecodeResult', {
					taskId: task.taskId,
					ok: false,
					message: (error && error.message) || String(error),
					codes: [],
					timings
				})
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

/*
	批量连续扫码的留位卡片：原生控件按这块区域的实测矩形挂上去（utils/batchBarcodeScanner.js），
	所以它不会覆盖下面的按钮；扫描失败时这里显示失败原因，配合「🔄 重新启动扫码」重试。
*/
.batch-scan-card {
	padding-bottom: 16rpx;
}

.batch-scan-head {
	display: flex;
	align-items: center;
}

/*
	提示音开关：与右上角「扫描中」徽标**同款几何**（同高、同圆角、同字号、同内边距），
	只把颜色换成中性灰表示"可点"，这样一行里的两个小控件左右对齐、行高一致。
	注意两件事，少一件就会错位：
	  1. uni-app 的 <button> 自带 padding / line-height / margin auto，必须逐项覆盖；
	  2. 页面上另有 `button.ghost { margin-top: 16rpx }`，它声明在后面会把本按钮顶下去，
	     所以选择器带上 .batch-scan-head 提高优先级，用 px 与 .badge（App.vue，px 定义）对齐。
*/
.batch-scan-head button.batch-scan-sound {
	display: inline-block;
	margin: 0 0 0 8px;
	padding: 2px 10px;
	border: 1px solid #d3dae0;
	border-radius: 999px;
	background: #eef1f4;
	color: #475569;
	font-size: 12px;
	line-height: 1.5;
	min-height: 0;
	height: auto;
	box-sizing: border-box;
}

/* uni-app 的 button 默认还带一层 ::after 边框，会和上面的 border 叠成双线 */
.batch-scan-head button.batch-scan-sound::after {
	border: none;
}

.batch-scan-head button.batch-scan-sound.button-hover {
	background: #e2e8ee;
	color: #334155;
}

.batch-scan-slot {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 100%;
	height: 40vh;
	margin-top: 16rpx;
	padding: 0 24rpx;
	background: #101a22;
	border-radius: 12rpx;
}

.batch-scan-slot-hint {
	font-size: 24rpx;
	color: #b6c6d1;
	text-align: center;
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

/* 需求 7：漏扫高亮警告条 —— 比普通 hint 更醒目，但颜色不是唯一线索（前面带 ⚠️ 与文字） */
.underfill-warn {
	display: block;
	margin-top: 16rpx;
	padding: 16rpx 20rpx;
	font-size: 26rpx;
	font-weight: 600;
	color: #b45309;
	background: #fdf3e5;
	border: 2rpx solid #e0a458;
	border-radius: 10rpx;
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

/*
	多行批量录入框（手动粘贴 / 图库辅助共用）：
	改成 textarea 后高度要放开，否则会沿用 .input 的 76rpx 单行高度，粘贴 6 个序列号只能看到一行。
	uni-app 里 textarea 外层是 <uni-textarea>、内层才是真实 textarea，两层都要约束。
*/
.batch-input {
	height: auto;
	min-height: 170rpx;
	padding: 16rpx 20rpx;
	line-height: 1.6;
}

.batch-input .uni-textarea-textarea {
	min-height: 140rpx;
	line-height: 1.6;
}

/*
	OCR 候选列表（阶段 2）：一行一枚候选 = 序号 + 码 + 状态 + 删除。
	识别失败/无插件时这一段不渲染，浮层里只剩多行手动录入 —— 降级路径必须永远可用。
*/
.ocr-head {
	margin-top: 16rpx;
}

.ocr-list {
	margin-top: 12rpx;
	border: 1rpx solid #e2ebee;
	border-radius: 12rpx;
	background: #f7fafb;
}

.ocr-row {
	display: flex;
	/* 顶部对齐：徽标与删除按钮的上边缘必须落在同一水平线（见 .ocr-row button.ocr-del 注释） */
	align-items: flex-start;
	padding: 12rpx 16rpx;
	border-bottom: 1rpx solid #e8eff2;
}

.ocr-row:last-child {
	border-bottom: none;
}

/* 已删除的候选：整行浅灰 + 删除线，按钮变「已删除」并 disabled（保留可追溯） */
.ocr-row.is-deleted {
	background: #fafafa;
}

.ocr-row.is-deleted .ocr-index,
.ocr-row.is-deleted .ocr-code {
	color: #909399;
	text-decoration: line-through;
}

.ocr-row.is-deleted .ocr-del {
	color: #b9bfc6;
	background: #f4f4f5;
}

.hint-deleted {
	color: #909399;
}

.ocr-index {
	width: 44rpx;
	color: #8697a3;
	font-size: 24rpx;
	/* 与下面的 .ocr-code 同一个行高，单行时序号/码文字与右侧胶囊视觉齐平（24px = 胶囊高度） */
	line-height: 24px;
}

.ocr-code {
	flex: 1;
	font-size: 24rpx;
	line-height: 24px;
	margin-right: 10rpx;
}

/*
	候选行右侧操作列：删除按钮与「有效 / 本次重复 / 无效 / 已删除」徽标**同款几何**
	（同高、同内边距、同圆角、同字号、同线宽），只把颜色换成中性灰做视觉区分。

	三个必须踩准的点（与 .batch-scan-head button.batch-scan-sound 是同一套教训）：
	  1. uni-app 的 <button> 自带 padding / line-height / margin auto，必须逐项覆盖；
	  2. 页面上另有 `button.ghost { margin-top: 16rpx }`，优先级 (0,1,1) 高于 .ocr-del (0,1,0)，
	     会把这个按钮顶下去 6px —— 所以选择器带 .ocr-row 提权（.ocr-row button.ocr-del = 0,2,1）；
	  3. uni-button 自带一层 ::after 边框，不关掉会和 border 叠成双线。

	另外**必须用 px**：设备 dpr=3.5 会把边框吸附到整数物理像素（1px→0.857px、1rpx→0.286px），
	用 rpx 去对齐 px 定义的 .badge 永远差一档。
*/
.ocr-row button.ocr-del {
	display: inline-block;
	margin: 0 0 0 8px; /* 覆盖 button.ghost 的 margin-top: 16rpx */
	padding: 2px 10px; /* 与 .badge 一致 */
	border: 1px solid #d3dae0;
	border-radius: 999px; /* 胶囊，与 .badge 一致 */
	background: #ffffff; /* 中性色，保留与徽标的视觉区分 */
	color: #475569;
	font-size: 12px; /* 与 .badge 一致 */
	line-height: 1.5; /* 与 .badge 一致 */
	min-height: 0;
	height: auto;
	box-sizing: border-box;
}

.ocr-row button.ocr-del::after {
	border: none;
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
	/* 罐编号靠右：它排在行尾，左边留出间距不贴着罐号 */
	margin-left: 12rpx;
	flex: 0 0 auto;
}

.slot-can-code {
	font-size: 22rpx;
	color: #5a6b77;
}

/* 罐行：罐号在左、罐编号靠右 */
.can-head {
	align-items: center;
}

/* 20 位箱号 / 罐号在窄屏上必须能折行：
   不给 min-width:0 的话，flex 子项会直接溢出而不是换行。
   编号按采集顺序排在行尾（靠右对齐），所以码在左、编号在右。 */
.box-head .code,
.can-head .code {
	flex: 1;
	min-width: 0;
	margin-right: 12rpx;
	text-align: left;
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
