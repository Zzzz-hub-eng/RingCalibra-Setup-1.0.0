# 示例图片目录

将待分析的环形样品显微照片放入本目录后即可运行：

```bash
# GUI
python run_app.py

# 批量 CLI
python scripts/batch_analyze.py examples examples/batch_results
```

图片要求:
- 环形/圆环截面样品, 中心为白色孔洞, 四周为背景
- 图中包含**蓝色标尺** (scale bar), 默认标注 1000 µm (可通过参数修改)
- 支持 jpg / jpeg / png / tif / tiff / bmp

注: 示例图片体积较大, 已被 .gitignore 排除, 不随仓库分发。
