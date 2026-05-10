import eel
import os
import sys
import json
import io

# 初始化：指定HTML文件夹
eel.init("web")

# 导入pipeline相关模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_nodes
from pipeline import load_pipeline_from_json, Pipeline

# 给HTML调用的Python函数
@eel.expose
def python_add(a, b):
    print(f"Python收到：{a} + {b}")
    return a + b

@eel.expose
def run_pipeline(pipeline_data):
    """运行Pipeline"""
    print("=== run_pipeline called ===")
    
    try:
        workspace_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'test_workspace')
        os.makedirs(workspace_dir, exist_ok=True)
        
        pipeline_path = os.path.join(workspace_dir, 'pipeline.json')
        with open(pipeline_path, 'w', encoding='utf-8') as f:
            json.dump(pipeline_data, f, ensure_ascii=False, indent=2)
        
        print("Loading pipeline...")
        pipeline = load_pipeline_from_json(pipeline_path, workspace_dir)
        pipeline.force = True
        print("Pipeline loaded, stages:", len(pipeline.stages))
        
        pipeline.run()
        
        import time
        time.sleep(0.1)
        
        if os.path.exists(pipeline.log_file):
            with open(pipeline.log_file, 'r', encoding='utf-8') as f:
                output = f.read()
        else:
            output = "Log file not found"
        
        print("=== run_pipeline finished ===")
        return {'success': True, 'output': output}
    
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
        print(f"Pipeline error: {error_msg}")
        return {'success': False, 'error': error_msg}

# 启动程序，使用Bottle服务器模式（不需要浏览器），并保持阻塞运行
print("Starting eel server...")
eel.start("index.html", size=(1200, 800), mode='none', port=8081, block=True)
