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
import { mkdtempSync, rmSync } from 'node:fs';
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
