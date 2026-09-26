/**
 * Python 本地服务（FastAPI）进程管理。
 *
 * 与 Tauri 版保持同一套解析顺序，保证两条壳实现可以互换：
 *   1. 环境变量 PHARMRELATE_BACKEND_DIR / PHARMRELATE_PYTHON
 *   2. 可执行文件同级的 backend/（打包态）
 *   3. 源码仓库中的 backend/（开发态）
 */

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

/** 与 backend/app/main.py 的 FRONTEND_DIR_ENV 必须一致。 */
const FRONTEND_DIR_ENV = 'PHARMRELATE_FRONTEND_DIR';

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

function isBackendDir(candidate) {
  return Boolean(candidate) && fs.existsSync(path.join(candidate, 'app', 'main.py'));
}

function resolveBackendDir() {
  const fromEnv = process.env.PHARMRELATE_BACKEND_DIR;
  if (isBackendDir(fromEnv)) return fromEnv;

  const besideExecutable = path.join(path.dirname(process.execPath), 'backend');
  if (isBackendDir(besideExecutable)) return besideExecutable;

  return path.resolve(__dirname, '..', '..', 'backend');
}

function resolvePython(backendDir) {
  const fromEnv = process.env.PHARMRELATE_PYTHON;
  if (fromEnv && fromEnv.trim()) return fromEnv;

  const venv = path.join(backendDir, '.venv', 'Scripts', 'python.exe');
  if (fs.existsSync(venv)) return venv;

  return process.platform === 'win32' ? 'python' : 'python3';
}

function isFrontendDir(candidate) {
  return Boolean(candidate) && fs.existsSync(path.join(candidate, 'index.html'));
}

/**
 * 前端产物目录，解析顺序与后端目录一致。
 *
 * 起后端时通过 PHARMRELATE_FRONTEND_DIR 传给它，由服务端托管前端，
 * Electron 就能 loadURL(http) 而不是 loadFile(file://)：
 * 同源 → 既没有绝对路径 404（白屏），也没有跨源拦截（CORS）。
 */
function resolveFrontendDir() {
  const fromEnv = process.env.PHARMRELATE_FRONTEND_DIR;
  if (isFrontendDir(fromEnv)) return fromEnv;

  const besideExecutable = path.join(process.resourcesPath, 'frontend', 'dist');
  if (isFrontendDir(besideExecutable)) return besideExecutable;

  return path.resolve(__dirname, '..', '..', 'frontend', 'dist');
}

/** 启动 uvicorn；返回 { child, baseUrl }。 */
function startSidecar(
  port,
  backendDir = resolveBackendDir(),
  frontendDir = resolveFrontendDir(),
  options = {},
) {
  const python = resolvePython(backendDir);
  const onOutput = typeof options.onOutput === 'function' ? options.onOutput : null;
  const child = spawn(
    python,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: backendDir,
      // 不继承 stdio：Electron 主进程的管道一旦关闭，子进程会收到 EPIPE
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: {
        ...process.env,
        // 服务端据此挂载静态目录；目录不存在时服务端会自行跳过并记日志
        [FRONTEND_DIR_ENV]: frontendDir,
      },
    },
  );

  const forward = (stream, chunk) => {
    stream.write(`[backend] ${chunk}`);
    // 打包态双击启动时没有控制台，后端输出必须能被壳记进日志文件，
    // 否则"服务起不来"在现场只能看到一个白窗口。
    if (onOutput) onOutput(String(chunk));
  };

  child.stdout.on('data', (chunk) => forward(process.stdout, chunk));
  child.stderr.on('data', (chunk) => forward(process.stderr, chunk));
  child.on('error', (error) => console.error('[backend] 启动失败：', error.message));
  child.on('exit', (code) => console.log(`[backend] 已退出，code=${code}`));

  return { child, baseUrl: `http://127.0.0.1:${port}/api` };
}

async function waitForHealth(baseUrl, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) return await response.json();
    } catch {
      // 还没起来，继续等
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return null;
}

module.exports = {
  FRONTEND_DIR_ENV,
  freePort,
  resolveBackendDir,
  resolveFrontendDir,
  resolvePython,
  startSidecar,
  waitForHealth,
};
