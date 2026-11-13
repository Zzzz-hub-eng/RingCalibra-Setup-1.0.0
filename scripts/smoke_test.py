# -*- coding: utf-8 -*-
"""冒烟测试: 验证 ringcalibra 包可正常导入与运行 (无窗口)

用法:  python scripts/smoke_test.py [示例图片路径]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from ringcalibra import pipeline as rp

# 1. 流水线测试 (验证值来自已验证的批处理结果, 1050-jidi.jpg)
img = (sys.argv[1] if len(sys.argv) > 1
       else r'C:\Users\Administrator\Desktop\ring_analysis\sample\1050-jidi.jpg')
assert os.path.exists(img), f'sample image missing: {img}'
res = rp.analyze_image(img, 1000.0, progress=lambda p, m: None)
s = res['stats']
print('um_per_px =', round(res['um_per_px'], 6))
print('center =', round(res['cx'], 1), round(res['cy'], 1))
print('inner  =', s['inner']['dia_mean_um'], '+/-', s['inner']['dia_std_um'])
print('outer  =', s['outer']['dia_mean_um'], '+/-', s['outer']['dia_std_um'])
print('center =', s['centerline']['dia_mean_um'])
print('perimeter =', s['centerline_perimeter_um'])
print('wall =', s['mean_wall_um'])
assert 1.3 < res['um_per_px'] < 1.4, 'unexpected calibration'
assert abs(s['inner']['dia_mean_um'] - 2452.1) < 2.0, 'inner mismatch vs batch run'
assert abs(s['outer']['dia_mean_um'] - 4491.4) < 2.0, 'outer mismatch vs batch run'
assert abs(s['centerline_perimeter_um'] - 12137.8) < 20.0, 'perimeter mismatch'

# 2. 周期插值/NaN 填充自测
th = np.linspace(0, 2 * np.pi, 720, endpoint=False)
r = 900 + 10 * np.sin(5 * th)
r[:5] = np.nan
filled = rp.fill_nan_periodic(r)
assert not np.isnan(filled).any()
ctrl_idx = np.arange(0, 720, 36)
full = rp.periodic_interp(th[ctrl_idx], filled[ctrl_idx], th)
assert len(full) == 720 and np.isfinite(full).all()
assert np.abs(full - filled).max() < 5.0

# 3. 手动标尺一致性: 用自动检测端点构造手动标尺, 结果应一致
b = res['bar']
manual = rp.make_bar((b['x0'], b['y0']), (b['x1'], b['y1']), 1000.0)
res2 = rp.analyze_image(img, 1000.0, bar=manual, bar_source='manual')
assert res2['bar_source'] == 'manual'
assert abs(res2['um_per_px'] - res['um_per_px']) < 1e-6
assert abs(res2['stats']['inner']['dia_mean_um']
           - s['inner']['dia_mean_um']) < 0.5
print('manual scale bar OK, um_per_px =', round(res2['um_per_px'], 6))

# 4. GUI 模块导入测试 (不开窗口)
import tkinter as tk
from ringcalibra.editor_app import RingEditorApp, Exporter
root = tk.Tk()
root.withdraw()
app = RingEditorApp(root)
root.update()
root.destroy()
print('GUI import OK')
print('SMOKE TEST PASSED')
