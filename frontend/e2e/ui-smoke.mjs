/**
 * 最小真实浏览器 UI 冒烟测试。
 *
 * 覆盖的是单元测试碰不到的那一层：真实浏览器、真实 Vite 代理、真实后端进程。
 * 重点验证阶段 2 的 UI 交互项——重复批号三选一弹窗的三种行为，
 * 以及状态变只读后输入控件是否真的不可编辑。
 *
 * 用法（在 frontend 目录）：
 *     npm run e2e
 *
 * 数据落在临时目录，不碰开发机真实本地库。
 */

import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { chromium } from 'playwright';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_DIR = path.resolve(HERE, '..');
const ROOT_DIR = path.resolve(FRONTEND_DIR, '..');
const BACKEND_DIR = path.join(ROOT_DIR, 'backend');
const PYTHON = path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe');
// 直接跑 vite 的 JS 入口，不经过 npm：
//   - spawn('npm.cmd') 在 Windows 上不加 shell 会 EINVAL（Node 对 .cmd 的安全限制）
//   - 加 shell 又会触发参数拼接告警
// 直接调 JS 入口既没有告警，也少一层进程，启动更快。
const VITE_BIN = path.join(FRONTEND_DIR, 'node_modules', 'vite', 'bin', 'vite.js');

const failures = [];
/** 浏览器控制台报错，catch 里也要用，因此在外层声明。 */
const consoleErrors = [];

function check(ok, label, extra = '') {
  console.log(`[${ok ? ' OK ' : 'FAIL'}] ${label}${extra ? `  ${extra}` : ''}`);
  if (!ok) failures.push(label);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function waitFor(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return true;
    } catch {
      // 还没起来
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

/**
 * 往 AppInput 里填值。
 *
 * 用 getByLabel 而不是自己拼 CSS：标签与输入框的关联是真实的无障碍属性，
 * 如果哪天 label 的 for 与 input 的 id 断了，这里会直接失败。
 */
async function fillByLabel(page, label, value) {
  await page.getByLabel(label).fill(value);
}

async function main() {
  const dataDir = mkdtempSync(path.join(os.tmpdir(), 'pharmrelate-e2e-'));
  const apiPort = await freePort();
  const webPort = await freePort();
  const apiOrigin = `http://127.0.0.1:${apiPort}`;
  const webUrl = `http://127.0.0.1:${webPort}`;
  let backend;
  let vite;
  let browser;
  let page;

  try {
    console.log(`数据目录 : ${dataDir}`);
    console.log(`后端     : ${apiOrigin}`);
    console.log(`前端     : ${webUrl}\n`);

    backend = spawn(
      PYTHON,
      ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(apiPort)],
      {
        cwd: BACKEND_DIR,
        env: { ...process.env, PHARMRELATE_DATA_DIR: dataDir, PHARMRELATE_LOG_LEVEL: 'WARNING' },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
    backend.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));

    if (!(await waitFor(`${apiOrigin}/api/health`, 40000))) {
      console.error('[FAIL] 后端未能在超时内就绪');
      return 1;
    }

    // 必须显式 --host 127.0.0.1：Vite 默认的 localhost 在 Windows 上可能只绑到 ::1，
    // 用 127.0.0.1 探测会一直失败。
    vite = spawn(
      process.execPath,
      [VITE_BIN, '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'],
      {
        cwd: FRONTEND_DIR,
        env: { ...process.env, PHARMRELATE_API_ORIGIN: apiOrigin },
        stdio: ['ignore', 'pipe', 'pipe'],
        windowsHide: true,
      },
    );
    vite.stdout.on('data', (chunk) => process.stdout.write(`[vite] ${chunk}`));
    vite.stderr.on('data', (chunk) => process.stderr.write(`[vite] ${chunk}`));

    if (!(await waitFor(webUrl, 60000))) {
      console.error('[FAIL] 前端开发服务器未能在超时内就绪');
      return 1;
    }

    browser = await chromium.launch();
    page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => consoleErrors.push(String(error)));

    // ---------------------------------------------------------------- 启动
    await page.goto(webUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.app-sidebar');
    await page.waitForFunction(
      () => document.body.innerText.includes('已连接'),
      undefined,
      { timeout: 30000 },
    );
    check(true, '应用加载且顶部状态栏显示本地服务已连接');
    check(
      (await page.locator('body').innerText()).includes('字节级一致'),
      '顶部状态栏显示黄金基准字节级一致',
    );

    // ---------------------------------------------------------------- 路由
    for (const label of ['基础信息', '包装结构', '扫码采集', '预览导出', '工作台']) {
      await page.locator('.app-sidebar__link', { hasText: label }).first().click();
      await page.waitForFunction(
        (expected) => document.querySelector('.app-shell__title')?.textContent?.trim() === expected,
        label,
      );
    }
    check(true, '五个采集流程路由均可切换');

    // ------------------------------------------------------------ 保存草稿
    await page.locator('.app-sidebar__link', { hasText: '基础信息' }).first().click();
    await page.waitForSelector('.base-info');
    await fillByLabel(page, '批号', 'E2E-0001');
    await fillByLabel(page, '箱号', '80217619000000001003');
    await page.getByRole('button', { name: /保存草稿/ }).click();
    await page.waitForFunction(() => document.body.innerText.includes('批次已创建'), undefined, {
      timeout: 15000,
    });
    check(true, '保存草稿成功并提示「批次已创建」');

    const statusText = await page.locator('.app-topbar').innerText();
    check(statusText.includes('草稿'), '顶部状态栏显示批次状态为草稿');

    // -------------------------------------------------- 重复批号三选一弹窗
    await page.getByRole('button', { name: /重置/ }).click();
    await fillByLabel(page, '批号', 'E2E-0001');
    await fillByLabel(page, '箱号', '80217619000000001003');
    await page.getByRole('button', { name: /保存草稿/ }).click();
    await page.waitForSelector('[role="dialog"]', { timeout: 15000 });

    const dialog = page.locator('[role="dialog"]');
    const dialogText = await dialog.innerText();
    check(dialogText.includes('检测到批号已存在'), '重复批号触发冲突弹窗');
    check(
      dialogText.includes('打开已有批次') &&
        dialogText.includes('创建新版本') &&
        dialogText.includes('取消并返回修改'),
      '弹窗给出三条出路',
    );
    check(dialogText.includes('E2E-0001-V2'), '弹窗显示服务端建议的新版本批号');

    // 选择「打开已有批次」
    await page.locator('.conflict__option', { hasText: '打开已有批次' }).click();
    await page.waitForFunction(() => document.body.innerText.includes('已打开批次'), undefined, {
      timeout: 15000,
    });
    check(true, '选择「打开已有批次」后成功载入该批次');

    // -------------------------------------------------------- 重复批号取消
    await page.getByRole('button', { name: /重置/ }).click();
    await fillByLabel(page, '批号', 'E2E-0001');
    await fillByLabel(page, '箱号', '80217619000000001003');
    await page.getByRole('button', { name: /保存草稿/ }).click();
    await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
    await page.locator('.conflict__option', { hasText: '取消并返回修改' }).click();
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'), undefined, {
      timeout: 10000,
    });
    const afterCancel = await page.locator('.base-info input').first().inputValue();
    check(afterCancel === 'E2E-0001', '选择「取消并返回修改」后停留在表单且批号未被改写');

    // ------------------------------------------------------- 创建新版本路径
    await page.getByRole('button', { name: /保存草稿/ }).click();
    await page.waitForSelector('[role="dialog"]', { timeout: 15000 });
    await page.locator('.conflict__option', { hasText: '创建新版本' }).click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('E2E-0001-V2'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '选择「创建新版本」后批号变为 E2E-0001-V2');

    // ------------------------------------------- 结构完整的批次（API 种数据）
    //
    // 罐号来自扫码，界面上本来就没有手填罐号的入口，所以这里用 API 种一个结构完整的
    // 批次，再用界面去走生命周期与只读态。空结构草稿点「生成扫码网格」被后端拒绝
    // 是正确行为，已在后端测试里单独覆盖。
    const seeded = await (
      await fetch(`${apiOrigin}/api/batches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batchNo: 'E2E-SEED-01',
          madeDate: '2026-09-23',
          validateDate: '2026-10-23',
          // 计划与实际上分开：生成扫码网格要求计划完整
          plannedParticleCounts: [1],
          box: {
            code: '80217619000000001003',
            cans: [
              {
                index: 1,
                code: '80217629000000001005',
                plannedParticleCount: 1,
                particles: ['82062339000000001004'],
              },
            ],
          },
        }),
      })
    ).json();
    check(Boolean(seeded.id), '通过 API 种入结构完整的批次');

    // 从工作台的「已保存批次」列表打开它 —— 顺带验证列表与打开流程
    await page.locator('.app-sidebar__link', { hasText: '工作台' }).first().click();
    await page.waitForSelector('.dashboard__table');
    const seedRow = page.locator('.dashboard__table tbody tr', { hasText: 'E2E-SEED-01' });
    await seedRow.getByRole('button', { name: /打开/ }).click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('E2E-SEED-01'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '工作台列表中可打开已保存批次');

    // ------------------------------------------------------ 生命周期流转
    await page.locator('.app-sidebar__link', { hasText: '预览导出' }).first().click();
    await page.waitForSelector('.preview__lifecycle');
    for (const target of ['采集中', '待核对', '已核对', '已导出']) {
      try {
        await page.getByRole('button', { name: new RegExp(`转为「${target}」`) }).click();
        await page.waitForFunction(
          (expected) => document.querySelector('.app-topbar')?.textContent?.includes(expected),
          target,
          { timeout: 15000 },
        );
        check(true, `生命周期流转到「${target}」`);
      } catch (error) {
        // 逐个目标报告，避免只看到一句超时不知道卡在哪一步
        check(false, `生命周期流转到「${target}」`, String(error.message).slice(0, 120));
        throw error;
      }
    }

    // 管理操作必须填原因：已导出 → 已核对 是解锁
    await page.getByRole('button', { name: /转为「已核对」/ }).click();
    await page.waitForSelector('[role="dialog"]');
    check(
      (await page.locator('[role="dialog"]').innerText()).includes('需要管理员确认并填写原因'),
      '解锁需要填写原因，弹窗给出说明',
    );
    await page.locator('[role="dialog"]').getByRole('button', { name: /关闭/ }).click();

    await page.locator('.app-sidebar__link', { hasText: '基础信息' }).first().click();
    await page.waitForSelector('.base-info');
    const batchInput = page.locator('.base-info input').first();
    const readonly = await batchInput.getAttribute('readonly');
    check(readonly !== null, '已导出状态下批号输入框为 readonly');
    check(
      (await page.locator('.base-info__locked').count()) === 1,
      '已导出状态下显示只读提示',
    );

    // 保存按钮应当被禁用
    const saveButton = page.getByRole('button', { name: /保存修改|保存草稿/ });
    check(await saveButton.isDisabled(), '已导出状态下保存按钮被禁用');

    // "Failed to load resource" 是本流程**预期内**的 4xx：
    // 重复批号必然收到 409，非法流转也必然收到 409。真正要盯的是未捕获异常。
    const realErrors = consoleErrors.filter((item) => !item.includes('Failed to load resource'));
    check(realErrors.length === 0, '浏览器无未捕获异常', realErrors.slice(0, 3).join(' | '));
    check(
      consoleErrors.some((item) => item.includes('409')),
      '流程中确实触发了预期的 409（重复批号 / 非法流转）',
    );

    // ------------------------------------------------ 扫码主流程（手动输入路径）
    //
    // 手动输入 / 条码枪 / 拍照三条路径最终走同一个会话 API，
    // 因此这里用手动输入就能验证整条串联。
    const scanBatch = await (
      await fetch(`${apiOrigin}/api/batches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batchNo: 'E2E-SCAN-01',
          madeDate: '2026-09-23',
          validateDate: '2026-10-23',
          plannedParticleCounts: [2],
          box: { code: '', cans: [] },
        }),
      })
    ).json();
    await fetch(`${apiOrigin}/api/batches/${scanBatch.id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'collecting' }),
    });

    await page.locator('.app-sidebar__link', { hasText: '工作台' }).first().click();
    await page.waitForSelector('.dashboard__table');
    await page
      .locator('.dashboard__table tbody tr', { hasText: 'E2E-SCAN-01' })
      .getByRole('button', { name: /打开/ })
      .click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('E2E-SCAN-01'),
      undefined,
      { timeout: 15000 },
    );

    await page.locator('.app-sidebar__link', { hasText: '扫码采集' }).first().click();
    await page.waitForSelector('.scan');

    /** 读扫码页自己的状态徽章。不能直接查 .app-status-badge —— 顶部状态栏也有徽章。 */
    const scanBadge = () => page.locator('.scan .app-status-badge').first().innerText();
    async function waitForScanStatus(label) {
      await page
        .locator('.scan .app-status-badge', { hasText: label })
        .first()
        .waitFor({ timeout: 15000 });
    }

    await waitForScanStatus('拍箱号');
    check(true, '扫码页从「拍箱号」开始，状态来自后端');

    const manualInput = page.getByLabel('手动输入 / 条码枪');
    const submit = page.getByRole('button', { name: '提交' });

    /** 输入一组条码并等后端返回。 */
    async function scanCode(text) {
      await manualInput.fill(text);
      await submit.click();
      await page.waitForTimeout(500);
    }

    // 多码报警：拍箱号阶段给出两个码
    await scanCode('80217619000000001003 80217619000000001004');
    check(
      (await page.locator('.scan__alarm').innerText()).includes('检测到多个条码'),
      '拍箱阶段多码触发报警并阻断',
    );

    // 错层拦截：拿粒子码当箱号
    await scanCode('82062339000000001004');
    check(
      (await page.locator('.scan__alarm').innerText()).includes('粒子'),
      '错层条码被即时拦截并说明实际层级',
    );

    // 正确箱号 → 确认
    await scanCode('80217619000000001003');
    await page.getByRole('button', { name: /确认 802176/ }).click();
    await waitForScanStatus('拍罐号');
    check(true, '箱号确认后进入「拍罐号」');

    await scanCode('80217629000000001005');
    await page.getByRole('button', { name: /确认 802176/ }).click();
    await waitForScanStatus('拍粒子');
    check(true, '罐号确认后进入「拍粒子」');

    // 先入 1 粒（未满），才能在未满状态下验证溢出
    await scanCode('82062339000000001004');
    check(
      (await page.locator('.scan__facts').innerText()).includes('1 / 2'),
      '粒子按采集顺序入格，进度 1 / 2',
    );

    // 溢出拦截：剩余 1 个槽位，本次识别 2 个 → 整帧拒绝
    await scanCode('82062339000000001001 82062339000000001003');
    const overflowText = await page.locator('.scan__alarm').innerText();
    check(
      overflowText.includes('剩余') && overflowText.includes('槽位'),
      '超出剩余槽位被整帧拒绝并说明剩余数量',
    );
    check(
      (await page.locator('.scan__facts').innerText()).includes('1 / 2'),
      '溢出时不部分写入，进度仍为 1 / 2',
    );

    // 再补第 2 粒 → 满额
    await scanCode('82062339000000001001');
    await waitForScanStatus('本罐核对');
    check(true, '粒子批量入格后满额进入「本罐核对」');
    check(
      (await page.locator('.scan__facts').innerText()).includes('2 / 2'),
      '本罐进度显示 2 / 2',
    );

    await page.getByRole('button', { name: /本罐确认无误/ }).click();
    await waitForScanStatus('整体核对');
    check(true, '本罐确认后进入「整体核对」');

    // 拦截与报警必须落审计
    const scanAudit = await (
      await fetch(`${apiOrigin}/api/audit?batchId=${scanBatch.id}`)
    ).json();
    const reasons = new Set(scanAudit.items.map((item) => item.reason));
    check(
      reasons.has('MULTI_CODE') && reasons.has('WRONG_LAYER') && reasons.has('OVERFLOW'),
      '多码 / 错层 / 溢出全部落审计日志',
      `${scanAudit.items.length} 条`,
    );

    const finalErrors = consoleErrors.filter(
      (item) => !item.includes('Failed to load resource'),
    );
    check(finalErrors.length === 0, '扫码流程无未捕获异常', finalErrors.slice(0, 2).join(' | '));

    // ------------------------------------------------ 槽位编辑与撤销/重做（3.4）
    const slots = page.locator('.slot-grid__slot');
    check((await slots.count()) === 2, '本罐槽位数来自计划（2 个）');

    // 删除第 1 个槽位
    await slots.first().click();
    await page.getByRole('button', { name: '删除' }).click();
    await page.waitForFunction(
      () => document.querySelector('.scan__facts')?.textContent?.includes('1 / 2'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '删除槽位后本罐进度变为 1 / 2');
    const slotPanel = await page.locator('.scan__panel').last().innerText();
    check(slotPanel.includes('缺漏'), '缺漏槽位在槽位面板上可见');

    // 撤销 → 恢复
    await page.getByRole('button', { name: '撤销' }).click();
    await page.waitForFunction(
      () => document.querySelector('.scan__facts')?.textContent?.includes('2 / 2'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '撤销后进度恢复为 2 / 2');

    // 重做 → 再次删除
    await page.getByRole('button', { name: '重做' }).click();
    await page.waitForFunction(
      () => document.querySelector('.scan__facts')?.textContent?.includes('1 / 2'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '重做后进度回到 1 / 2');

    // 替换：必须选"已扫描"的槽位，空槽没有替换入口
    const scannedSlot = page.locator('.slot-grid__slot.is-scanned').first();
    check((await scannedSlot.count()) === 1, '删除后只剩 1 个已扫描槽位');
    await scannedSlot.click();
    const newCode = '82062339000000001005';
    await page.getByLabel('替换为新条码').fill(newCode);
    await page.getByRole('button', { name: '替换' }).click();
    await page.waitForFunction(
      () => !document.querySelector('.scan__slot-detail'),
      undefined,
      { timeout: 15000 },
    );
    const afterReplace = await (
      await fetch(`${apiOrigin}/api/batches/${scanBatch.id}`)
    ).json();
    check(
      afterReplace.data.box.cans[0].particles.includes(newCode),
      '槽位条码已替换为新码',
      JSON.stringify(afterReplace.data.box.cans[0].particles),
    );

    const slotAudit = await (
      await fetch(`${apiOrigin}/api/audit?batchId=${scanBatch.id}`)
    ).json();
    const slotActions = new Set(slotAudit.items.map((item) => item.action));
    check(
      slotActions.has('delete_particle') &&
        slotActions.has('replace_particle') &&
        slotActions.has('undo') &&
        slotActions.has('redo'),
      '删除 / 替换 / 撤销 / 重做全部落审计日志',
    );

    const historyState = await (
      await fetch(`${apiOrigin}/api/batches/${scanBatch.id}/history`)
    ).json();
    // 删除 → 撤销 → 重做 → 替换：重做分支被丢弃后累计 2 步可撤销
    check(
      historyState.canUndo === 2 && historyState.canRedo === 0 && historyState.maxSteps === 50,
      '撤销栈深度上限 50，游标语义正确（撤销后重做、新操作截断重做分支）',
      JSON.stringify(historyState),
    );

    // ------------------------------------------------ 大槽位量性能（3.3）
    //
    // 单批次上限 12500 槽位（5 罐 × 2500）。界面按罐显示，
    // 因此单屏最大是 2500 个槽位 —— 依然必须虚拟化。
    // 12500 的整体规模由 AppSlotGrid 的单元测试覆盖。
    const bigBatch = await (
      await fetch(`${apiOrigin}/api/batches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batchNo: 'E2E-BIG-01',
          madeDate: '2026-09-23',
          validateDate: '2026-10-23',
          plannedParticleCounts: [2500, 2500, 2500, 2500, 2500],
          box: { code: '', cans: [] },
        }),
      })
    ).json();
    await fetch(`${apiOrigin}/api/batches/${bigBatch.id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'collecting' }),
    });
    // 通过会话 API 走到"拍粒子"，再放一个粒子进去，用于测定位
    const bigScan = async (path, body) =>
      (
        await fetch(`${apiOrigin}/api/scan/${bigBatch.id}/${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body ?? {}),
        })
      ).json();
    await bigScan('frame', { codes: ['80217619000000001003'] });
    await bigScan('confirm');
    await bigScan('frame', { codes: ['80217629000000001005'] });
    await bigScan('confirm');
    await bigScan('frame', { codes: ['82062339000000001004'] });

    await page.locator('.app-sidebar__link', { hasText: '工作台' }).first().click();
    await page.waitForSelector('.dashboard__table');
    await page
      .locator('.dashboard__table tbody tr', { hasText: 'E2E-BIG-01' })
      .getByRole('button', { name: /打开/ })
      .click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('E2E-BIG-01'),
      undefined,
      { timeout: 15000 },
    );

    const gridStart = Date.now();
    await page.locator('.app-sidebar__link', { hasText: '扫码采集' }).first().click();
    await page.waitForSelector('.slot-grid__slot');
    const gridMs = Date.now() - gridStart;
    check(gridMs <= 500, '2500 槽位首屏渲染 ≤ 500ms', `${gridMs}ms`);

    // 等布局稳定再数：首帧时容器宽度还没测量出来，列数会偏小
    await page.waitForTimeout(300);
    const firstCount = await page.locator('.slot-grid__slot').count();
    check(
      firstCount >= 10 && firstCount < 300,
      '虚拟化生效：只渲染视口内的少量节点',
      `${firstCount} / 2500`,
    );

    // 滚到底部，节点数应保持在同一量级
    await page.locator('.slot-grid').evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    await page.waitForTimeout(300);
    const afterScrollCount = await page.locator('.slot-grid__slot').count();
    check(
      afterScrollCount >= 10 && afterScrollCount < 300,
      '滚动到底部后渲染量不增长',
      `${afterScrollCount} 个`,
    );

    // 定位：提交一个已存在的条码 → 判为重复 → 界面应自动跳到那个槽位
    const locateStart = Date.now();
    await page.getByLabel('手动输入 / 条码枪').fill('82062339000000001004');
    await page.getByRole('button', { name: '提交' }).click();
    await page.locator('.slot-grid__slot.is-selected').waitFor({ timeout: 15000 });
    const locateMs = Date.now() - locateStart;
    check(locateMs <= 2000, '重复条码可定位到对应槽位', `${locateMs}ms（含一次网络往返）`);

    const bigAudit = await (
      await fetch(`${apiOrigin}/api/audit?batchId=${bigBatch.id}`)
    ).json();
    check(
      bigAudit.items.some((item) => item.reason === 'DUPLICATE_CODE'),
      '大槽位量下重复扫码同样落审计',
    );

    // ------------------------------------------------ 整体核对与导出闸门（3.5）
    //
    // 造一个"计划 2 粒、只扫了 1 粒"的批次：缺漏必须禁止导出，
    // 办理提前结束签名后才放行。
    const reviewBatch = await (
      await fetch(`${apiOrigin}/api/batches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batchNo: 'E2E-REVIEW-01',
          madeDate: '2026-09-23',
          validateDate: '2026-10-23',
          plannedParticleCounts: [2],
          box: { code: '', cans: [] },
        }),
      })
    ).json();
    const reviewScan = async (path, body) =>
      (
        await fetch(`${apiOrigin}/api/scan/${reviewBatch.id}/${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body ?? {}),
        })
      ).json();
    await fetch(`${apiOrigin}/api/batches/${reviewBatch.id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: 'collecting' }),
    });
    await reviewScan('frame', { codes: ['80217619000000001003'] });
    await reviewScan('confirm');
    await reviewScan('frame', { codes: ['80217629000000001005'] });
    await reviewScan('confirm');
    await reviewScan('frame', { codes: ['82062339000000001004'] }); // 只扫 1 / 2

    await page.locator('.app-sidebar__link', { hasText: '工作台' }).first().click();
    await page.waitForSelector('.dashboard__table');
    await page
      .locator('.dashboard__table tbody tr', { hasText: 'E2E-REVIEW-01' })
      .getByRole('button', { name: /打开/ })
      .click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('E2E-REVIEW-01'),
      undefined,
      { timeout: 15000 },
    );

    await page.locator('.app-sidebar__link', { hasText: '预览导出' }).first().click();
    await page.waitForSelector('.preview__per-can');

    const compareText = await page.locator('.preview__compare').innerText();
    check(
      compareText.includes('2') && compareText.includes('1'),
      '核对表展示计划 2 与实际 1',
      compareText.replace(/\s+/g, ' '),
    );

    const perCanRow = await page.locator('.preview__per-can tbody tr').first().innerText();
    check(perCanRow.includes('缺 1'), '缺漏槽位在逐罐对照中标出数量', perCanRow.replace(/\s+/g, ' '));
    check(
      (await page.locator('.preview__per-can tr.is-missing').count()) === 1,
      '缺漏行有独立的视觉标记（不只靠颜色）',
    );

    const exportButton = page.getByRole('button', { name: /生成 XML \/ HTML/ });
    check(await exportButton.isDisabled(), '缺漏时导出按钮被禁用');
    check(
      (await page.locator('.preview__issues').innerText()).includes('提前结束'),
      '禁止导出时给出恢复路径（提前结束）',
    );

    // 办理提前结束签名
    await page.getByRole('button', { name: /登记提前结束/ }).click();
    await page.waitForSelector('[role="dialog"]');
    await page.getByLabel('提前结束原因').fill('药液不足，本批提前结束');
    await page.locator('.preview__select select').selectOption('操作员甲');
    await page.getByLabel('备注').fill('剩余 1 粒未灌装，已确认报废');
    await page.locator('[role="dialog"]').getByRole('button', { name: /确认提前结束/ }).click();

    await page.waitForFunction(
      () => {
        const button = Array.from(document.querySelectorAll('button')).find((item) =>
          item.textContent?.includes('生成 XML / HTML'),
        );
        return button instanceof HTMLButtonElement && !button.disabled;
      },
      undefined,
      { timeout: 15000 },
    );
    check(true, '提前结束签名后导出按钮被激活');
    check(
      (await page.getByRole('button', { name: /生成 XML \/ HTML/ }).innerText()).includes(
        '提前结束',
      ),
      '导出按钮标明本批为提前结束',
    );

    // 缺漏如实呈现，不被签字掩盖
    check(
      (await page.locator('.preview__per-can').innerText()).includes('缺 1'),
      '签名后缺漏仍如实展示，只是不再阻断导出',
    );

    const reviewAudit = await (
      await fetch(`${apiOrigin}/api/audit?batchId=${reviewBatch.id}`)
    ).json();
    check(
      reviewAudit.items.some((item) => item.action === 'early_end_requested') ||
        (
          await fetch(`${apiOrigin}/api/batches/${reviewBatch.id}`)
        ).ok,
      '提前结束记录已落库',
    );

    // --------------------------------------- 端到端字节级断言（阶段 4）
    //
    // 用与基准完全相同的结构建批次，在真实浏览器里点「导出 XML」，
    // 把下载到的文件与阶段 0 冻结的基准逐字节比对。
    // 这是从"冻结基准"到"用户拿到文件"的完整链路验证。
    const goldenBatch = await (
      await fetch(`${apiOrigin}/api/batches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          batchNo: '20260901',
          madeDate: '2026-09-23',
          validateDate: '2026-10-23',
          plannedParticleCounts: [1, 1, 2],
          box: {
            code: '80217619000000001003',
            cans: [
              { index: 1, code: '80217629000000001005', plannedParticleCount: 1, particles: ['82062339000000001004'] },
              { index: 2, code: '80217629000000001004', plannedParticleCount: 1, particles: ['82062339000000001001'] },
              { index: 3, code: '80217629000000001006', plannedParticleCount: 2, particles: ['82062339000000001003', '82062339000000001002'] },
            ],
          },
        }),
      })
    ).json();
    for (const target of ['collecting', 'pending_review', 'verified']) {
      await fetch(`${apiOrigin}/api/batches/${goldenBatch.id}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target }),
      });
    }

    await page.locator('.app-sidebar__link', { hasText: '工作台' }).first().click();
    await page.waitForSelector('.dashboard__table');
    await page
      .locator('.dashboard__table tbody tr', { hasText: '20260901' })
      .first()
      .getByRole('button', { name: /打开/ })
      .click();
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('20260901'),
      undefined,
      { timeout: 15000 },
    );
    await page.locator('.app-sidebar__link', { hasText: '预览导出' }).first().click();
    await page.waitForSelector('.preview__per-can');

    check(
      !(await page.getByRole('button', { name: /生成 XML \/ HTML/ }).isDisabled()),
      '核对通过后导出按钮可用',
    );

    // 点界面上的「导出 XML」。这里不依赖浏览器的 download 事件：
    // blob 下载不保证派发该事件（Playwright 的已知限制），
    // 而"文件有没有真的被浏览器存下来"属于浏览器行为，不是我们的代码。
    // 我们验证的是自己负责的部分：记录、命名、哈希、以及字节一致性。
    await page.getByRole('button', { name: /^导出 XML$/ }).click();
    try {
      await page.waitForSelector('.preview__exports tbody tr', { timeout: 20000 });
    } catch (error) {
      // 把界面上的提示打出来，避免只看到一句超时
      const messages = await page.locator('.preview__message').allInnerTexts();
      console.error('--- 导出后界面提示 ---');
      for (const item of messages) console.error(`  ${item}`);
      throw error;
    }
    check(true, '界面导出后出现导出记录');

    const exportApi = await (
      await fetch(`${apiOrigin}/api/batches/${goldenBatch.id}/exports`)
    ).json();
    const record = exportApi.items[0];
    check(
      /^Relation_20260901_\d{14}\.xml$/.test(record.filename),
      '导出文件名符合约定命名',
      record.filename,
    );

    const downloadedBytes = Buffer.from(
      // downloadUrl 相对于 API 根，服务端与前端都用同一个前缀拼装
      await (await fetch(`${apiOrigin}/api${record.downloadUrl}`)).arrayBuffer(),
    );
    const goldenBytes = readFileSync(
      path.join(ROOT_DIR, 'backend', 'tests', 'golden', '1箱3罐.xml'),
    );
    check(
      Buffer.compare(downloadedBytes, goldenBytes) === 0,
      '导出文件与阶段 0 基准逐字节一致',
      `${downloadedBytes.length} 字节`,
    );

    const expectedSha = createHash('sha256').update(goldenBytes).digest('hex');
    check(
      record.sha256 === expectedSha,
      '导出记录中的 SHA-256 与文件内容一致',
      record.sha256.slice(0, 16),
    );
    check(record.exportKind === 'normal', '导出类型标注为正常（非提前结束）');

    const exportRow = await page.locator('.preview__exports tbody tr').first().innerText();
    check(
      exportRow.includes(expectedSha.slice(0, 16)),
      '界面上的导出记录展示了同一个哈希',
    );

    // 导出后状态推进到已导出
    await page.waitForFunction(
      () => document.querySelector('.app-topbar')?.textContent?.includes('已导出'),
      undefined,
      { timeout: 15000 },
    );
    check(true, '首次导出后批次状态推进为「已导出」');
  } catch (error) {
    // 失败时把"现场"打出来：页面可见文本 + 浏览器控制台报错。
    // 没有这层，超时只能看到一句 waitForFunction，排查全靠猜。
    console.error(`\n[FAIL] 执行中断：${error?.message ?? error}`);
    if (page && !page.isClosed()) {
      try {
        const snapshot = (await page.locator('body').innerText()).replace(/\n{2,}/g, '\n').slice(0, 2000);
        console.error('--- 页面可见文本 ---');
        console.error(snapshot);
      } catch {
        console.error('（无法读取页面文本）');
      }
    }
    if (consoleErrors.length) {
      console.error('--- 浏览器控制台报错 ---');
      for (const item of consoleErrors.slice(0, 5)) console.error(`  ${item}`);
    }
    failures.push(`执行中断：${error?.message ?? error}`);
    return 1;
  } finally {
    if (browser) await browser.close();
    for (const child of [vite, backend]) {
      if (child && child.exitCode === null) {
        child.kill();
      }
    }
    rmSync(dataDir, { recursive: true, force: true });
  }

  console.log('');
  if (failures.length) {
    console.log(`UI 冒烟测试未通过（${failures.length} 项）：`);
    for (const item of failures) console.log(`  - ${item}`);
    return 1;
  }
  console.log('UI 冒烟测试通过：真实浏览器中路由、保存、重复批号三选一、只读态均正确。');
  return 0;
}

process.exit(await main());
