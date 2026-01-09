#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::thread;
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_fs::FsExt;

#[derive(serde::Serialize)]
struct PyResult {
    code: i32,
    stdout: String,
    stderr: String,
}

#[tauri::command]
async fn run_python(script: String, args: Option<Vec<String>>) -> Result<PyResult, String> {
    use std::path::PathBuf;
    use std::process::Command;

    // 获取脚本绝对路径：相对于可执行文件所在目录或项目根目录
    // 在开发环境下，CARGO_MANIFEST_DIR 是 src-tauri 目录
    let mut script_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    script_path.push("..");
    script_path.push("python");
    script_path.push(&script);

    let interpreter = if cfg!(windows) { "python" } else { "python3" };
    let args_vec = args.unwrap_or_default();

    let output = Command::new(interpreter)
        .arg(&script_path)
        .args(args_vec)
        .output()
        .map_err(|e| format!("Failed to execute python script: {}", e))?;

    Ok(PyResult {
        code: output.status.code().unwrap_or(-1),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}

#[tauri::command]
fn show_main_window(window: tauri::Window) {
    window.show().unwrap();
    window.set_focus().unwrap();
    println!("Window shown via frontend signal");
}

/// 动态授予文件系统访问权限
/// 
/// 此命令允许前端在运行时请求访问特定目录的权限，
/// 实现了最小权限原则：应用启动时无全盘访问，仅在用户明确操作后动态授予。
#[tauri::command]
async fn request_project_permission(app: tauri::AppHandle, path: String) -> Result<(), String> {
    use std::path::PathBuf;
    
    // 获取文件系统作用域管理器
    let scope = app.fs_scope();
    let path_buf = PathBuf::from(&path);
    
    // 递归允许访问该目录及其子目录
    scope
        .allow_directory(&path_buf, true)
        .map_err(|e| format!("无法授予访问权限 {}: {}", path_buf.display(), e))?;
    
    println!("✅ 已授予文件系统访问权限: {}", path);
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();


            let window_clone = window.clone();
            thread::spawn(move || {
                thread::sleep(Duration::from_secs(1));
                if let Ok(false) = window_clone.is_visible() {
                    let _ = window_clone.show();
                    // #[cfg(debug_assertions)] 
                    // window_clone.open_devtools();
                    println!("Window shown via safety timeout");
                }
            });

            #[cfg(debug_assertions)]
            {
                let scale_factor = window.scale_factor().unwrap_or(1.0);
                if let Ok(size) = window.inner_size() {
                    println!("=== Window Debug Info ===");
                    println!(
                        "Logical size: {}x{}",
                        size.width as f64 / scale_factor,
                        size.height as f64 / scale_factor
                    );
                }
            }
            Ok(())
        })

        .invoke_handler(tauri::generate_handler![
            run_python,
            show_main_window,
            request_project_permission
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
