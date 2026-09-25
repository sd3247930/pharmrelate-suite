//! 籽关通 (PharmRelate Multi) 桌面壳。
//!
//! 职责只有三件：拉起 Python 本地服务、把服务地址交给前端、退出时回收进程。
//! 业务逻辑全部在 backend/，桌面壳不做任何数据处理。

mod sidecar;

use std::sync::Mutex;

use sidecar::SidecarState;
use tauri::Manager;

/// 前端启动时调用，拿到实际分配的 API 根地址。
#[tauri::command]
fn api_base_url(state: tauri::State<'_, SidecarState>) -> String {
    state.base_url.clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let backend_dir = sidecar::resolve_backend_dir();
            let port = sidecar::free_port().unwrap_or(17800);
            let base_url = sidecar::api_base(port);

            let child = match sidecar::spawn(&backend_dir, port) {
                Ok(child) => {
                    log::info!(
                        "本地服务已启动：{} (backend={})",
                        base_url,
                        backend_dir.display()
                    );
                    Some(child)
                }
                Err(error) => {
                    // 启动失败不能让整个应用崩掉：前端会显示"本地服务未连接"并提供重试
                    log::error!("本地服务启动失败：{error} (backend={})", backend_dir.display());
                    None
                }
            };

            app.manage(SidecarState {
                child: Mutex::new(child),
                base_url,
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_base_url])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<SidecarState>() {
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(child) = guard.as_mut() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                        // 置空，避免窗口重建时重复 kill
                        *guard = None;
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
