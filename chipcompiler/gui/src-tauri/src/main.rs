#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::Manager;
use tauri_plugin_fs::FsExt;

// Global reference to the FastAPI server process
type ApiServerProcess = Arc<Mutex<Option<Child>>>;

/// Get the binary name for api-server based on the current platform
fn get_api_server_binary_name() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "api-server.exe"
    }
    #[cfg(not(target_os = "windows"))]
    {
        "api-server"
    }
}

/// Start the FastAPI server process
/// In debug mode: runs Python script directly
/// In release mode: runs the bundled executable
fn start_api_server(app_handle: &tauri::AppHandle) -> Option<Child> {
    use std::path::PathBuf;
    
    #[cfg(debug_assertions)]
    {
        // Development mode: use Python script with virtual environment
        let mut server_script = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        server_script.push("..");
        server_script.push("..");
        server_script.push("services");
        server_script.push("run_server.py");
        
        // Use venv Python interpreter if available, otherwise fall back to system Python
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..");
        
        #[cfg(target_os = "windows")]
        let venv_python = project_root.join(".venv").join("Scripts").join("python.exe");
        #[cfg(not(target_os = "windows"))]
        let venv_python = project_root.join(".venv").join("bin").join("python3");
        
        let interpreter = if venv_python.exists() {
            println!("Using venv Python: {:?}", venv_python);
            venv_python.to_string_lossy().to_string()
        } else {
            println!("Venv not found, using system Python");
            #[cfg(target_os = "windows")]
            { "python".to_string() }
            #[cfg(not(target_os = "windows"))]
            { "python3".to_string() }
        };
        
        println!("Starting FastAPI server (dev mode) from: {:?}", server_script);
        
        match Command::new(&interpreter)
            .arg(&server_script)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg("8765")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => {
                println!("✅ FastAPI server started with PID: {}", child.id());
                return Some(child);
            }
            Err(e) => {
                eprintln!("❌ Failed to start FastAPI server: {}", e);
                return None;
            }
        }
    }
    
    #[cfg(not(debug_assertions))]
    {
        // Production mode: use bundled executable
        // Tauri's externalBin places binaries in the same directory as the main executable
        
        let binary_name = get_api_server_binary_name();
        
        // Try multiple possible locations for the binary
        let possible_paths = get_possible_binary_paths(app_handle, binary_name);
        
        let mut server_binary: Option<PathBuf> = None;
        for path in &possible_paths {
            println!("Checking for api-server at: {:?}", path);
            if path.exists() {
                server_binary = Some(path.clone());
                break;
            }
        }
        
        let server_binary = match server_binary {
            Some(path) => path,
            None => {
                eprintln!("❌ API server binary not found. Checked locations:");
                for path in &possible_paths {
                    eprintln!("   - {:?}", path);
                }
                return None;
            }
        };
        
        println!("Starting FastAPI server (prod mode) from: {:?}", server_binary);
        
        match Command::new(&server_binary)
            .arg("--host")
            .arg("127.0.0.1")
            .arg("--port")
            .arg("8765")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
        {
            Ok(child) => {
                println!("✅ FastAPI server started with PID: {}", child.id());
                Some(child)
            }
            Err(e) => {
                eprintln!("❌ Failed to start FastAPI server: {}", e);
                None
            }
        }
    }
}

/// Get possible paths where the api-server binary might be located
/// This handles differences between macOS, Linux, and Windows
#[cfg(not(debug_assertions))]
fn get_possible_binary_paths(app_handle: &tauri::AppHandle, binary_name: &str) -> Vec<std::path::PathBuf> {
    
    let mut paths = Vec::new();
    
    // Method 1: Next to the current executable (works for Linux and Windows)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            paths.push(exe_dir.join(binary_name));
        }
    }
    
    // Method 2: Using Tauri's resource_dir (may work for some setups)
    if let Ok(resource_dir) = app_handle.path().resource_dir() {
        // Direct in resource dir
        paths.push(resource_dir.join(binary_name));
        // In binaries subdirectory
        paths.push(resource_dir.join("binaries").join(binary_name));
    }
    
    // Method 3: macOS specific - inside the .app bundle
    #[cfg(target_os = "macos")]
    {
        if let Ok(exe_path) = std::env::current_exe() {
            // exe_path is typically: ECC.app/Contents/MacOS/ECC
            // Binary should be at: ECC.app/Contents/MacOS/api-server
            if let Some(macos_dir) = exe_path.parent() {
                paths.push(macos_dir.join(binary_name));
                
                // Also check Resources directory
                if let Some(contents_dir) = macos_dir.parent() {
                    paths.push(contents_dir.join("Resources").join(binary_name));
                    paths.push(contents_dir.join("Resources").join("binaries").join(binary_name));
                }
            }
        }
    }
    
    paths
}

/// Stop the FastAPI server process
fn stop_api_server(process: &mut Option<Child>) {
    if let Some(ref mut child) = process {
        println!("Stopping FastAPI server (PID: {})...", child.id());
        match child.kill() {
            Ok(_) => println!("✅ FastAPI server stopped"),
            Err(e) => eprintln!("❌ Failed to stop FastAPI server: {}", e),
        }
        *process = None;
    }
}

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
    
    // Create a shared reference for the API server process
    let api_server: ApiServerProcess = Arc::new(Mutex::new(None));
    let api_server_clone = api_server.clone();
    
    tauri::Builder::default()
        .plugin(tauri_plugin_store::Builder::new().build())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .setup(move |app| {
            let window = app.get_webview_window("main").unwrap();

            // Start the FastAPI server
            {
                let mut server = api_server.lock().unwrap();
                *server = start_api_server(&app.handle());
            }

            // Wait a moment for the server to start
            thread::sleep(Duration::from_millis(500));

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
        .on_window_event(move |_window, event| {
            // Stop the API server when the window is destroyed
            if let tauri::WindowEvent::Destroyed = event {
                let mut server = api_server_clone.lock().unwrap();
                stop_api_server(&mut server);
            }
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
