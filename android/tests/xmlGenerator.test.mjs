/**
 * 本机 XML 生成器单测（v1.3.3）。
 *
 * 关键一条：**与后端基准文件 backend/tests/golden/1箱3罐.xml 逐字节比对**——
 * 手机端与电脑端的 XML 必须一模一样，二期同步才不会打架。
 *
 * 加载方式说明：`services/xmlGenerator.js` 里有 `import { FIXED_PARAMS } from './localBatch.js'`，
 * 而 Node 不允许从 data: URL 里做相对导入，所以这里先把 localBatch.js 也编成 data: URL，
 * 再把 import 说明符替换掉 —— 这样**不为测试改产品代码**。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/xmlGenerator.test.mjs
 */
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const service = (name) => resolve(here, '..', 'services', name)
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')

const localUrl = toDataUrl(readFileSync(service('localBatch.js'), 'utf8'))
const genSource = readFileSync(service('xmlGenerator.js'), 'utf8').replace(
	"from './localBatch.js'",
	`from '${localUrl}'`
)
const xg = await import(toDataUrl(genSource))
// 同一份 localBatch（data: URL 加载），只用来读虚拟箱号常量，保证不与产品代码漂移
const lb = await import(localUrl)

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

/**
 * 找基准文件。三条路子，**都不写死本机绝对路径**：
 *   1. 从本文件往上两级 —— 仓库里 android/ 是指向 HBuilderX 工程目录的 junction，
 *      所以从仓库路径跑时 `../../backend/tests/golden/` 就是仓库的 backend；
 *   2. HBuilderX 工程目录单独跑时够不到仓库，用环境变量 PHARMRELATE_GOLDEN_XML 指过来；
 *   3. 都没有就用工程内自带的副本 `tests/fixtures/golden-1箱3罐.xml`，
 *      保证在任何目录下都能跑。
 *
 * 第 3 条是「副本」，所以下面加了一条防漂移断言：只要后端基准也能找到，
 * 就要求两者逐字节一致 —— 副本过期会立刻红，不会静默放过。
 */
const BACKEND_GOLDEN = resolve(here, '..', '..', 'backend', 'tests', 'golden', '1箱3罐.xml')
const LOCAL_GOLDEN = resolve(here, 'fixtures', 'golden-1箱3罐.xml')
const GOLDEN_CANDIDATES = [
	BACKEND_GOLDEN,
	process.env.PHARMRELATE_GOLDEN_XML || '',
	LOCAL_GOLDEN
].filter(Boolean)
const goldenPath = GOLDEN_CANDIDATES.find((item) => existsSync(item))

if (existsSync(BACKEND_GOLDEN) && existsSync(LOCAL_GOLDEN)) {
	equal(
		readFileSync(LOCAL_GOLDEN, 'utf8'),
		readFileSync(BACKEND_GOLDEN, 'utf8'),
		'工程内基准副本与 backend/tests/golden/1箱3罐.xml 逐字节一致（副本不能悄悄过期）'
	)
}

/** 与 backend/tests/golden/1箱3罐.xml 对应的本地批次（1 箱 3 罐 3 粒）。 */
const goldenBatch = {
	batchNo: '20260901',
	produceDate: '2026-09-23',
	expireDate: '2026-10-23',
	boxes: [
		{
			boxIndex: 1,
			boxCode: '80217619000000001003',
			cans: [
				{ canIndex: 1, canCode: '80217629000000001005', plannedParticleCount: 1, particles: ['82062339000000001004'] },
				{ canIndex: 2, canCode: '80217629000000001004', plannedParticleCount: 1, particles: ['82062339000000001001'] },
				{
					canIndex: 3,
					canCode: '80217629000000001006',
					plannedParticleCount: 2,
					particles: ['82062339000000001003', '82062339000000001002']
				}
			]
		}
	]
}

// ---------------------------------------------------------------------------
section('① 与后端基准文件逐字节一致')
// ---------------------------------------------------------------------------

if (!goldenPath) {
	check(false, '找到后端基准文件 1箱3罐.xml', `试过：${GOLDEN_CANDIDATES.join(' / ')}`)
} else {
	const golden = readFileSync(goldenPath, 'utf8')
	const generated = xg.renderXml(goldenBatch)
	check(generated === golden, 'renderXml(1箱3罐) === golden/1箱3罐.xml（逐字节）', goldenPath)
	if (generated !== golden) {
		const a = generated.split('\n')
		const b = golden.split('\n')
		for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
			if (a[index] !== b[index]) {
				console.log(`    首个不同行 #${index + 1}：生成=${JSON.stringify(a[index])} 基准=${JSON.stringify(b[index])}`)
				break
			}
		}
	}
}

// ---------------------------------------------------------------------------
section('② 编码/换行规范：无 BOM、纯 LF、末尾恰好一个换行')
// ---------------------------------------------------------------------------

const sample = xg.renderXml(goldenBatch)
check(!sample.startsWith('\uFEFF'), '无 BOM')
check(sample.indexOf('\r') < 0, '不含 CR（纯 LF）')
check(sample.endsWith('\n'), '以换行结尾')
check(!sample.endsWith('\n\n'), '末尾不是两个换行')
equal(sample.length - sample.replace(/\n+$/, '').length, 1, '末尾恰好一个换行')

// ---------------------------------------------------------------------------
section('③ 第 1 行 = XML 声明紧接 <Document>，且无缩进')
// ---------------------------------------------------------------------------

const firstLine = sample.split('\n')[0]
check(
	firstLine.startsWith('<?xml version="1.0" encoding="utf-8"?><Document '),
	'第 1 行是声明紧接 <Document>',
	firstLine.slice(0, 60)
)
equal(sample.split('\n')[1], '<Events Version="3.0">', '第 2 行是 <Events Version="3.0">')
check(!sample.includes('\t'), '没有任何 Tab 缩进')
check(sample.split('\n').every((line) => line === '' || line === line.trimStart()), '每一行都没有行首空格缩进')
check(
	sample.split('\n').filter((line) => line.includes('<Code ')).every((line) => line === line.trim()),
	'Code 行没有缩进'
)

// ---------------------------------------------------------------------------
section('④ 属性顺序固定 + 批次映射')
// ---------------------------------------------------------------------------

const order = (line, attrs) => {
	let last = -1
	return attrs.every((attr) => {
		const index = line.indexOf(`${attr}=`)
		if (index < 0 || index < last) return false
		last = index
		return true
	})
}
check(order(firstLine, ['xmlns:xsi', 'xsi:noNamespaceSchemaLocation', 'License']), 'Document 属性顺序：xmlns:xsi → schemaLocation → License')
const relationLine = sample.split('\n').find((line) => line.startsWith('<Relation '))
check(
	order(relationLine, ['productCode', 'subTypeNo', 'cascade', 'packageSpec', 'comment']),
	'Relation 属性顺序：productCode → subTypeNo → cascade → packageSpec → comment'
)
const batchLine = sample.split('\n').find((line) => line.startsWith('<Batch '))
check(
	order(batchLine, ['batchNo', 'madeDate', 'validateDate', 'workshop', 'lineName', 'lineManager']),
	'Batch 属性顺序：batchNo → madeDate → validateDate → workshop → lineName → lineManager'
)
const boxLine = sample.split('\n').find((line) => line.includes('packLayer="3"'))
check(order(boxLine, ['curCode', 'packLayer', 'flag']), '箱 Code 属性顺序：curCode → packLayer → flag（无 parentCode）')
check(!boxLine.includes('parentCode'), '箱节点没有 parentCode')
const canLine = sample.split('\n').find((line) => line.includes('packLayer="2"'))
check(order(canLine, ['curCode', 'packLayer', 'parentCode', 'flag']), '罐 Code 属性顺序：curCode → packLayer → parentCode → flag')
check(sample.includes('cascade="1:5:2500"'), 'cascade 是固定字面量 1:5:2500')
check(sample.includes('<Relation productCode="9999999"'), '固定参数 productCode=9999999')
check(sample.includes('License="1001123"') && sample.includes('workshop="一号车间"'), '固定参数 License / workshop 正确')
check(
	batchLine.includes('batchNo="20260901"') &&
		batchLine.includes('madeDate="2026-09-23"') &&
		batchLine.includes('validateDate="2026-10-23"'),
	'批次映射：batchNo / produceDate→madeDate / expireDate→validateDate'
)

// ---------------------------------------------------------------------------
section('⑤ 粒子顺序 = 采集顺序（严禁排序）')
// ---------------------------------------------------------------------------

const orderBatch = {
	batchNo: 'T-ORDER',
	produceDate: '2026-09-01',
	expireDate: '2026-10-01',
	boxes: [
		{
			boxCode: '1',
			cans: [{ canCode: '1', particles: ['82062330000000000003', '82062330000000000001', '82062330000000000002'] }]
		}
	]
}
const particleLines = xg
	.renderXml(orderBatch)
	.split('\n')
	.filter((line) => line.includes('packLayer="1"'))
equal(particleLines.length, 3, '3 个粒子节点')
check(particleLines[0].includes('curCode="82062330000000000003"'), '第 1 个粒子是采集时的第 1 个（03）')
check(particleLines[1].includes('curCode="82062330000000000001"'), '第 2 个粒子是采集时的第 2 个（01，未被排序）')
check(particleLines[2].includes('curCode="82062330000000000002"'), '第 3 个粒子是采集时的第 3 个（02）')

// ---------------------------------------------------------------------------
section('⑥ 多箱 parentCode 挂载 + 跳过未采集节点')
// ---------------------------------------------------------------------------

const multiBatch = {
	batchNo: 'T-MULTI',
	produceDate: '2026-09-01',
	expireDate: '2026-10-01',
	boxes: [
		{
			boxCode: '1',
			cans: [
				{ canCode: '1', particles: ['82062330000000000001'] },
				{ canCode: '2', particles: ['82062330000000000002'] }
			]
		},
		{ boxCode: '2', cans: [{ canCode: '1', particles: ['82062330000000000003', ''] }] }
	]
}
const multiXml = xg.renderXml(multiBatch)
const multiLines = multiXml.split('\n')
equal(multiLines.filter((line) => line.includes('packLayer="3"')).length, 2, '2 个箱节点')
equal(multiLines.filter((line) => line.includes('packLayer="2"')).length, 3, '3 个罐节点（箱 2 的罐 1 也算）')
equal(multiLines.filter((line) => line.includes('packLayer="1"')).length, 3, '3 个粒子节点（空槽位被跳过）')
check(multiXml.includes('<Code curCode="1" packLayer="2" parentCode="1" flag="2"/>'), '箱 1 的罐 1：parentCode 指箱 1')
check(
	multiXml.includes('<Code curCode="1" packLayer="2" parentCode="2" flag="2"/>'),
	'箱 2 的罐 1：parentCode 指箱 2（同名不同箱）'
)
check(
	multiXml.includes('<Code curCode="82062330000000000003" packLayer="1" parentCode="1" flag="2"/>'),
	'箱 2 罐 1 的粒子：parentCode 指向它自己的罐号'
)
const multiNodes = xg.exportNodes(multiBatch)
equal(multiNodes.nodes.length, 8, 'exportNodes 共 8 个节点（2 箱 + 3 罐 + 3 粒子）')
equal(multiNodes.skipped, 1, '空槽位被计为 1 个跳过')
check(!multiXml.includes('curCode=""'), 'XML 里不会出现空 curCode')

const emptyBoxBatch = {
	batchNo: 'T-SKIP',
	produceDate: '2026-09-01',
	expireDate: '2026-10-01',
	boxes: [
		{ boxCode: '', cans: [{ canCode: '', particles: [''] }] },
		{ boxCode: '9', cans: [{ canCode: '8', particles: ['82062330000000000009'] }] }
	]
}
const skipNodes = xg.exportNodes(emptyBoxBatch)
equal(skipNodes.nodes.length, 3, '未采集的整箱被跳过，只剩第 2 箱的 3 个节点')
equal(skipNodes.skipped, 3, '第 1 箱的箱/罐/粒子都计入跳过')
check(xg.renderXml(emptyBoxBatch).includes('<Code curCode="9" packLayer="3" flag="2"/>'), '第 2 箱正常输出')

// ---------------------------------------------------------------------------
section('⑥之二 虚拟箱（箱数 = 0）：XML 里必须仍有 packLayer="3"，不能是空文件')
// ---------------------------------------------------------------------------

const virtualBoxBatch = {
	batchNo: '20260929',
	produceDate: '2026-09-29',
	expireDate: '2026-11-28',
	boxes: [
		{
			boxIndex: 1,
			boxCode: lb.VIRTUAL_BOX_CODE,
			virtual: true,
			reviewConfirmed: true,
			cans: [
				{
					canIndex: 1,
					canCode: '80217629000000001005',
					plannedParticleCount: 1,
					confirmed: true,
					particles: ['82062339000000001004']
				}
			]
		}
	]
}
const virtualNodes = xg.exportNodes(virtualBoxBatch)
const virtualXml = xg.renderXml(virtualBoxBatch)

equal(lb.VIRTUAL_BOX_CODE, '80217619999999999999', '虚拟箱号常量')
equal(virtualNodes.nodes.length, 3, '虚拟箱也有 3 个节点（箱 + 罐 + 粒子）')
equal(virtualNodes.skipped, 0, '虚拟箱场景没有任何节点被跳过')
check(
	virtualXml.includes(`<Code curCode="${lb.VIRTUAL_BOX_CODE}" packLayer="3" flag="2"/>`),
	'虚拟箱节点存在且 packLayer="3"（不是空文件）'
)
check(
	virtualXml.includes(`packLayer="2" parentCode="${lb.VIRTUAL_BOX_CODE}"`),
	'罐的 parentCode 指向虚拟箱'
)
check(
	virtualXml.includes('packLayer="1" parentCode="80217629000000001005"'),
	'粒子仍然指向自己的罐'
)
equal(virtualXml.split('\n').filter((line) => line.includes('<Code ')).length, 3, '恰好 3 个 Code 节点')

// ---------------------------------------------------------------------------
section('⑦ 文件名格式 Relation_{批号}_{yyyyMMddHHmmss}.html')
// ---------------------------------------------------------------------------

equal(
	xg.xmlFileName('20260901', new Date(2026, 8, 28, 14, 30, 0)),
	'Relation_20260901_20260928143000.html',
	'文件名 = Relation_批号_年月日时分秒.html'
)
equal(
	xg.xmlFileName('V133-XML', new Date(2026, 8, 28, 3, 5, 9)),
	'Relation_V133-XML_20260928030509.html',
	'带连字符的批号原样保留'
)
check(xg.xmlFileName('', new Date(2026, 0, 2, 3, 4, 5)).startsWith('Relation_batch_'), '空批号兜底为 batch')
check(!/[:*?"<>|]/.test(xg.xmlFileName('A/B:C', new Date(2026, 0, 2, 3, 4, 5))), '批号里的非法文件名字符被替换')

// ---------------------------------------------------------------------------
section('⑧ HTML 转义与 <pre> 包裹')
// ---------------------------------------------------------------------------

const html = xg.renderHtml(sample, '20260901')
check(html.startsWith('<!DOCTYPE html>'), 'HTML 以 <!DOCTYPE html> 开头')
check(html.includes('<meta charset="utf-8">'), 'HTML 带 utf-8 meta')
check(html.includes('<title>批次 20260901 关联关系 XML</title>'), 'HTML title 带批号')
check(html.includes('<pre>') && html.includes('</pre>'), 'HTML 用 <pre> 包裹')
check(html.includes('&lt;Document'), 'XML 的 < 被转义为 &lt;（浏览器不会吞标签）')
check(!html.includes('<Document'), 'HTML 里不存在未转义的 <Document')
equal(html.split('&lt;Code ').length - 1, 8, '8 个 Code 节点全部出现在 HTML 里')
equal(xg.escapeAttr('a&b<c>d"e'), 'a&amp;b&lt;c&gt;d&quot;e', 'escapeAttr 转义 & < > "')
equal(xg.escapeText('a&b<c>d"e'), 'a&amp;b&lt;c&gt;d"e', 'escapeText 只转义 & < >')

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`XML 生成器单测全部通过（${passed} 项）。`)
process.exit(0)
