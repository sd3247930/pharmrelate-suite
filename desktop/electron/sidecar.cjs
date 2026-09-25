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

/** 启动 uvicorn；返回 { child, baseUrl }。 */
function startSidecar(port, backendDir = resolveBackendDir()) {
  const python = resolvePython(backendDir);
  const child = spawn(
    python,
    ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
    {
      cwd: backendDir,
      // 不继承 stdio：Electron 主进程的管道一旦关闭，子进程会收到 EPIPE
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  );

  child.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`));
  child.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`));
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

module.exports = { freePort, resolveBackendDir, resolvePython, startSidecar, waitForHealth };
