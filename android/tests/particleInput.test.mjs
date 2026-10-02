/**
 * 粒子码手动录入解析层单测（阶段 A）。
 *
 * 覆盖：13 位补前缀 / 20 位原样 / 双前缀剥离 / 长度与字符非法 / 批量分隔符 /
 *      输入内去重 / 汇总文案。
 * 另外把 `PARTICLE_PREFIX`、`PARTICLE_CODE_LENGTH` 与 `localBatch` 的
 * `CODE_PREFIXES[1]`、`BARCODE_LENGTH` 钉在一起，防止两边悄悄漂移。
 *
 * 加载方式与其它单测一致：源码读出来按 ESM 从 data: URL 加载，不为测试改产品代码。
 *
 * 运行：
 *   cd "<ANDROID_PROJECT_DIR>"
 *   node tests/particleInput.test.mjs
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const toDataUrl = (source) => 'data:text/javascript;base64,' + Buffer.from(source, 'utf8').toString('base64')
const load = (name) => import(toDataUrl(readFileSync(resolve(here, '..', 'services', name), 'utf8')))

const pi = await load('particleInput.js')
const lb = await load('localBatch.js')

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

const PREFIX = '8206233'
const short = (n) => String(n).padStart(13, '0')
const full = (n) => PREFIX + short(n)

// ---------------------------------------------------------------------------
section('常量锁定：解析层与数据层不许漂移')
// ---------------------------------------------------------------------------

equal(pi.PARTICLE_PREFIX, lb.CODE_PREFIXES[1], 'PARTICLE_PREFIX = localBatch.CODE_PREFIXES[1]')
equal(pi.PARTICLE_CODE_LENGTH, lb.BARCODE_LENGTH, 'PARTICLE_CODE_LENGTH = localBatch.BARCODE_LENGTH')
equal(pi.PARTICLE_SHORT_LENGTH, 13, '短码位数 = 13（20 − 7）')
equal(pi.PARTICLE_PREFIX, PREFIX, '前缀字面量 = 8206233')

// ---------------------------------------------------------------------------
section('normalizeParticleCode：单条解析')
// ---------------------------------------------------------------------------

{
	const shortResult = pi.normalizeParticleCode(short(1))
	equal(shortResult.ok, true, '13 位纯数字 → 通过')
	equal(shortResult.mode, 'short', '标记为 short（补前缀）')
	equal(shortResult.code, full(1), '自动拼成 20 位完整粒子码')

	const fullResult = pi.normalizeParticleCode(full(2))
	equal(fullResult.ok, true, '20 位且前缀正确 → 通过')
	equal(fullResult.mode, 'full', '标记为 full（原样保留）')
	equal(fullResult.code, full(2), '不重复加前缀（避免 82062338206233…）')

	const spaced = pi.normalizeParticleCode('  ' + full(3) + '  ')
	equal(spaced.ok, true, '首尾空格容忍')
	equal(spaced.code, full(3), '空格清除后仍原样')

	// 前缀被敲两遍：7 + 20 = 27 位
	const doubled = pi.normalizeParticleCode(PREFIX + full(4))
	equal(doubled.ok, true, '27 位双前缀 → 通过')
	equal(doubled.mode, 'stripped', '标记为 stripped（去掉了多余那一遍前缀）')
	equal(doubled.code, full(4), '剥离后得到正确 20 位码')

	const wrongPrefix = pi.normalizeParticleCode('8021761' + short(5))
	equal(wrongPrefix.ok, false, '20 位但前缀不对 → 拒绝')
	equal(wrongPrefix.reason, 'WRONG_PREFIX', '原因 = WRONG_PREFIX')
	check(wrongPrefix.message.includes('8206233'), '提示里带上正确前缀', wrongPrefix.message)

	const empty = pi.normalizeParticleCode('   ')
	equal(empty.ok, false, '空/纯空白 → 拒绝')
	equal(empty.reason, 'EMPTY', '原因 = EMPTY（对应"输入不能为空"）')

	const letter = pi.normalizeParticleCode('8206233000000000000O')
	equal(letter.ok, false, '含字母 → 拒绝')
	equal(letter.reason, 'INVALID_FORMAT', '原因 = INVALID_FORMAT（不把 O 猜成 0）')

	;[12, 14, 19, 21].forEach((length) => {
		const token = '8'.repeat(length)
		const result = pi.normalizeParticleCode(token)
		equal(result.ok, false, `${length} 位 → 拒绝`)
		equal(result.reason, 'INVALID_LENGTH', `${length} 位的原因 = INVALID_LENGTH`)
	})

	const zeroPadded = pi.normalizeParticleCode(short(0))
	equal(zeroPadded.code, PREFIX + '0000000000000', '全 0 序列号不会被"纠错"，按原样补前缀')
}

// ---------------------------------------------------------------------------
section('parseParticleBatch：多分隔符与分类')
// ---------------------------------------------------------------------------

{
	const one = pi.parseParticleBatch(short(1))
	equal(one.total, 1, '单条：解析出 1 条')
	equal(one.valid.length, 1, '单条：有效 1 条')

	const six = [1, 2, 3, 4, 5, 6]
	equal(pi.parseParticleBatch(six.map(short).join(' ')).valid.length, 6, '空格分隔 6 个 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join(',')).valid.length, 6, '英文逗号分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join('，')).valid.length, 6, '中文逗号分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join(';')).valid.length, 6, '英文分号分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join('；')).valid.length, 6, '中文分号分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join('、')).valid.length, 6, '顿号分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join('\n')).valid.length, 6, '换行分隔 → 6 条有效')
	equal(pi.parseParticleBatch(six.map(short).join('\t')).valid.length, 6, 'Tab 分隔 → 6 条有效')

	const mixed = `${short(1)}  ${short(2)},${short(3)}\n${short(4)}；${short(5)}、${short(6)},,  `
	const mixedResult = pi.parseParticleBatch(mixed)
	equal(mixedResult.total, 6, '多分隔符混合 + 连续分隔符 + 首尾空白 → 仍解析出 6 条')
	equal(mixedResult.valid.length, 6, '混合输入 6 条全部有效')
	equal(mixedResult.valid[0].code, full(1), '保持输入顺序（第 1 条）')
	equal(mixedResult.valid[5].code, full(6), '保持输入顺序（第 6 条）')

	// 6 个完整 20 位码
	const fullBatch = pi.parseParticleBatch(six.map(full).join(' '))
	equal(fullBatch.valid.length, 6, '6 个完整 20 位码 → 6 条有效')
	equal(fullBatch.valid[0].code, full(1), '20 位码原样保留')

	// 输入内重复
	const dup = pi.parseParticleBatch([short(7), short(7), short(8)].join(' '))
	equal(dup.valid.length, 2, '输入内重复：只留 1 条 + 另一条 = 2 条有效')
	equal(dup.duplicateInInput.length, 1, '输入内重复：识别出 1 条重复')
	equal(dup.duplicateInInput[0].code, full(7), '重复项指向标准化后的码')

	// 短码与完整码指向同一枚 → 也算输入内重复
	const sameCodeTwice = pi.parseParticleBatch(`${short(9)} ${full(9)}`)
	equal(sameCodeTwice.valid.length, 1, '13 位与 20 位指的是同一枚码 → 只留 1 条')
	equal(sameCodeTwice.duplicateInInput.length, 1, '同一枚码写两遍 → 计 1 条重复')

	// 有效 / 重复 / 无效 混合
	const mixedKinds = pi.parseParticleBatch(
		[short(1), short(1), '8021761' + short(2), 'abc', short(3)].join(' ')
	)
	equal(mixedKinds.total, 5, '混合输入：共 5 条')
	equal(mixedKinds.valid.length, 2, '混合输入：有效 2 条')
	equal(mixedKinds.duplicateInInput.length, 1, '混合输入：重复 1 条')
	equal(mixedKinds.invalid.length, 2, '混合输入：无效 2 条（错前缀 + 字母）')
	equal(mixedKinds.invalid[0].reason, 'WRONG_PREFIX', '无效原因 1 = WRONG_PREFIX')
	equal(mixedKinds.invalid[1].reason, 'INVALID_FORMAT', '无效原因 2 = INVALID_FORMAT')

	equal(pi.parseParticleBatch('').total, 0, '空文本 → 0 条')
	equal(pi.parseParticleBatch('   \n  ').total, 0, '纯空白 → 0 条')
	equal(pi.parseParticleBatch(null).total, 0, 'null 输入不炸，返回 0 条')
}

// ---------------------------------------------------------------------------
section('summarizeBatchParse：汇总文案')
// ---------------------------------------------------------------------------

{
	const text = pi.summarizeBatchParse(pi.parseParticleBatch([short(1), short(1), 'abc'].join(' ')))
	equal(text, '本次解析 3 条：有效 1 条，重复 1 条，无效 1 条', '汇总文案把三类都列出来')
	const clean = pi.summarizeBatchParse(pi.parseParticleBatch(short(1)))
	equal(clean, '本次解析 1 条：有效 1 条', '全有效时不提重复/无效')
}

// ---------------------------------------------------------------------------

console.log('')
if (failures.length) {
	console.log(`未通过 ${failures.length} 项：${failures.join('、')}`)
	process.exit(1)
}
console.log(`粒子码手动录入解析层单测全部通过（${passed} 项）。`)
process.exit(0)
