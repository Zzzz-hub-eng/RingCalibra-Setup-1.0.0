# -*- coding: utf-8 -*-
"""
交互式环形样品标定编辑器 (Tkinter + matplotlib)
  1. 导入图片 -> 自动运行完整分析流水线
  2. 直接显示 ring_calibrated_overlay 标定叠加图 + 统计结果
  3. 手动修正: 切换 inner/outer, 鼠标拖拽控制点 (每 5° 一个) 修正曲线,
     松开后自动重插值/平滑并实时重算统计值
  4. 一键导出: diameter_vs_angle.csv + summary.json + overlay PNG
"""
import os
import csv
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
# 中文字体 (避免图中中文显示为方块)
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei',
                                          'PingFang SC', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from scipy.signal import savgol_filter

from ringcalibra import pipeline as rp

NTH = rp.NTH
CTRL_STEP = 20          # 每 20 个角度点 (5°) 一个可拖拽控制点


class RingEditorApp:
    def __init__(self, root):
        self.root = root
        root.title('环形样品标定编辑器 Ring Calibration Editor')
        root.geometry('1280x960')
        self.state = None
        self.drag = None
        self.artists = {}
        self.ctrl_idx = np.arange(0, NTH, CTRL_STEP)
        self.ctrl_r = {}
        self.q = queue.Queue()
        self.busy = False
        # 图片 / 标尺状态
        self.img_path = None
        self.img_rgb = None
        self.bar = None
        self.bar_source = None
        self.pick_pts = []
        self.bar_pickmode = False
        self._build_toolbar()
        self._build_canvas()
        self._build_statusbar()
        root.after(150, self._poll_queue)
        self._exporter = Exporter(self)

    # ---------------- UI 构建 ----------------
    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side='top', fill='x')
        self.btn_open = ttk.Button(bar, text='导入图片', command=self.open_image)
        self.btn_open.pack(side='left', padx=4)
        ttk.Label(bar, text='标尺 (µm):').pack(side='left', padx=(12, 2))
        self.scale_var = tk.StringVar(value='1000')
        ttk.Entry(bar, textvariable=self.scale_var, width=8).pack(side='left')
        self.btn_autobar = ttk.Button(bar, text='自动标尺',
                                      command=self.auto_detect_bar,
                                      state='disabled')
        self.btn_autobar.pack(side='left', padx=(10, 2))
        self.btn_manualbar = ttk.Button(bar, text='手动标尺',
                                        command=self.start_manual_bar,
                                        state='disabled')
        self.btn_manualbar.pack(side='left', padx=2)
        self.btn_run = ttk.Button(bar, text='开始分析',
                                  command=self.start_analysis, state='disabled')
        self.btn_run.pack(side='left', padx=(10, 4))
        ttk.Label(bar, text='编辑曲线:').pack(side='left', padx=(12, 2))
        self.edit_var = tk.StringVar(value='inner')
        self.cmb_edit = ttk.Combobox(bar, textvariable=self.edit_var, width=8,
                                     state='disabled', values=['inner', 'outer'])
        self.cmb_edit.pack(side='left')
        self.cmb_edit.bind('<<ComboboxSelected>>', lambda e: self._refresh_markers())
        self.smooth_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text='自动平滑',
                        variable=self.smooth_var).pack(side='left', padx=(10, 2))
        self.btn_recalc = ttk.Button(bar, text='重新计算', command=self.recompute,
                                     state='disabled')
        self.btn_recalc.pack(side='left', padx=(10, 2))
        self.btn_save = ttk.Button(bar, text='导出结果', command=self.save_results,
                                   state='disabled')
        self.btn_save.pack(side='left', padx=2)
        self.btn_reset = ttk.Button(bar, text='恢复自动检测', command=self.reset_auto,
                                    state='disabled')
        self.btn_reset.pack(side='left', padx=2)

        # 进度条行
        pframe = ttk.Frame(self.root, padding=(6, 0))
        pframe.pack(side='top', fill='x')
        self.pbar = ttk.Progressbar(pframe, mode='determinate', maximum=100,
                                    length=560)
        self.pbar.pack(side='left', padx=4)
        self.pct_var = tk.StringVar(value='0%')
        ttk.Label(pframe, textvariable=self.pct_var, width=6).pack(side='left', padx=2)
        self.prog_msg = ttk.Label(pframe, text='', anchor='w')
        self.prog_msg.pack(side='left', padx=6, fill='x', expand=1)

        self.info = tk.Text(self.root, height=7, font=('Consolas', 10),
                            bg='#f7f7ee', relief='groove')
        self.info.pack(side='top', fill='x', padx=6)

    def _build_canvas(self):
        self.fig = Figure(figsize=(8.5, 8.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(self.fig, master=self.root)
        canvas.draw()
        canvas.get_tk_widget().pack(side='top', fill='both', expand=1)
        self.canvas = canvas
        self.toolbar = NavigationToolbar2Tk(canvas, self.root, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side='bottom', fill='x')
        canvas.mpl_connect('button_press_event', self._on_press)
        canvas.mpl_connect('motion_notify_event', self._on_motion)
        canvas.mpl_connect('button_release_event', self._on_release)

    def _build_statusbar(self):
        self.status = ttk.Label(self.root, text='请点击"导入图片"开始',
                                anchor='w', padding=(6, 3))
        self.status.pack(side='bottom', fill='x')

    # ---------------- 图片导入 / 标尺 ----------------
    def open_image(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title='选择显微照片',
            filetypes=[('图片', '*.jpg *.jpeg *.png *.tif *.tiff *.bmp'),
                       ('所有文件', '*.*')])
        if not path:
            return
        try:
            from PIL import Image
            im = Image.open(path).convert('RGB')
        except Exception as e:
            messagebox.showerror('无法读取图片', f'{type(e).__name__}: {e}')
            return
        self.img_path = path
        self.img_rgb = im
        self.state = None
        self.bar = None
        self.bar_source = None
        self.pick_pts = []
        self.bar_pickmode = False
        for b in (self.btn_autobar, self.btn_manualbar, self.btn_run):
            b.config(state='normal')
        for b in (self.btn_recalc, self.btn_save, self.btn_reset):
            b.config(state='disabled')
        self.cmb_edit.config(state='disabled')
        self.info.config(state='normal')
        self.info.delete('1.0', 'end')
        self.info.config(state='disabled')
        self._set_progress(0, '')
        self._draw_preview()
        # 先尝试自动识别标尺 (失败则可手动绘制)
        self.auto_detect_bar()

    def _scale_um(self):
        try:
            v = float(self.scale_var.get())
        except ValueError:
            messagebox.showerror('错误', '标尺长度必须是数字')
            raise
        if v <= 0:
            messagebox.showerror('错误', '标尺长度必须大于 0')
            raise ValueError('invalid scale')
        return v

    def auto_detect_bar(self):
        if self.img_rgb is None or self.busy:
            return
        try:
            scale_um = self._scale_um()
        except ValueError:
            return
        try:
            self.bar = rp.detect_scale_bar(self.img_rgb, scale_um)
            self.bar_source = 'auto'
            self._draw_preview()
            self.status.config(
                text=f'已自动识别标尺: {self.bar["bar_len_px"]} px = {scale_um:g} µm '
                     f'({self.bar["um_per_px"]:.4f} µm/px), 可点"开始分析"')
        except Exception as e:
            self.bar = None
            self.bar_source = None
            self._draw_preview()
            messagebox.showwarning(
                '未识别到标尺',
                f'{e}\n\n请点击"手动标尺", 然后在图上依次点击标尺的两个端点。')

    def start_manual_bar(self):
        if self.img_rgb is None or self.busy:
            return
        self.bar_pickmode = True
        self.pick_pts = []
        self.bar = None
        self.bar_source = None
        self._draw_preview()
        self.status.config(text='手动标尺: 请在图上依次点击标尺的 左端 -> 右端 两个端点')

    def _add_bar_point(self, x, y):
        self.pick_pts.append((float(x), float(y)))
        if len(self.pick_pts) == 1:
            self._draw_preview()
            self.status.config(text='已记录第 1 个端点, 请点击标尺另一端')
            return
        p0, p1 = self.pick_pts[0], self.pick_pts[1]
        try:
            scale_um = self._scale_um()
            self.bar = rp.make_bar(p0, p1, scale_um)
        except ValueError as e:
            self.pick_pts = []
            self._draw_preview()
            messagebox.showwarning('标尺无效', str(e))
            return
        self.bar_source = 'manual'
        self.bar_pickmode = False
        self.pick_pts = []
        self._draw_preview()
        self.status.config(
            text=f'手动标尺: {self.bar["bar_len_px"]} px = {scale_um:g} µm '
                 f'({self.bar["um_per_px"]:.4f} µm/px), 可点"开始分析"')

    def _draw_preview(self):
        """显示原图 + 当前标尺 (分析前预览)"""
        self.ax.clear()
        if self.img_rgb is not None:
            self.ax.imshow(np.array(self.img_rgb), origin='upper')
        if self.bar is not None:
            b = self.bar
            by0 = b.get('y0', b['y'])
            by1 = b.get('y1', b['y'])
            self.ax.plot([b['x0'], b['x1']], [by0, by1], '-',
                         color='deepskyblue', lw=3)
            self.ax.plot([b['x0'], b['x1']], [by0, by1], 'o', ms=7,
                         mfc='none', mec='deepskyblue', mew=1.5)
            self.ax.text(0.5 * (b['x0'] + b['x1']), 0.5 * (by0 + by1) - 110,
                         f"标尺: {self.scale_var.get()} µm = {b['bar_len_px']} px\n"
                         f"({b['um_per_px']:.4f} µm/px, "
                         f"{'自动' if self.bar_source == 'auto' else '手动'})",
                         ha='center', fontsize=10,
                         bbox=dict(fc='lightyellow', alpha=0.9))
        for (px_, py_) in self.pick_pts:
            self.ax.plot(px_, py_, '+', ms=14, mew=2, color='deepskyblue')
        self.ax.set_title(
            (os.path.basename(self.img_path) if self.img_path else '')
            + ('   [手动标尺: 点击两个端点]' if self.bar_pickmode else ''),
            fontsize=10)
        self.ax.axis('off')
        self.fig.tight_layout()
        self.canvas.draw()

    # ---------------- 开始分析 / 后台进度 ----------------
    def start_analysis(self):
        if self.img_rgb is None or self.busy:
            return
        try:
            scale_um = self._scale_um()
        except ValueError:
            return
        if self.bar is None:
            messagebox.showwarning('缺少标尺',
                                   '尚未标定标尺: 请先"自动标尺"或"手动标尺"')
            return
        self.state = None
        self._start_analysis(self.img_path, scale_um, self.bar,
                             self.bar_source or 'manual',
                             f'正在分析 {os.path.basename(self.img_path)} ...')

    def _start_analysis(self, path, scale_um, bar, bar_source, msg):
        self._set_busy(True, msg)
        self._set_progress(0, msg)
        self.pbar.config(mode='determinate', maximum=100)
        threading.Thread(target=self._analyze_worker,
                         args=(path, scale_um, bar, bar_source), daemon=True).start()

    def _analyze_worker(self, path, scale_um, bar=None, bar_source=None):
        def progress(pct, msg):
            self.q.put(('progress', (pct, msg)))
        try:
            result = rp.analyze_image(path, scale_um, progress,
                                      bar=bar, bar_source=bar_source)
            self.q.put(('done', result))
        except Exception as e:
            self.q.put(('error', f'{type(e).__name__}: {e}'))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'progress':
                    pct, msg = payload
                    self._set_progress(pct, msg)
                elif kind == 'done':
                    self._on_analyzed(payload)
                    self._set_progress(100, '分析完成')
                    self._set_busy(
                        False, '分析完成: 可拖拽控制点修正; 点"导出结果"保存')
                elif kind == 'error':
                    self._set_progress(0, '分析失败')
                    self._set_busy(False)
                    messagebox.showerror('分析失败', payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _set_progress(self, pct, msg=''):
        pct = max(0, min(100, int(pct)))
        self.pbar['value'] = pct
        self.pct_var.set(f'{pct}%')
        self.prog_msg.config(text=msg)
        if msg:
            self.status.config(text=f'[{pct}%] {msg}')

    def _set_busy(self, busy, msg=None):
        self.busy = busy
        state = 'disabled' if busy else 'normal'
        self.btn_open.config(state=state)
        has_img = self.img_rgb is not None
        self.btn_autobar.config(state=state if has_img else 'disabled')
        self.btn_manualbar.config(state=state if has_img else 'disabled')
        self.btn_run.config(state=state if (has_img and self.bar is not None)
                            else 'disabled')
        if msg:
            self.status.config(text=msg)

    def _on_analyzed(self, st_):
        self.state = st_
        self.bar = st_['bar']
        self.bar_source = st_.get('bar_source', self.bar_source)
        self.ctrl_r['inner'] = st_['rin'][self.ctrl_idx].copy()
        self.ctrl_r['outer'] = st_['rout'][self.ctrl_idx].copy()
        self.cmb_edit.config(state='readonly')
        for b in (self.btn_recalc, self.btn_save, self.btn_reset):
            b.config(state='normal')
        self._draw_overlay()
        self._update_info()

    # ---------------- 绘图 ----------------
    def _draw_overlay(self):
        st_ = self.state
        self.ax.clear()
        self.ax.imshow(np.array(st_['im_rgb']), origin='upper')
        th = st_['th']
        cx, cy = st_['cx'], st_['cy']
        s = st_['stats']
        for k, arr in enumerate(st_['band_r']):
            ok = ~np.isnan(arr)
            self.ax.plot(cx + arr[ok] * np.cos(th[ok]),
                         cy + arr[ok] * np.sin(th[ok]),
                         lw=0.6, alpha=0.6, color='m',
                         label=f'band{k+1}' if k == 0 else None)
        self.artists['inner'] = self.ax.plot(
            cx + st_['rin'] * np.cos(th), cy + st_['rin'] * np.sin(th),
            'r-', lw=1.3, label=f"inner Ø {s['inner']['dia_mean_um']:.0f} µm")[0]
        self.artists['outer'] = self.ax.plot(
            cx + st_['rout'] * np.cos(th), cy + st_['rout'] * np.sin(th),
            'b-', lw=1.3, label=f"outer Ø {s['outer']['dia_mean_um']:.0f} µm")[0]
        self.artists['centerline'] = self.ax.plot(
            cx + st_['rc'] * np.cos(th), cy + st_['rc'] * np.sin(th),
            'g--', lw=1.0,
            label=f"centerline Ø {s['centerline']['dia_mean_um']:.0f} µm")[0]
        bar = st_['bar']
        by0 = bar.get('y0', bar['y'])
        by1 = bar.get('y1', bar['y'])
        self.ax.plot([bar['x0'], bar['x1']], [by0, by1], '-',
                     color='deepskyblue', lw=3)
        self.ax.plot([bar['x0'], bar['x1']], [by0, by1], 'o', ms=7,
                     mfc='none', mec='deepskyblue', mew=1.5)
        self.ax.plot(cx, cy, 'k+', ms=12, mew=2)
        self.ax.text(bar['x0'], by0 - 90,
                     f"scale bar: {self.scale_var.get()} µm = "
                     f"{bar['bar_len_px']} px\n"
                     f"({st_['um_per_px']:.4f} µm/px, "
                     f"{'auto' if st_.get('bar_source') == 'auto' else 'manual'})",
                     fontsize=9, bbox=dict(fc='white', alpha=0.85))
        self._info_box = self.ax.text(
            0.01, 0.01, '', transform=self.ax.transAxes, va='bottom',
            fontsize=9, bbox=dict(fc='lightyellow', alpha=0.9))
        self.ax.legend(loc='upper left', fontsize=8, framealpha=0.85)
        self.ax.axis('off')
        self.fig.tight_layout()
        self.canvas.draw()
        self._refresh_markers()

    def _refresh_markers(self):
        """按当前选择的编辑曲线显示控制点"""
        if 'markers' in self.artists:
            self.artists['markers'].remove()
            del self.artists['markers']
        curve = self.edit_var.get()
        if self.state is None or curve not in self.ctrl_r:
            self.canvas.draw_idle()
            return
        th_c = self.state['th'][self.ctrl_idx]
        r_c = self.ctrl_r[curve]
        cx, cy = self.state['cx'], self.state['cy']
        color = 'r' if curve == 'inner' else 'b'
        self.artists['markers'] = self.ax.plot(
            cx + r_c * np.cos(th_c), cy + r_c * np.sin(th_c),
            'o', ms=5, mfc=color, mec='k', mew=0.5, alpha=0.9,
            zorder=10, label='_nolegend_')[0]
        self.canvas.draw_idle()

    # ---------------- 拖拽编辑 ----------------
    def _on_press(self, event):
        # 手动标尺点选模式
        if (self.bar_pickmode and not self.busy and event.inaxes is self.ax
                and event.button == 1 and event.xdata is not None):
            self._add_bar_point(event.xdata, event.ydata)
            return
        if (self.state is None or self.busy
                or event.inaxes is not self.ax or event.button != 1):
            return
        mk = self.artists.get('markers')
        if mk is None:
            return
        xy = np.column_stack([mk.get_xdata(), mk.get_ydata()])
        disp = self.ax.transData.transform(xy)
        d = np.hypot(disp[:, 0] - event.x, disp[:, 1] - event.y)
        i = int(np.argmin(d))
        if d[i] < 14:
            self.drag = (self.edit_var.get(), i)
            self.status.config(text=f'拖拽 {self.edit_var.get()} 控制点 #{i} ...')

    def _on_motion(self, event):
        if self.drag is None:
            return
        if event.inaxes is not self.ax or event.xdata is None:
            return
        curve, i = self.drag
        cx, cy = self.state['cx'], self.state['cy']
        r = max(float(np.hypot(event.xdata - cx, event.ydata - cy)), 1.0)
        self.ctrl_r[curve][i] = r
        self._apply_ctrl(curve, smooth=False)
        self._refresh_markers_quick()

    def _on_release(self, event):
        if self.drag is None:
            return
        curve, _ = self.drag
        self.drag = None
        self._apply_ctrl(curve, smooth=self.smooth_var.get())
        self._refresh_markers_quick()
        self.recompute(quiet=True)
        self.status.config(text=f'{curve} 曲线已修正并重算')

    def _apply_ctrl(self, curve, smooth):
        st_ = self.state
        th = st_['th']
        r_full = rp.periodic_interp(th[self.ctrl_idx], self.ctrl_r[curve], th)
        if smooth:
            r_full = savgol_filter(r_full, 31, 3, mode='wrap')
        key = 'rin' if curve == 'inner' else 'rout'
        st_[key] = r_full
        st_['rc'] = (st_['rin'] + st_['rout']) / 2.0
        cx, cy = st_['cx'], st_['cy']
        arr = st_[key]
        self.artists[curve].set_data(cx + arr * np.cos(th), cy + arr * np.sin(th))
        rc = st_['rc']
        self.artists['centerline'].set_data(cx + rc * np.cos(th), cy + rc * np.sin(th))

    def _refresh_markers_quick(self):
        mk = self.artists.get('markers')
        if mk is None:
            return
        curve = self.edit_var.get()
        th_c = self.state['th'][self.ctrl_idx]
        r_c = self.ctrl_r[curve]
        cx, cy = self.state['cx'], self.state['cy']
        mk.set_data(cx + r_c * np.cos(th_c), cy + r_c * np.sin(th_c))
        self.canvas.draw_idle()

    # ---------------- 重算 / 信息 ----------------
    def recompute(self, quiet=False):
        if self.state is None:
            return
        st_ = self.state
        st_['stats'] = rp.compute_stats(st_['rin'], st_['rout'],
                                        st_['th'], st_['um_per_px'])
        self._update_info()
        s = st_['stats']
        self.artists['inner'].set_label(f"inner Ø {s['inner']['dia_mean_um']:.0f} µm")
        self.artists['outer'].set_label(f"outer Ø {s['outer']['dia_mean_um']:.0f} µm")
        self.artists['centerline'].set_label(
            f"centerline Ø {s['centerline']['dia_mean_um']:.0f} µm")
        legend = self.ax.get_legend()
        if legend is not None:
            legend.remove()
        self.ax.legend(loc='upper left', fontsize=8, framealpha=0.85)
        self._info_box.set_text(self._stats_text())
        self.canvas.draw()
        if not quiet:
            self.status.config(text='已重新计算')

    def _stats_text(self):
        s = self.state['stats']
        return (f"centerline perimeter: {s['centerline_perimeter_um']:.1f} µm\n"
                f"mean(r_out - r_in): {s['mean_wall_um']:.1f} µm (wall thickness)\n"
                f"mean(D_out - D_in): {s['mean_dia_diff_um']:.1f} µm")

    def _update_info(self):
        s = self.state['stats']
        bar = self.state['bar']
        lines = [
            f"图片: {os.path.basename(self.state['img_path'])}   "
            f"标定: {bar['bar_len_px']} px = {self.scale_var.get()} µm "
            f"({self.state['um_per_px']:.4f} µm/px, "
            f"{'自动' if self.state.get('bar_source') == 'auto' else '手动'})   "
            f"中心: ({self.state['cx']:.0f}, {self.state['cy']:.0f}) px",
            f"inner_hole   Ø {s['inner']['dia_mean_um']:>7.1f} ± {s['inner']['dia_std_um']:>5.1f} µm "
            f"| 95%CI±{s['inner']['dia_ci95_mean_um']:.2f} "
            f"| circ {s['inner']['circ_ratio']:.4f} | ecc {s['inner']['eccentricity']:.4f}",
            f"outer_wall   Ø {s['outer']['dia_mean_um']:>7.1f} ± {s['outer']['dia_std_um']:>5.1f} µm "
            f"| 95%CI±{s['outer']['dia_ci95_mean_um']:.2f} "
            f"| circ {s['outer']['circ_ratio']:.4f} | ecc {s['outer']['eccentricity']:.4f}",
            f"centerline   Ø {s['centerline']['dia_mean_um']:>7.1f} ± {s['centerline']['dia_std_um']:>5.1f} µm "
            f"| 95%CI±{s['centerline']['dia_ci95_mean_um']:.2f} "
            f"| circ {s['centerline']['circ_ratio']:.4f} | ecc {s['centerline']['eccentricity']:.4f}",
            f"centerline 周长: {s['centerline_perimeter_um']:.1f} µm   "
            f"平均壁厚 mean(r_out-r_in): {s['mean_wall_um']:.1f} µm   "
            f"直径差 mean(D_out-D_in): {s['mean_dia_diff_um']:.1f} µm",
        ]
        self.info.config(state='normal')
        self.info.delete('1.0', 'end')
        self.info.insert('1.0', '\n'.join(lines))
        self.info.config(state='disabled')

    def reset_auto(self):
        """放弃手动修改的曲线, 用当前标尺重新运行自动检测"""
        if self.state is None:
            return
        path = self.state['img_path']
        try:
            scale_um = float(self.scale_var.get())
        except ValueError:
            scale_um = 1000.0
        self._start_analysis(path, scale_um,
                             self.state['bar'],
                             self.state.get('bar_source', 'auto'),
                             '重新运行自动检测...')

    def save_results(self):
        self._exporter.save()


# ---------------- 导出 ----------------
class Exporter:
    def __init__(self, app):
        self.app = app

    def save(self):
        st_ = self.app.state
        stem = os.path.splitext(os.path.basename(st_['img_path']))[0]
        out_dir = os.path.join(os.path.dirname(st_['img_path']),
                               'ring_results', stem)
        os.makedirs(out_dir, exist_ok=True)
        s = st_['stats']
        th = st_['th']
        upx = st_['um_per_px']
        rin, rout, rc = st_['rin'], st_['rout'], st_['rc']

        with open(f'{out_dir}/diameter_vs_angle.csv', 'w', newline='',
                  encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['angle_deg', 'inner_radius_px', 'inner_diameter_px',
                        'inner_radius_um', 'inner_diameter_um',
                        'outer_radius_px', 'outer_diameter_px',
                        'outer_radius_um', 'outer_diameter_um',
                        'centerline_radius_um', 'centerline_diameter_um',
                        'wall_thickness_um'])
            for a in range(len(th)):
                w.writerow([round(np.rad2deg(th[a]), 3),
                            round(rin[a], 3), round(2 * rin[a], 3),
                            round(rin[a] * upx, 2), round(2 * rin[a] * upx, 2),
                            round(rout[a], 3), round(2 * rout[a], 3),
                            round(rout[a] * upx, 2), round(2 * rout[a] * upx, 2),
                            round(rc[a] * upx, 2), round(2 * rc[a] * upx, 2),
                            round((rout[a] - rin[a]) * upx, 2)])

        bar = st_['bar']
        summary = dict(
            image=os.path.basename(st_['img_path']),
            scale_bar=dict(label_um=float(self.app.scale_var.get()),
                           length_px=bar['bar_len_px'],
                           um_per_px=round(upx, 6),
                           x0=round(bar.get('x0', 0.0), 3),
                           y0=round(bar.get('y0', bar.get('y', 0.0)), 3),
                           x1=round(bar.get('x1', 0.0), 3),
                           y1=round(bar.get('y1', bar.get('y', 0.0)), 3),
                           source=st_.get('bar_source', 'auto')),
            center_px=[round(st_['cx'], 3), round(st_['cy'], 3)],
            centerline_perimeter_um=s['centerline_perimeter_um'],
            mean_wall_thickness_um=s['mean_wall_um'],
            mean_dia_diff_um=s['mean_dia_diff_um'],
            manually_edited=True,
            results=[s['inner'], s['outer'], s['centerline']])
        with open(f'{out_dir}/summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.app.fig.savefig(f'{out_dir}/ring_calibrated_overlay.png', dpi=110)
        self.app.status.config(text=f'结果已导出 -> {out_dir}')
