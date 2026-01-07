#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use std::thread;
use std::time::Duration;

#[tauri::command]
fn minimize_window(window: tauri::Window) {
    window.minimize().unwrap();
}

#[tauri::command]
fn maximize_window(window: tauri::Window) {
    window.maximize().unwrap();
}

#[tauri::command]
fn unmaximize_window(window: tauri::Window) {
    window.unmaximize().unwrap();
}

#[tauri::command]
fn close_window(window: tauri::Window) {
    window.close().unwrap();
}

#[tauri::command]
fn is_maximized(window: tauri::Window) -> bool {
    window.is_maximized().unwrap_or(false)
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let window = app.get_window("main").unwrap();
            
            // 获取当前屏幕的缩放因子
            let scale_factor = window.scale_factor().unwrap_or(1.0);
            println!("=== Window Setup ===");
            println!("Screen scale factor: {}", scale_factor);
            
            // 始终使用逻辑像素，Tauri 会自动处理 Retina 缩放
            let _ = window.set_size(tauri::LogicalSize {
                width: 1400.0,
                height: 900.0,
            });
            
            let _ = window.set_min_size(Some(tauri::LogicalSize {
                width: 1280.0,
                height: 800.0,
            }));
            
            // 居中窗口
            let _ = window.center();
            
            // 获取并打印窗口的实际尺寸（用于调试）
            if let Ok(size) = window.inner_size() {
                println!("Window physical size: {}x{}", size.width, size.height);
                let logical_width = size.width as f64 / scale_factor;
                let logical_height = size.height as f64 / scale_factor;
                println!("Window logical size: {:.0}x{:.0}", logical_width, logical_height);
            }
            
            if let Ok(size) = window.outer_size() {
                println!("Window outer size: {}x{}", size.width, size.height);
            }
            
            // 延迟显示窗口
            let window_clone = window.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_millis(300));
                let _ = window_clone.show();
                println!("Window shown");
            });
            
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            minimize_window,
            maximize_window,
            unmaximize_window,
            close_window,
            is_maximized
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
