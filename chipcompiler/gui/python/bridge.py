import sys
import json
import os
import importlib.util
import traceback

def main():
    if len(sys.argv) < 3:
        error_res = {
            "status": "error",
            "message": "Usage: bridge.py <script_path> <func_name> [args_json]"
        }
        print(json.dumps(error_res))
        sys.exit(1)

    script_path = sys.argv[1]
    func_name = sys.argv[2]
    args_json = sys.argv[3] if len(sys.argv) > 3 else "{}"

    try:
        # 1. 解析参数
        params = json.loads(args_json)
        
        # 2. 检查脚本是否存在
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Script not found at: {script_path}")

        # 3. 动态加载模块
        # 获取绝对路径并添加到 sys.path 以处理内部 import
        abs_script_path = os.path.abspath(script_path)
        script_dir = os.path.dirname(abs_script_path)
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        module_name = os.path.splitext(os.path.basename(script_path))[0]
        spec = importlib.util.spec_from_file_location(module_name, abs_script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 4. 获取并执行函数
        if not hasattr(module, func_name):
            raise AttributeError(f"Module '{module_name}' has no function '{func_name}'")

        func = getattr(module, func_name)
        
        # 支持字典解包或位置参数（如果 params 是列表）
        if isinstance(params, dict):
            result = func(**params)
        elif isinstance(params, list):
            result = func(*params)
        else:
            result = func(params)

        # 5. 返回结果
        response = {
            "status": "success",
            "payload": result
        }
        print(json.dumps(response))

    except Exception as e:
        error_response = {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        print(json.dumps(error_response))
        sys.exit(1)

if __name__ == "__main__":
    main()
