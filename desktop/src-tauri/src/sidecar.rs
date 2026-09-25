//! Python 本地服务（FastAPI）进程管理。
//!
//! 桌面壳启动时拉起 uvicorn，退出时回收，避免留下孤儿进程占住端口。
//!
//! 端口动态分配：车间里可能同时开着浏览器版或第二个实例，写死端口会互相抢占。
//! 解析顺序（先具体后通用）：
//!   1. 环境变量 PHARMRELATE_BACKEND_DIR / PHARMRELATE_PYTHON
//!   2. 可执行文件同级的 backend/ 与 .venv/（打包态）
//!   3. 源码仓库中的 backend/（开发态）

use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

pub struct SidecarState {
    pub child: Mutex<Option<Child>>,
    pub base_url: String,
}

/// 让操作系统分配一个空闲端口，避免端口冲突。
pub fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn executable_dir() -> Option<PathBuf> {
    std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
}

/// 定位仓库中的 backend 目录（开发态使用编译期路径）。
fn dev_backend_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("backend")
}

pub fn resolve_backend_dir() -> PathBuf {
    if let Ok(value) = std::env::var("PHARMRELATE_BACKEND_DIR") {
        let candidate = PathBuf::from(value);
        if candidate.join("app").join("main.py").is_file() {
            return candidate;
        }
    }
    if let Some(dir) = executable_dir() {
        let candidate = dir.join("backend");
        if candidate.join("app").join("main.py").is_file() {
            return candidate;
        }
    }
    dev_backend_dir()
}

/// 优先使用项目自带的虚拟环境解释器，其次才退回系统 Python。
fn resolve_python(backend_dir: &Path) -> String {
    if let Ok(value) = std::env::var("PHARMRELATE_PYTHON") {
        if !value.trim().is_empty() {
            return value;
        }
    }
    let venv = backend_dir.join(".venv").join("Scripts").join("python.exe");
    if venv.is_file() {
        return venv.to_string_lossy().to_string();
    }
    "python".to_string()
}

/// 启动 uvicorn，返回 (子进程, API 根地址)。
pub fn spawn(backend_dir: &Path, port: u16) -> std::io::Result<Child> {
    let python = resolve_python(backend_dir);
    let mut command = Command::new(python);
    command
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .current_dir(backend_dir)
        // 打包态没有控制台，必须吞掉输出，否则 Windows 上会弹黑框
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .stdin(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    command.spawn()
}

pub fn api_base(port: u16) -> String {
    format!("http://127.0.0.1:{port}/api")
}
