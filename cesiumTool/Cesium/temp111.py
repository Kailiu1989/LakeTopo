import re
import os
import shutil

def patch_cesium_replaceAll(cesium_js_path):
    if not os.path.exists(cesium_js_path):
        print(f"[❌] 找不到 Cesium.js：{cesium_js_path}")
        return

    # 备份文件
    backup_path = cesium_js_path.replace(".js", "_backup.js")
    shutil.copyfile(cesium_js_path, backup_path)
    print(f"[✔] 已备份原始文件为：{backup_path}")

    with open(cesium_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 正则替换 .replaceAll(x, y) 为 .split(x).join(y)
    pattern = re.compile(r'\.replaceAll\(([^,]+?),\s*([^)]+?)\)')
    replaced_content = pattern.sub(r'.split(\1).join(\2)', content)

    with open(cesium_js_path, "w", encoding="utf-8") as f:
        f.write(replaced_content)

    print(f"[✅] 已自动替换所有 .replaceAll → .split().join()，并保存修改。")
    print(f"[🎉] 替换完成后，请重启你的 PyQt5 应用测试效果。")


# 修改为你实际的 Cesium.js 文件路径
cesium_path = r"H:\04-水下地形生成软件\Predicted_Reservoir_Bathymetry20241006\Predicted_Reservoir_Bathymetry\cesiumTool\Cesium\Cesium.js"
patch_cesium_replaceAll(cesium_path)
