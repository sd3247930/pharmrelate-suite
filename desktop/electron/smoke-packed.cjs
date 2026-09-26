/**
 * 打包态 UI 冒烟：启动真实安装产物，断言界面真的渲染出来、后端真的可用。

 * 为什么必须有这一条：原有 11 项检查里没有一项会打开窗口 ——
 * `npm run smoke`（桌面壳冒烟）只校验后端接口，从不创建 BrowserWindow；
 * 前端 E2E 跑的是 Vite dev server，不是打包产物。
 * 于是"打包后白屏"和"打包漏文件导致 /api/health 500"都能悄悄溜到交付。
 * 本条检查就是堵这个洞：A（绝对路径白屏）、B（基准漏打包）、C（跨源拦截）
 * 任何一条复发，它都会失败。

 * 前置：先 `cd desktop && npm run dist`
 * 用法：`node electron/smoke-packed.cjs`（或 `npm run smoke:packed`）
 */

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..');
const APP_DIR = path.join(ROOT, 'desktop', 'release', 'win-unpacked');
const EXE = path.join(APP_DIR, 'PharmRelate Multi.exe');
const ARTIFACT_DIR = path.join(ROOT, 'desktop', 'artifacts', 'smoke-packed');

const failures = [];
const consoleLines = [];

/** 失败已经上报过，只是需要跳到收尾。 */
class AlreadyReported extends Error {}

function report(ok, label, extra = '') {
  console.log(`[${ok ? ' OK ' : 'FAIL'}] ${label}${extra ? `  ${extra}` : ''}`);
  if (!ok) failures.push(label);
}

/** playwright 装在 frontend/node_modules，桌面壳自己没装 */
function loadPlaywright() {
  try {
    return require('playwright');
  } catch {
    return require(require.resolve('playwright', { paths: [path.join(ROOT, 'frontend')] }));
  }
}

/** 单实例锁：若已有一个实例在跑，新实例会静默退出，表现为"连不上界面"。 */
function assertNoRunningInstance() {
  if (process.platform !== 'win32') return true;
  try {
    const output = execFileSync('tasklist', ['/FI', 'IMAGENAME eq PharmRelate Multi.exe', '/NH'], {
      encoding: 'utf8',
    });
    if (output.includes('PharmRelate Multi.exe')) {
      report(false, '没有已运行的实例', '检测到 PharmRelate Multi.exe 正在运行，请先关闭它再跑本检查');
      return false;
    }
  } catch {
    // tasklist 不可用时不做拦截，交给后面的启动失败兜底
  }
  return true;
}

function writeArtifacts(details) {
  try {
    fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(ARTIFACT_DIR, 'failure.txt'),
      [
        `检查时间：${new Date().toISOString()}`,
        `未通过项：${failures.join('、') || '（无）'}`,
        '',
        '=== 详情 ===',
        JSON.stringify(details, null, 2),
        '',
        '=== 渲染进程控制台 ===',
        consoleLines.join('\n') || '（无输出）',
      ].join('\n'),
      'utf8',
    );
    console.log(`已写出失败详情：${path.join(ARTIFACT_DIR, 'failure.txt')}`);
  } catch (error) {
    console.error(`失败详情写入失败：${error.message}`);
  }
}

/** 收尾：正常关不掉（例如启动失败时弹了模态框）就按进程树结束。 */
async function closeApp(app) {
  const child = app.process();
  const pid = child ? child.pid : null;
  try {
    await Promise.race([
      app.close(),
      new Promise((_resolve, reject) => setTimeout(() => reject(new Error('close 超时')), 8000)),
    ]);
    return;
  } catch {
    if (!pid || process.platform !== 'win32') return;
    try {
      execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
      console.log(`已强制结束未退出的实例（pid ${pid}）`);
    } catch {
      // 已经退出了
    }
  }
}

async function main() {
  if (!fs.existsSync(EXE)) {
    console.error(`找不到打包产物：${EXE}`);
    console.error('请先执行：cd desktop && npm run dist');
    process.exit(1);
  }

  if (!assertNoRunningInstance()) {
    process.exit(1);
  }

  const { _electron: electron } = loadPlaywright();
  let app = null;
  let page = null;
  const details = {};

  try {
    app = await electron.launch({ executablePath: EXE, timeout: 60000 });
    // 正常启动约 2 秒。启动失败时壳要先等后端超时（30 秒）才开窗，
    // 所以这里的超时必须比它长，否则只会得到一个笼统的"等待窗口超时"，
    // 拿不到"具体是哪一步坏了"。
    page = await app.firstWindow({ timeout: 75000 });

    page.on('console', (message) => consoleLines.push(`[${message.type()}] ${message.text()}`));
    page.on('pageerror', (error) => consoleLines.push(`[pageerror] ${error.message}`));

    // 0. 先认一下是不是"启动失败页" —— 若是，直接给出确切原因，不必等 30 秒超时
    const boot = await page.evaluate(() => ({
      hasApp: Boolean(document.getElementById('app')),
      title: document.title,
      detail: document.getElementById('detail') ? document.getElementById('detail').textContent : '',
    }));
    details.pageTitle = boot.title;
    if (!boot.hasApp) {
      // 主进程是在 loadFile 之后才注入详情的，稍等一下再取，
      // 否则留档里只剩"（未提供详细信息）"，等于白记。
      const detail = await page
        .waitForFunction(
          () => {
            const el = document.getElementById('detail');
            const text = el ? el.textContent : '';
            return text && !text.startsWith('（未提供') ? text : false;
          },
          null,
          { timeout: 5000 },
        )
        .then((handle) => handle.jsonValue())
        .catch(() => boot.detail);
      details.bootErrorPage = detail;
      report(false, '界面正常渲染（加载到的是启动失败页）', boot.title);
      throw new AlreadyReported('加载到启动失败页');
    }

    // 1. 界面必须渲染出内容（白屏时 #app 长度为 0）
    await page.waitForFunction(
      () => document.getElementById('app') && document.getElementById('app').innerHTML.length > 1000,
      null,
      { timeout: 30000 },
    );
    details.url = page.url();
    details.appHtmlLength = await page.evaluate(
      () => document.getElementById('app').innerHTML.length,
    );
    // 打包态必须由本地服务托管（http），不是 file:// —— file:// 正是白屏的老路
    report(details.url.startsWith('http://127.0.0.1:'), '界面经本地服务以 http 加载', details.url);

    const topbar = await page.locator('.app-topbar').innerText();
    details.topbar = topbar.replace(/\s+/g, ' ').trim();
    report(/本地服务[\s\S]*v\d+\.\d+\.\d+/.test(details.topbar), '顶栏显示本地服务版本', details.topbar);
    report(details.topbar.includes('字节级一致'), '顶栏显示黄金基准字节级一致');

    // 2. 后端接口真的能用（打包漏基准文件时这里会 500）
    const health = await page.evaluate(async () => {
      const response = await fetch('/api/health');
      return { status: response.status, body: await response.json() };
    });
    details.healthStatus = health.status;
    details.healthBody = {
      status: health.body.status,
      version: health.body.version,
      goldenOk: health.body.goldenOk,
      goldenFiles: (health.body.golden || []).length,
    };
    report(health.status === 200, 'GET /api/health 返回 200', String(health.status));
    report(health.body.goldenOk === true, '黄金基准往返一致');
    report((health.body.golden || []).length === 2, '基准文件数量为 2', String((health.body.golden || []).length));
  } catch (error) {
    if (!(error instanceof AlreadyReported)) {
      report(false, '打包态界面可启动', error.message);
    }
    details.error = error.message;
  }

  if (failures.length > 0 && page) {
    try {
      fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
      const shot = path.join(ARTIFACT_DIR, 'failure.png');
      await page.screenshot({ path: shot });
      console.log(`已写出截图：${shot}`);
    } catch (error) {
      console.error(`截图失败：${error.message}`);
    }
  }

  if (app) {
    await closeApp(app);
  }

  console.log('');
  if (failures.length > 0) {
    writeArtifacts(details);
    console.error(`打包态 UI 冒烟未通过（${failures.length} 项）：${failures.join('、')}`);
    process.exit(1);
  }
  console.log('打包态 UI 冒烟通过：真实安装产物能渲染界面，且后端可用。');
}

main().catch((error) => {
  console.error(`执行异常：${error.stack || error.message}`);
  process.exit(1);
});
