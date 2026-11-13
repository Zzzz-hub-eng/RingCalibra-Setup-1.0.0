# RingCalibra — 环形样品显微照片标定与分析工具

对环形/圆环截面样品（热压石墨环、缠绕环、涂层环等）的光学显微照片进行
**自动标定、边界测量与统计**，并提供**交互式手动修正**：

- 自动识别图中**蓝色标尺 (scale bar)**，测量像素长度 → `µm/px` 标定
- 自动定位中心孔洞圆心并迭代精化（圆拟合）
- 沿周角 0.25° 步长径向采样，按衬度检测**内孔 / 外壁 / 同心环暗带**边界
- 直接显示 `ring_calibrated_overlay` 标定叠加图与统计结果
- 自动检测不准时，**鼠标拖拽控制点**手动修正曲线，统计值实时重算
- 一键导出 CSV / JSON / 图表，结果可复现

## 功能特性

| 功能 | 说明 |
|------|------|
| 标尺标定 | 自动检测蓝色标尺；失败或不准时**手动点击标尺两端**，支持任意标注值 |
| 边界检测 | 0.25° 步长（1440 条射线）径向采样，内孔/外壁/同心环暗带 |
| 统计输出 | 直径均值±标准差、均值 95%CI、95% 区间、圆度、椭圆拟合/离心率 |
| 附加计算 | 中心线周长（实测曲线弧长累加）、平均壁厚 `mean(r_out−r_in)` |
| 进度显示 | 分析过程实时显示进度条与百分比，可随时查看当前阶段 |
| 手动修正 | 每 5° 一个控制点，拖拽即改，周期插值 + 可选平滑，实时重算 |
| 批量模式 | CLI 扫描目录批量分析，汇总 `batch_summary.csv` |

## 环境要求

- Python ≥ 3.10（含 tkinter，Windows 官方安装包自带）
- 依赖：`numpy`、`scipy`、`matplotlib`、`pillow`（见 `requirements.txt`）

## 安装

```bash
# 建议使用虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

## 快速开始

### 1. 交互式 GUI（推荐）

```bash
python run_app.py
```

1. 点击 **导入图片**，选择显微照片（jpg/jpeg/png/tif/bmp），窗口显示原图并自动识别标尺
2. **核对标尺**：若自动识别失败或不准，点击 **手动标尺**，在图上依次点击标尺的
   两个端点（左端 → 右端）；也可修改“标尺 (µm)”数值后点 **自动标尺** 重新识别
3. 点击 **开始分析**，进度条与百分比实时显示分析进度（约 1–2 分钟/张）
4. 分析完成后直接显示标定叠加图与统计信息
5. **手动修正曲线**：在"编辑曲线"下拉框切换 `inner`/`outer`，
   鼠标拖拽图上圆点控制点修正边界 → 松开即自动重算
6. 点击 **导出结果**，在图片目录 `ring_results/<图名>/` 下生成：
   - `ring_calibrated_overlay.png`（含修正后曲线的叠加图）
   - `diameter_vs_angle.csv`（0.25° 步长，px + µm）
   - `summary.json`（标定信息 + 全部统计值，含 `manually_edited` 标记）

> 提示：编辑前请确保 matplotlib 工具栏处于默认箭头模式；
> 拖错可点"恢复自动检测"重新分析。

### 2. 命令行批量分析

```bash
python scripts/batch_analyze.py <图片目录> [输出目录] [--scale 1000]
```

每张图输出 `diameter_vs_angle.png/.csv`、`polar_map.png`、
`centerline_diameter_vs_angle.png`、`ring_calibrated.png`、
`ring_calibrated_overlay.png`、`summary.json`，
并汇总生成 `batch_summary.csv`。

### 3. 验证安装（可选）

```bash
python scripts/smoke_test.py <示例图片路径>
```

## 项目结构

```
RingCalibra/
├── run_app.py                 # GUI 启动入口
├── requirements.txt           # 依赖清单
├── ringcalibra/               # 核心包
│   ├── __init__.py
│   ├── pipeline.py            # 自动分析流水线（标定/圆心/边界检测/统计）
│   └── editor_app.py          # Tkinter GUI + 拖拽编辑 + 导出
├── scripts/
│   ├── batch_analyze.py       # 命令行批量分析
│   └── smoke_test.py          # 冒烟测试
├── examples/                  # 示例图片（自行放入，不入库）
└── README.md
```

## 方法说明（复现细节）

1. **标尺标定**：颜色阈值 `B>150, B−R>80, B−G>80` 取最大连通域，
   测量其 x 向范围作为标尺像素长度；`µm/px = 标注值 / 长度`。
   手动标尺取两点距离并按“含端点像素计数”约定 +1 px，与自动检测口径一致。
2. **圆心定位**：中心白色孔洞阈值分割 → 质心初值 → 内边界 720 角度
   圆拟合迭代 3 次。
3. **边界检测**（savgol 平滑后）：
   - 内孔：半径 >600 px 处首次跌破灰度 180
   - 外壁：灰度 (40,170) 的最外暗带之后 300 px 内回升 >235
   - 同心环暗带：r∈[900,1700] px 局部极小值，按径向参考位置归并
4. **去尖刺**：角度向滚动中值（size 7）偏差 >40 px 的点用中值替代；
   NaN 沿角度周期插值填充。
5. **统计**：t 分布 95%CI、2.5–97.5 分位数、极径 min/max 圆度、
   极坐标椭圆拟合 `r(θ)=ab/√((b·cos(θ−φ))²+(a·sin(θ−φ))²)`。
6. **手动修正**：控制点半径 → 周期线性插值回 1440 角度 →
   可选 savgol(31,3) 平滑（wrap 模式）→ 全部统计量重算。

## 已知限制

- 标尺检测依赖**蓝色**标尺；灰度标尺图片需扩展检测逻辑
- 内/外壁检测阈值针对本类样品衬度（孔洞≈245、壁≈110、背景≈250）整定，
  其他衬度条件可能需要调整 `ringcalibra/pipeline.py` 中的阈值
- 极坐标采样假设样品在图内完整成像且半径 <2000 px

## 输出字段说明（summary.json / batch_summary.csv）

| 字段 | 含义 |
|------|------|
| `dia_mean/std_um` | 直径均值 / 标准差 (µm) |
| `dia_ci95_mean_um` | 均值 95% 置信区间半宽 |
| `dia_p95_lo/hi_um` | 95% 分位数区间 |
| `circ_ratio` | 圆度 `r_min/r_max`（越接近 1 越圆） |
| `eccentricity` | 椭圆拟合离心率 |
| `centerline_perimeter_um` | 中心线实测周长 |
| `mean_wall_um` | 平均壁厚 `mean(r_out − r_in)` |
| `mean_dia_diff_um` | 直径差均值 `mean(D_out − D_in)` |
