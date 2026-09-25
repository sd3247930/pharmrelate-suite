/**
 * Electron 桌面壳。
 *
 * 职责只有三件：拉起 Python 本地服务、把服务地址交给前端、退出时回收进程。
 * 业务逻辑全部在 backend/，桌面壳不做任何数据处理。
 *
 * 附带 `--smoke-test` 模式：启动壳、等后端就绪、校验关键接口，然后退出。
 * 这样"桌面壳能不能拉起后端"就成了一项可自动验证的证据，而不靠肉眼确认。
 */

const { BrowserWindow, app, ipcMain } = require('electron');
const path = require('node:path');

const { freePort, resolveBackendDir, startSidecar, waitForHealth } = require('./sidecar.cjs');

const SMOKE_TEST = process.argv.includes('--smoke-test');
const DEV_SERVER_URL = process.env.PHARMRELATE_DEV_URL ?? 'http://localhost:5173';

let sidecar = null;
let baseUrl = '';

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
  const port = await freePort();
  sidecar = startSidecar(port, backendDir);
  baseUrl = sidecar.baseUrl;
  console.log(`[shell] 本地服务地址 ${baseUrl}（backend=${backendDir}）`);

  const health = await waitForHealth(baseUrl);
  if (!health) {
    console.error('[shell] 本地服务未能在超时内就绪');
    return null;
  }
  console.log(`[shell] 本地服务就绪：v${health.version} · Python ${health.python} · 基准一致=${health.goldenOk}`);
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

  window.once('ready-to-show', () => window.show());

  if (process.env.PHARMRELATE_DEV_URL || !app.isPackaged) {
    window.loadURL(DEV_SERVER_URL).catch(() => window.loadFile(path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html')));
  } else {
    window.loadFile(path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html'));
  }

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
