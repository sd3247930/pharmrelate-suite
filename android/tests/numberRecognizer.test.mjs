/**
 * 追溯码视觉识别契约层单测（v1.4.0）。
 *
 * 重点验证「识别只负责看见什么数字、业务层负责校验」这条边界：
 * 不猜测、不补位、不把字母转成数字、置信度阈值、噪声剔除、多候选保留。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/numberRecognizer.test.mjs
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const source = readFileSync(resolve(here, '..', 'services', 'numberRecognizer.js'), 'utf8')
const nr = await import('data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64'))

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
section('① 默认 Provider：本机无识别引擎 → 严格失败，绝不猜测')
// ---------------------------------------------------------------------------

equal(nr.getProviderName(), 'manualConfirmProvider', '默认 Provider 是 manualConfirmProvider')

{
	const result = await nr.recognizeNumber('_doc/photo.jpg', { kind: 'box' })
	equal(result.success, false, '默认 Provider 返回 success=false')
	equal(result.number, '', '默认 Provider 不返回号码')
	equal(result.confidence, 0, '默认 Provider 置信度为 0')
	equal(result.needsConfirmation, true, '默认 Provider 要求人工确认')
	equal(result.sourceType, 'unknown', '来源类型 unknown')
	equal(result.candidates.length, 0, '没有候选')
	equal(Object.keys(result).length, 6, '结果只有契约里的 6 个字段')
}

{
	const empty = await nr.recognizeNumber('', {})
	equal(empty.success, false, '空图片路径 → 直接失败（不调用 Provider）')
}

// ---------------------------------------------------------------------------
section('② 噪声剔除：段落标记 / 空格 / 下划线 / 光标残留 / 连字符')
// ---------------------------------------------------------------------------

const ok = (raw) => nr.normalizeResult(raw)

equal(ok({ success: true, number: '1\u21B5', confidence: 0.9 }).number, '1', 'Word 段落标记 ↵ 被剔除（1↵ → 1）')
equal(ok({ success: true, number: ' 1 ', confidence: 0.9 }).number, '1', '首尾空格被剔除')
equal(ok({ success: true, number: '1_', confidence: 0.9 }).number, '1', '下划线被剔除')
equal(ok({ success: true, number: '1|', confidence: 0.9 }).number, '1', '光标竖线被剔除')
equal(ok({ success: true, number: '1\u200B', confidence: 0.9 }).number, '1', '零宽字符被剔除')
equal(ok({ success: true, number: ' 12\u21B5 ', confidence: 0.95 }).number, '12', '多位数 12↵ 也得 12')
equal(ok({ success: true, number: '01', confidence: 0.9 }).number, '01', '前导零原样保留（业务层允许）')
equal(nr.sanitizeDigits('1\u21B5 _ 2'), '12', 'sanitizeDigits 只剔噪声、不改变数字')
// 现场罐码标签印的就是「8021762-9000000001003」：分段连字符属于排版噪声
equal(
	ok({ success: true, number: '8021762-9000000001003', confidence: 0.95 }).number,
	'80217629000000001003',
	'罐码分段连字符被剔除（8021762-9000000001003 → 20 位）'
)
equal(
	nr.sanitizeDigits(' 8021762 - 9000000001003 '),
	'80217629000000001003',
	'连字符两侧带空格也能剔干净'
)
equal(nr.sanitizeDigits('1-2-3'), '123', '连续分段 1-2-3 全部剔除')
equal(nr.sanitizeDigits('80217629000000001003'), '80217629000000001003', '本身无连字符 → 幂等')
equal(nr.sanitizeDigits('8206233-000003000001'), '8206233000003000001', '粒子码分段连字符同样按噪声剔除')
equal(nr.sanitizeDigits('-1'), '-1', '行首负号保留（它是符号，不是分段符）')

// ---------------------------------------------------------------------------
section('③ 字母不转数字 / 不猜测 / 不补位')
// ---------------------------------------------------------------------------

const alpha = ok({ success: true, number: 'I23', confidence: 0.99 })
equal(alpha.success, false, 'I23 判失败（不把 I 强行当 1）')
equal(alpha.number, '', '失败时不保留会被误读的原值')
equal(ok({ success: true, number: 'O0', confidence: 0.99 }).success, false, 'O0 判失败（不把 O 当 0）')
equal(ok({ success: true, number: 'S1', confidence: 0.99 }).success, false, 'S1 判失败（不把 S 当 5）')
equal(ok({ success: true, number: '1a', confidence: 0.99 }).success, false, '1a 判失败')
equal(ok({ success: true, number: '1.5', confidence: 0.99 }).success, false, '小数 1.5 判失败')
equal(ok({ success: true, number: '-1', confidence: 0.99 }).success, false, '负数 -1 判失败')
equal(ok({ success: true, number: '  ', confidence: 0.99 }).success, false, '空白串判失败')
check(ok({ success: true, number: '1', confidence: 0.9 }).number !== '00000000000000000001', '绝不补位成 20 位')
equal(ok({ success: true, number: '1', confidence: 0.9 }).number.length, 1, '号码长度保持原样（1 就是 1）')

// ---------------------------------------------------------------------------
section('④ 置信度阈值 0.70')
// ---------------------------------------------------------------------------

equal(ok({ success: true, number: '1', confidence: 0.7 }).needsConfirmation, false, '0.70 达标 → 不需要人工确认')
equal(ok({ success: true, number: '1', confidence: 0.69 }).needsConfirmation, true, '0.69 低于阈值 → 需要人工确认')
equal(ok({ success: true, number: '1', confidence: 0.1 }).needsConfirmation, true, '低置信度 → 需要人工确认')
equal(ok({ success: true, number: '1', confidence: 1.5 }).confidence, 1, '置信度 >1 被夹到 1')
equal(ok({ success: true, number: '1', confidence: -1 }).confidence, 0, '负数置信度夹到 0')
equal(ok({ success: true, number: '1', confidence: '0.8' }).confidence, 0.8, '字符串置信度可解析')
equal(ok({ success: true, number: '1' }).confidence, 0, '缺置信度按 0 处理（视为低置信度）')
equal(ok({ success: true, number: '1' }).needsConfirmation, true, '缺置信度 → 要求人工确认')
equal(ok({ success: false, number: '1', confidence: 0.99 }).needsConfirmation, true, '失败时一律要求人工确认')

// ---------------------------------------------------------------------------
section('⑤ 职责边界：识别层不做业务判断（长度 / 前缀交业务层）')
// ---------------------------------------------------------------------------

const shortCode = ok({ success: true, number: '8021761000001406604', confidence: 0.95 }) // 19 位
equal(shortCode.success, true, '识别层对 19 位仍返回 success=true（它确实看见了这些数字）')
equal(shortCode.number, '8021761000001406604', '识别层如实返回 19 位，不做业务拦截')
check(
	nr.normalizeResult({ success: true, number: '80217629000000001002', confidence: 0.9 }).success,
	'前缀是罐号的串在箱号步骤也照常返回，由业务层去拦'
)
check(!('max' in shortCode), '识别结果里没有业务上限字段')
check(!('prefix' in shortCode), '识别结果里没有业务前缀字段')

// ---------------------------------------------------------------------------
section('⑥ 多候选 candidates')
// ---------------------------------------------------------------------------

const many = ok({ success: true, number: '1', confidence: 0.9, candidates: ['1', '2'] })
equal(many.candidates.length, 2, '两个候选被保留（业务层据此报警）')
equal(many.candidates.join(','), '1,2', '候选顺序原样保留')
const noisyCandidates = ok({ success: false, confidence: 0.2, candidates: ['1\u21B5', ' 2 ', '', 'I3'] })
equal(noisyCandidates.candidates.join(','), '1,2,I3', '候选逐个净化：噪声剔除、空候选丢弃、字母保留但不改')
equal(ok({ success: true, number: '7', confidence: 0.9 }).candidates.join(','), '7', '没有 candidates 时用 number 兜底成单候选')
equal(ok({ success: false, confidence: 0.1 }).candidates.length, 0, '没号码也没候选 → 空数组')

// ---------------------------------------------------------------------------
section('⑦ Provider 插拔与异常处理')
// ---------------------------------------------------------------------------

{
	const fake = async () => ({ success: true, number: '1\u21B5', confidence: 0.93, sourceType: 'computer_document' })
	Object.defineProperty(fake, 'name', { value: 'fakeOcrProvider' })
	nr.setProvider(fake)
	equal(nr.getProviderName(), 'fakeOcrProvider', 'setProvider 后可读到 Provider 名')
	const result = await nr.recognizeNumber('_doc/word.jpg', { kind: 'box' })
	equal(result.success, true, '假 Provider 返回成功')
	equal(result.number, '1', '假 Provider 的 1↵ 被净化成 1（验收点 1 的契约行为）')
	equal(result.confidence, 0.93, '置信度透传')
	equal(result.sourceType, 'computer_document', '来源类型透传')
	equal(result.needsConfirmation, false, '0.93 ≥ 0.70 → 不需要人工确认')
}

{
	const broken = async () => {
		throw new Error('provider boom')
	}
	Object.defineProperty(broken, 'name', { value: 'brokenProvider' })
	nr.setProvider(broken)
	const result = await nr.recognizeNumber('_doc/x.jpg', {})
	equal(result.success, false, 'Provider 抛错时不冒泡，按识别失败处理')
	equal(result.needsConfirmation, true, 'Provider 抛错 → 要求人工确认')
}

nr.setProvider(null)
equal(nr.getProviderName(), 'manualConfirmProvider', 'setProvider(null) 回落默认 Provider')
equal((await nr.recognizeNumber('_doc/x.jpg', {})).success, false, '回落默认 Provider 后仍严格失败')
equal(nr.CONFIDENCE_THRESHOLD, 0.7, '阈值常量为 0.70')
equal(nr.SOURCE_TYPES.COMPUTER_DOCUMENT, 'computer_document', 'SOURCE_TYPES 含 computer_document')
equal(Object.keys(nr.SOURCE_TYPES).length, 4, 'SOURCE_TYPES 共 4 种')
equal(ok({ success: true, number: '1', confidence: 0.9, sourceType: 'nonsense' }).sourceType, 'unknown', '未知来源类型归一为 unknown')

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`识别契约层单测全部通过（${passed} 项）。`)
process.exit(0)
