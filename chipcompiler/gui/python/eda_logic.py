import os

def get_step_result(project_path, step):
    """
    模拟 EDA 后端根据步骤返回结果
    """
    # 映射逻辑：根据步骤返回对应的图片路径
    mapping = {
        "Floorplan": "Floorplan_iEDA/output/gcd_Floorplan.png",
        "Placement": "place_iEDA/output/gcd_place.png",
        "CTS": "CTS_iEDA/data/cts/output/cts_design.png", 
        "Routing": "route_iEDA/output/gcd_route.png"
    }
    
    rel_path = mapping.get(step)
    if not rel_path:
        return {"error": f"Unknown step: {step}"}
    
    # 1. 尝试用户项目路径
    full_path = os.path.join(project_path, rel_path)
            
    # 3. 如果不存在则返回错误
    if not os.path.exists(full_path):
        return {
            "step": step,
            "image_path": rel_path,
            "exists": False,
            "message": f"File not found in project: {rel_path}"
        }
    
    return {
        "step": step,
        "image_path": full_path,
        "exists": True
    }
