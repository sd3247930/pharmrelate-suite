/**
 * Electron 桌面壳。
 *
 * 职责只有三件：拉起 Python 本地服务、把服务地址交给前端、退出时回收进程。
 * 业务逻辑全部在 backend/，桌面壳不做任何数据处理。
 *
 * 附带 `--smoke-test` 模式：启动壳、等后端就绪、校验关键接口，然后退出。
 * 这样"桌面壳能不能拉起后端"就成了一项可自动验证的证据，而不靠肉眼确认。
 */

const { BrowserWindow, app, dialog, ipcMain } = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const {
  freePort,
  resolveBackendDir,
  resolveFrontendDir,
  startSidecar,
  waitForHealth,
} = require('./sidecar.cjs');

const SMOKE_TEST = process.argv.includes('--smoke-test');
const DEV_SERVER_URL = process.env.PHARMRELATE_DEV_URL ?? 'http://localhost:5173';

// 默认 app.getName() 取的是 package.json 的 name（pharmrelate-multi-desktop），
// 会让日志落到 %APPDATA%\pharmrelate-multi-desktop\。显式设成产品名，
// 与数据库目录（%LOCALAPPDATA%\PharmRelate Multi\）和文档口径一致。
app.setName('PharmRelate Multi');

const BACKEND_READY_TIMEOUT_MS = 30000;
/** ready-to-show 迟迟不来时的兜底：宁可先显示出来，也不要一个看不见的窗口。 */
const WINDOW_SHOW_FALLBACK_MS = 10000;
const BACKEND_TAIL_LINES = 40;

let sidecar = null;
let baseUrl = '';
/** 启动失败原因；非空时窗口展示错误页而不是白屏。 */
let bootFailure = '';
const backendTail = [];

/** 桌面壳日志：%APPDATA%\PharmRelate Multi\logs\desktop.log */
function desktopLogPath() {
  return path.join(app.getPath('userData'), 'logs', 'desktop.log');
}

function log(line) {
  console.log(`[shell] ${line}`);
  try {
    const target = desktopLogPath();
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.appendFileSync(target, `[${new Date().toISOString()}] ${line}\n`, 'utf8');
  } catch {
    // 日志写不进去不能反过来影响启动
  }
}

function collectBackendOutput(chunk) {
  for (const line of chunk.split(/\r?\n/)) {
    if (!line.trim()) continue;
    backendTail.push(line);
  }
  if (backendTail.length > BACKEND_TAIL_LINES) {
    backendTail.splice(0, backendTail.length - BACKEND_TAIL_LINES);
  }
}

function backendTailText() {
  return backendTail.length ? backendTail.join('\n') : '（后端没有输出）';
}

/** 后端根地址：把 `/api` 去掉，用于加载前端页面。 */
function appOrigin() {
  return baseUrl.replace(/\/api$/, '');
}

function stopSidecar() {
  if (!sidecar) return;
  const { child } = sidecar;
  sidecar = null;
  if (!child.killed && child.exitCode === null) {
    child.kill();
  }
}

async function bootBackend() {
  const backendDir = resolveBackendDir();
  const frontendDir = resolveFrontendDir();
  const port = await freePort();
  sidecar = startSidecar(port, backendDir, frontendDir, { onOutput: collectBackendOutput });
  baseUrl = sidecar.baseUrl;
  log(`本地服务地址 ${baseUrl}（backend=${backendDir}）`);
  log(`前端目录 ${frontendDir}（存在=${fs.existsSync(frontendDir)}）`);

  const health = await waitForHealth(baseUrl, BACKEND_READY_TIMEOUT_MS);
  if (!health) {
    bootFailure =
      `本地服务在 ${BACKEND_READY_TIMEOUT_MS / 1000} 秒内没有就绪。\n` +
      `后端目录：${backendDir}\n\n最近的后端输出：\n${backendTailText()}`;
    log(`本地服务未能就绪\n${bootFailure}`);
    return null;
  }
  log(`本地服务就绪：v${health.version} · Python ${health.python} · 基准一致=${health.goldenOk}`);
  if (!health.goldenOk) {
    log('基准一致性为 false：/api/health 虽返回 200，但黄金基准未能往返一致');
  }
  return health;
}

async function runSmokeTest() {
  const health = await bootBackend();
  if (!health) return 1;

  let failed = 0;
  const check = (ok, label, extra = '') => {
    console.log(`[${ok ? ' OK ' : 'FAIL'}] ${label}${extra ? `  ${extra}` : ''}`);
    if (!ok) failed += 1;
  };

  check(health.status === 'ok', '后端健康检查通过', `v${health.version}`);
  check(Boolean(health.goldenOk), '黄金基准往返一致');

  const listing = await (await fetch(`${baseUrl}/golden`)).json();
  check(listing.allOk === true, 'GET /golden 全部往返通过', `${listing.items.length} 个文件`);

  const preview = await (
    await fetch(`${baseUrl}/xml/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        batchNo: '20260901',
        madeDate: '2026-09-23',
        validateDate: '2026-10-23',
        box: {
          code: '80217619000000001003',
          cans: [
            { index: 1, code: '80217629000000001005', plannedParticleCount: 1, particles: ['82062339000000001004'] },
            { index: 2, code: '80217629000000001004', plannedParticleCount: 1, particles: ['82062339000000001001'] },
            {
              index: 3,
              code: '80217629000000001006',
              plannedParticleCount: 2,
              particles: ['82062339000000001003', '82062339000000001002'],
            },
          ],
        },
      }),
    })
  ).json();
  const golden = await (await fetch(`${baseUrl}/golden/${encodeURIComponent('1箱3罐.xml')}/xml`)).text();
  check(preview.xml === golden, '经由桌面壳生成的 XML 与基准逐字符一致');

  console.log('');
  if (failed) {
    console.log(`桌面壳冒烟测试未通过（${failed} 项）`);
    return 1;
  }
  console.log('桌面壳冒烟测试通过：Electron 能拉起 Python 服务并完成端到端调用。');
  return 0;
}

/**
 * 渲染层诊断：白屏这类问题在打包态没有控制台可看，
 * 必须把加载失败与渲染进程报错记进日志文件。
 */
function attachDiagnostics(window) {
  const contents = window.webContents;

  contents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    log(`界面加载失败：${errorDescription}（${errorCode}） ${validatedURL}`);
  });

  contents.on('render-process-gone', (_event, details) => {
    log(`渲染进程退出：${details.reason}`);
  });

  contents.on('console-message', (...args) => {
    // Electron 33 是 (event, level, message, line, sourceId)；新版是单个 details 对象
    const details = args[0] && typeof args[0] === 'object' && 'message' in args[0] ? args[0] : null;
    const level = details ? details.level : args[1];
    const message = details ? details.message : args[2];
    const source = details ? details.sourceId : args[4];
    const numeric = typeof level === 'number' ? level : 0;
    if (numeric < 2) return; // 只要警告与错误
    log(`渲染进程${numeric >= 3 ? '错误' : '警告'}：${message}${source ? ` (${source})` : ''}`);
  });
}

function showBootFailure(window, message) {
  // 用异步的 showMessageBox 而不是 showErrorBox：后者是模态阻塞的，
  // 无人值守（自动化检查）时会把整个进程挂住 —— 实测过一次，
  // 打包态冒烟因此卡死到超时。错误页本身已经把原因写清楚了。
  dialog
    .showMessageBox({
      type: 'error',
      title: '籽关通：本地服务启动失败',
      message: '本地服务启动失败，界面无法加载。',
      detail: message,
      buttons: ['知道了'],
    })
    .catch(() => {});
  window
    .loadFile(path.join(__dirname, 'error.html'))
    .then(() => window.webContents.executeJavaScript(`window.__showBootError(${JSON.stringify(message)});`))
    .catch((error) => log(`错误页加载失败：${error.message}`));
}

async function loadFrontend(window) {
  // 开发态优先连 Vite dev server（该源在 CORS 白名单内）
  if (process.env.PHARMRELATE_DEV_URL || !app.isPackaged) {
    try {
      await window.loadURL(DEV_SERVER_URL);
      log(`界面已加载：${DEV_SERVER_URL}`);
      return;
    } catch (error) {
      log(`连不上前端开发服务器 ${DEV_SERVER_URL}（${error.message}），改由本地服务托管前端`);
    }
  }

  if (bootFailure) {
    showBootFailure(window, bootFailure);
    return;
  }

  // 打包态：前端由本地服务托管，与 /api 同源 —— 没有 file:// 绝对路径 404，也没有跨源拦截
  await window.loadURL(`${appOrigin()}/`);
  log(`界面已加载：${appOrigin()}/`);
}

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: '#f1f4f6',
    title: '籽关通 (PharmRelate Multi)',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  attachDiagnostics(window);

  const showFallback = setTimeout(() => {
    if (!window.isDestroyed() && !window.isVisible()) {
      log('窗口超过 10 秒仍未就绪，先显示出来（此时界面可能尚未渲染）');
      window.show();
    }
  }, WINDOW_SHOW_FALLBACK_MS);

  window.once('ready-to-show', () => {
    clearTimeout(showFallback);
    window.show();
  });
  window.on('closed', () => clearTimeout(showFallback));

  loadFrontend(window).catch((error) => log(`界面加载出错：${error.message}`));

  return window;
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const [window] = BrowserWindow.getAllWindows();
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });

  app.whenReady().then(async () => {
    ipcMain.handle('pharmrelate:api-base-url', () => baseUrl);

    if (SMOKE_TEST) {
      const code = await runSmokeTest();
      stopSidecar();
      app.exit(code);
      return;
    }

    await bootBackend();
    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    stopSidecar();
    if (process.platform !== 'darwin') app.quit();
  });

  app.on('before-quit', stopSidecar);
  app.on('will-quit', stopSidecar);
}
