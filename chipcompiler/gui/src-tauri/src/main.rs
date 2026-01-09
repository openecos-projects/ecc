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
async fn call_python_func(
    script_path: String,
    func_name: String,
    args: Option<serde_json::Value>,
) -> Result<PyResult, String> {
    use std::path::PathBuf;
    use std::process::Command;

    let mut bridge_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    bridge_path.push("..");
    bridge_path.push("python");
    bridge_path.push("bridge.py");

    let mut resolved_script_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    resolved_script_path.push("..");
    resolved_script_path.push("python");
    resolved_script_path.push(&script_path);

    let interpreter = if cfg!(windows) { "python" } else { "python3" };
    let args_json = args.unwrap_or(serde_json::json!({})).to_string();

    let output = Command::new(interpreter)
        .arg(&bridge_path)
        .arg(&resolved_script_path)
        .arg(&func_name)
        .arg(args_json)
        .output()
        .map_err(|e| format!("Failed to execute python bridge: {}", e))?;

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
    
    // 递归允许访问该目录及其子目录 (文件系统)
    scope
        .allow_directory(&path_buf, true)
        .map_err(|e| format!("无法授予文件系统访问权限 {}: {}", path_buf.display(), e))?;

    // 在 Tauri v2 中，convertFileSrc 自动使用 fs scope，不需要单独的 asset protocol scope
    println!("✅ 已授予文件系统访问权限: {}", path);
    Ok(())
}

fn main() {
    use std::path::PathBuf;
    
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(|app| {
            let window = app.get_webview_window("main").unwrap();

            // 自动授予内置 data 目录的访问权限，以便加载演示数据
            let mut data_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            data_path.push("..");
            data_path.push("data");
            
            if data_path.exists() {
                let final_path = data_path.canonicalize().unwrap_or(data_path.clone());
                let scope = app.fs_scope();
                if let Err(e) = scope.allow_directory(&final_path, true) {
                    eprintln!("❌ 授予 fs scope 失败: {}", e);
                } else {
                    println!("✅ 已授予 fs scope 访问权限: {:?}", final_path);
                }
            }

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
            call_python_func,
            show_main_window,
            request_project_permission
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
