/**
 * 本机 XML 生成器（v1.3.3）。
 *
 * 目标：与 `backend/app/services/xml_builder.py` 的输出**字节级一致**，
 * 用 `backend/tests/golden/1箱3罐.xml` 做单测比对。
 *
 * 口径变更：本版**正式推翻一期 C3**（「手机端不产出 XML」）。
 * 现在本机生成 XML，仅用于「本地原样预览 + 导出 .html」，
 * **仍不同步、不改后端、不改电脑端**；二期同步后仍以主控机生成的 XML 为准。
 *
 * 字节级规则（照抄 xml_builder.py，不可违背）：
 *   1. 无 BOM、UTF-8、纯 LF（\n）、末尾恰好一个换行；
 *   2. 第 1 行 = XML 声明紧接 <Document>，中间无换行；
 *   3. 无任何缩进（不含空格/Tab 缩进），每个 <Code/> 独占一行；
 *   4. 属性顺序固定：
 *      Document: xmlns:xsi → xsi:noNamespaceSchemaLocation → License
 *      Relation: productCode → subTypeNo → cascade → packageSpec → comment
 *      Batch:    batchNo → madeDate → validateDate → workshop → lineName → lineManager
 *      Code:     curCode → packLayer → parentCode → flag
 *   5. 节点顺序：箱 → 罐1 → 罐1 的粒子（原序）→ 罐2 → 罐2 的粒子 → …；
 *   6. 箱 packLayer=3 且无 parentCode；罐 2（parent=箱号）；粒子 1（parent=罐号）；flag=2；
 *   7. 粒子顺序 = 采集原始顺序，**严禁排序**。
 *
 * 拍板决策 1：**跳过未采集节点** —— 箱号为空跳过该箱及其罐/粒子，罐号为空跳过该罐及其粒子，
 * 空槽位跳过；跳过数量回传给界面提示。
 */
import { FIXED_PARAMS } from './localBatch.js'

export const XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>'
export const XSI_NAMESPACE = 'http://www.w3.org/2001/XMLSchema-instance'
export const LINE_SEPARATOR = '\n'

export const LAYER_BOX = 3
export const LAYER_CAN = 2
export const LAYER_PARTICLE = 1

/** 固定值统一从 localBatch 的 FIXED_PARAMS 取，避免两处各写一份对不上。 */
function fixedValue(key) {
	const hit = FIXED_PARAMS.find((item) => item.key === key)
	return hit ? hit.value : ''
}

/** 属性值转义：& < > "（与 xml_builder.py 的 _attr 一致）。 */
export function escapeAttr(value) {
	return String(value == null ? '' : value)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
}

/** HTML 文本转义（<pre> 里用）：& < >，避免浏览器把 XML 标签当 HTML 渲染掉。 */
export function escapeText(value) {
	return String(value == null ? '' : value)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
}

/**
 * 导出节点序列：箱 → 罐 → 粒子（每个罐的粒子紧跟在该罐后面，保持采集顺序）。
 * 返回 `{ nodes, skipped }`：
 *   - nodes = [{ curCode, packLayer, parentCode }]
 *   - skipped = 被跳过的未采集节点数（箱 + 罐 + 粒子槽位）
 */
export function exportNodes(batch) {
	const nodes = []
	let skipped = 0
	const boxes = (batch && batch.boxes) || []

	boxes.forEach((box) => {
		const boxCode = String((box && box.boxCode) || '').trim()
		const cans = (box && box.cans) || []
		if (!boxCode) {
			// 整箱未采集：箱本身 + 它的罐 + 它的粒子槽位全都算跳过
			skipped += 1
			cans.forEach((can) => {
				skipped += 1 + ((can && can.particles) || []).length
			})
			return
		}
		nodes.push({ curCode: boxCode, packLayer: LAYER_BOX, parentCode: null })
		cans.forEach((can) => {
			const canCode = String((can && can.canCode) || '').trim()
			const particles = (can && can.particles) || []
			if (!canCode) {
				skipped += 1 + particles.length
				return
			}
			nodes.push({ curCode: canCode, packLayer: LAYER_CAN, parentCode: boxCode })
			particles.forEach((code) => {
				const value = String(code == null ? '' : code).trim()
				if (!value) {
					skipped += 1
					return
				}
				nodes.push({ curCode: value, packLayer: LAYER_PARTICLE, parentCode: canCode })
			})
		})
	})

	return { nodes, skipped }
}

function codeLine(node, flag) {
	const parts = [`curCode="${escapeAttr(node.curCode)}"`, `packLayer="${node.packLayer}"`]
	if (node.parentCode !== null && node.parentCode !== undefined) {
		parts.push(`parentCode="${escapeAttr(node.parentCode)}"`)
	}
	parts.push(`flag="${escapeAttr(flag)}"`)
	return '<Code ' + parts.join(' ') + '/>'
}

/**
 * 生成 XML 文本。
 * `options.params` 可传自定义固定值对象；不传则用 FIXED_PARAMS。
 */
export function renderXml(batch, options) {
	const custom = (options && options.params) || null
	const value = (key) => (custom ? String(custom[key] == null ? '' : custom[key]) : fixedValue(key))
	const source = batch || {}
	const { nodes } = exportNodes(source)

	const lines = [
		XML_DECLARATION +
			'<Document ' +
			`xmlns:xsi="${XSI_NAMESPACE}" ` +
			`xsi:noNamespaceSchemaLocation="${escapeAttr(value('schemaLocation'))}" ` +
			`License="${escapeAttr(value('license'))}">`,
		`<Events Version="${escapeAttr(value('eventsVersion'))}">`,
		`<Event Name="${escapeAttr(value('eventName'))}">`,
		'<Relation ' +
			`productCode="${escapeAttr(value('productCode'))}" ` +
			`subTypeNo="${escapeAttr(value('subTypeNo'))}" ` +
			`cascade="${escapeAttr(value('cascade'))}" ` +
			`packageSpec="${escapeAttr(value('packageSpec'))}" ` +
			`comment="${escapeAttr(value('comment'))}">`,
		'<Batch ' +
			`batchNo="${escapeAttr(source.batchNo)}" ` +
			`madeDate="${escapeAttr(source.produceDate)}" ` +
			`validateDate="${escapeAttr(source.expireDate)}" ` +
			`workshop="${escapeAttr(value('workshop'))}" ` +
			`lineName="${escapeAttr(value('lineName'))}" ` +
			`lineManager="${escapeAttr(value('lineManager'))}">`
	]

	nodes.forEach((node) => lines.push(codeLine(node, value('flag'))))
	lines.push('</Batch>', '</Relation>', '</Event>', '</Events>', '</Document>')

	return lines.join(LINE_SEPARATOR) + LINE_SEPARATOR
}

function pad2(value) {
	return String(value).padStart(2, '0')
}

/** 文件名：Relation_{批号}_{yyyyMMddHHmmss}.html，时间取设备本地时间。 */
export function xmlFileName(batchNo, at) {
	const date = at instanceof Date ? at : new Date()
	const stamp =
		`${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}` +
		`${pad2(date.getHours())}${pad2(date.getMinutes())}${pad2(date.getSeconds())}`
	// 批号里可能有文件名非法字符，替换掉但不改动其余字符
	const safe = String(batchNo == null ? '' : batchNo)
		.trim()
		.replace(/[\\/:*?"<>|\s]/g, '_')
	return `Relation_${safe || 'batch'}_${stamp}.html`
}

/** 导出用的 HTML：<pre> 包裹**转义后**的 XML，浏览器打开能看清结构。 */
export function renderHtml(xml, batchNo) {
	const title = `批次 ${String(batchNo == null ? '' : batchNo)} 关联关系 XML`
	return [
		'<!DOCTYPE html>',
		'<html>',
		'<head>',
		'<meta charset="utf-8">',
		`<title>${escapeText(title)}</title>`,
		'<style>',
		'body{margin:0;padding:16px;background:#fff;color:#101a22;}',
		'pre{font-family:Consolas,Monaco,"Courier New",monospace;font-size:13px;line-height:1.55;white-space:pre;overflow:auto;}',
		'</style>',
		'</head>',
		'<body>',
		'<pre>' + escapeText(xml) + '</pre>',
		'</body>',
		'</html>',
		''
	].join('\n')
}
