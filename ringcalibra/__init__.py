# -*- coding: utf-8 -*-
"""RingCalibra: 环形样品显微照片标定与分析工具包

自动流水线: 蓝色标尺标定 -> 圆心定位 -> 内孔/外壁/同心环暗带检测 -> 统计
交互编辑: Tkinter GUI 中拖拽控制点手动修正边界曲线, 实时重算
"""
__version__ = '1.0.0'

from . import pipeline  # noqa: F401

__all__ = ['pipeline', 'editor_app', '__version__']
