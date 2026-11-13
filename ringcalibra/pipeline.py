# -*- coding: utf-8 -*-
"""
环形样品显微照片自动分析流水线 (纯计算, 无绘图).
供交互式编辑器 ring_editor_app.py 调用, 也可独立使用。

流水线:
  1. 蓝色 scale bar 颜色检测 -> um/px 标定
  2. 中心白色孔洞定位 + 圆心迭代精化
  3. 0.25° 步长径向采样, 内孔/外壁/同心环暗带检测
  4. 角度向去尖刺 + NaN 填充
  5. 统计: 直径均值/标准差/95%CI/95%区间, 圆度, 椭圆拟合,
     中心线周长, 平均壁厚
"""
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.signal import savgol_filter, find_peaks
from scipy.optimize import least_squares
from scipy import stats as st

NTH = 1440          # 角度采样数 (0.25° 步长)
R_MAX = 2000.0      # 最大径向采样半径 (px)


# ---------------- 基础几何 ----------------
def radial(g, cx, cy, R, th):
    """从 (cx, cy) 沿角度 th、半径 R 双线性采样灰度图, 返回 [len(R), len(th)]"""
    rr, tt = np.meshgrid(R, th, indexing='ij')
    xx = cx + rr * np.cos(tt)
    yy = cy + rr * np.sin(tt)
    return ndimage.map_coordinates(g, [yy, xx], order=1, mode='nearest')


def fit_circle(xs, ys):
    def resid(p):
        cx, cy, R = p
        return np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2) - R
    return least_squares(resid, [xs.mean(), ys.mean(), 900.0], method='lm').x


def periodic_interp(th_ctrl, r_ctrl, th_full):
    """周期插值: 控制点 -> 全角度曲线 (自动跳过无效点)"""
    ok = np.isfinite(r_ctrl) & np.isfinite(th_ctrl)
    tc, rc = th_ctrl[ok], r_ctrl[ok]
    t2 = np.concatenate([tc - 2 * np.pi, tc, tc + 2 * np.pi])
    r2 = np.concatenate([rc] * 3)
    return np.interp(th_full, t2, r2)


def fill_nan_periodic(r):
    """沿角度方向插值填充 NaN"""
    ok = ~np.isnan(r)
    if ok.all():
        return r
    th = np.linspace(0, 2 * np.pi, len(r), endpoint=False)
    tv = th[ok]
    t2 = np.concatenate([tv - 2 * np.pi, tv, tv + 2 * np.pi])
    r2 = np.concatenate([r[ok]] * 3)
    return np.interp(th, t2, r2)


def despike(r_arr, tol=40):
    """角度向去尖刺: 偏离滚动中值超过 tol 的点用中值替代"""
    r = r_arr.copy()
    ok = ~np.isnan(r)
    med_f = ndimage.median_filter(np.where(ok, r, np.nanmedian(r)), size=7, mode='wrap')
    bad = ok & (np.abs(r - med_f) > tol)
    r[bad] = med_f[bad]
    return r


# ---------------- 边缘检测 ----------------
def _inner_radius(samp, R):
    out = np.full(samp.shape[1], np.nan)
    i0 = int(np.searchsorted(R, 600))
    for a in range(samp.shape[1]):
        s = savgol_filter(samp[:, a], 21, 3)
        i = np.where(s[i0:] < 180)[0]
        if len(i):
            out[a] = R[i0 + i[0]]
    return out


def _outer_radius(samp, R):
    out = np.full(samp.shape[1], np.nan)
    i0 = int(np.searchsorted(R, 1000))
    i1 = int(np.searchsorted(R, 1850))
    for a in range(samp.shape[1]):
        s = savgol_filter(samp[:, a], 41, 3)
        w = s[i0:i1]
        dark_idx = np.where((w > 40) & (w < 170))[0]
        if len(dark_idx) == 0:
            continue
        for di in dark_idx[::-1]:
            last_dark = i0 + di
            j = np.where(s[last_dark:] > 235)[0]
            if len(j) and j[0] < 300:
                out[a] = R[last_dark + j[0]]
                break
    return out


# ---------------- 标定与定位 ----------------
def detect_scale_bar(im_rgb, scale_um=1000.0):
    rgb = np.array(im_rgb, dtype=np.int32)
    R_, G_, B_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    blue = (B_ > 150) & (B_ - R_ > 80) & (B_ - G_ > 80)
    lab, n = ndimage.label(blue)
    if n == 0:
        raise ValueError('未找到蓝色 scale bar (请确认图片右下角标尺)')
    sizes = ndimage.sum(blue, lab, range(1, n + 1))
    best = int(np.argmax(sizes)) + 1
    ys, xs = np.nonzero(lab == best)
    x0, x1 = int(xs.min()), int(xs.max())
    y_mid = int(np.median(ys))
    return dict(bar_len_px=x1 - x0 + 1, x0=x0, x1=x1,
                y=y_mid, y0=y_mid, y1=y_mid,
                um_per_px=scale_um / (x1 - x0 + 1))


def make_bar(p0, p1, scale_um):
    """由手动点选的两个端点创建标尺字典"""
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    length = float(np.hypot(x1 - x0, y1 - y0))
    if length < 5:
        raise ValueError('标尺长度过短 (<5 px), 请重新选择两端点')
    # 与自动检测一致: 采用"含端点像素计数"约定 (端距 + 1 px)
    bar_len_px = int(round(length + 1.0))
    return dict(bar_len_px=bar_len_px,
                x0=x0, y0=y0, x1=x1, y1=y1,
                y=0.5 * (y0 + y1),
                um_per_px=float(scale_um) / bar_len_px)


def normalize_bar(bar, scale_um):
    """补全标尺字典字段 (兼容仅含 x0/x1/y 的自动检测结果)"""
    b = dict(bar)
    y = b.get('y', 0.5 * (b.get('y0', 0.0) + b.get('y1', 0.0)))
    b['y'] = y
    b.setdefault('y0', y)
    b.setdefault('y1', y)
    if not b.get('bar_len_px'):
        b['bar_len_px'] = int(round(np.hypot(b['x1'] - b['x0'],
                                             b['y1'] - b['y0'])))
    if not b.get('um_per_px'):
        b['um_per_px'] = float(scale_um) / b['bar_len_px']
    return b


def refine_center(g):
    """中心白色孔洞定位 + 圆心迭代精化"""
    H, W = g.shape
    gm = ndimage.median_filter(g, size=17)
    dark_c = ndimage.binary_closing(gm < 150, structure=np.ones((25, 25)))
    lab2, _ = ndimage.label(~dark_c)
    mask = (lab2 == lab2[H // 2, W // 2])
    ys0, xs0 = np.nonzero(mask)
    cx, cy = xs0.mean(), ys0.mean()
    th_it = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    R_it = np.arange(0, 1500, 0.5)
    for _ in range(3):
        rin_it = _inner_radius(radial(g, cx, cy, R_it, th_it), R_it)
        ok = ~np.isnan(rin_it)
        cx, cy, _ = fit_circle(cx + rin_it[ok] * np.cos(th_it[ok]),
                               cy + rin_it[ok] * np.sin(th_it[ok]))
    return float(cx), float(cy)


# ---------------- 统计 ----------------
def ellipse_fit(r, t):
    ok = ~np.isnan(r)
    rr, tt = r[ok], t[ok]

    def resid(p):
        a, b, phi = p
        d = tt - phi
        return rr - a * b / np.sqrt((b * np.cos(d)) ** 2 + (a * np.sin(d)) ** 2)
    return least_squares(resid, [np.nanmean(r)] * 2 + [0.0], method='lm').x


def boundary_stats(name, r, t, um_per_px):
    ok = ~np.isnan(r)
    rr = r[ok]
    dia = 2 * rr
    n_ = rr.size
    sd = dia.std(ddof=1)
    ci = st.t.ppf(0.975, n_ - 1) * sd / np.sqrt(n_)
    lo, hi = np.percentile(dia, [2.5, 97.5])
    a, b, phi = ellipse_fit(r, t)
    ecc = np.sqrt(max(0, 1 - (b / a) ** 2)) if a >= b else np.sqrt(max(0, 1 - (a / b) ** 2))
    return dict(name=name, n=n_,
                dia_mean_um=round(dia.mean() * um_per_px, 1),
                dia_std_um=round(sd * um_per_px, 1),
                dia_ci95_mean_um=round(ci * um_per_px, 2),
                dia_p95_lo_um=round(lo * um_per_px, 1),
                dia_p95_hi_um=round(hi * um_per_px, 1),
                r_mean_um=round(rr.mean() * um_per_px, 1),
                r_min_um=round(rr.min() * um_per_px, 1),
                r_max_um=round(rr.max() * um_per_px, 1),
                circ_ratio=round(rr.min() / rr.max(), 5),
                ellipse_a_um=round(a * um_per_px, 1),
                ellipse_b_um=round(b * um_per_px, 1),
                eccentricity=round(ecc, 5),
                ellipse_phi_deg=round(phi * 180 / np.pi % 180, 2))


def compute_stats(rin, rout, th, um_per_px):
    """由 (可手动修正后的) rin/rout 重新计算全部统计量"""
    rc = (rin + rout) / 2.0
    rep_in = boundary_stats('inner_hole', rin, th, um_per_px)
    rep_out = boundary_stats('outer_wall', rout, th, um_per_px)
    rep_c = boundary_stats('centerline', rc, th, um_per_px)

    # 中心线周长: 沿实测中心线闭合曲线逐段累加 (µm)
    xc = rc * np.cos(th)
    yc = rc * np.sin(th)
    perimeter = float((np.sum(np.hypot(np.diff(xc), np.diff(yc)))
                       + np.hypot(xc[0] - xc[-1], yc[0] - yc[-1])) * um_per_px)
    # 内外差平均值
    mean_wall = float(np.nanmean(rout - rin) * um_per_px)

    return dict(inner=rep_in, outer=rep_out, centerline=rep_c,
                centerline_perimeter_um=round(perimeter, 1),
                mean_wall_um=round(mean_wall, 1),
                mean_dia_diff_um=round(2.0 * mean_wall, 1))


# ---------------- 完整流水线 ----------------
def analyze_image(img_path, scale_um=1000.0, progress=None,
                  bar=None, bar_source=None):
    """对单张图片运行自动分析, 返回状态字典 (不含绘图)

    bar: 可选标尺字典 (手动标定时传入, 含 x0/y0/x1/y1 或 x0/x1/y)
    bar_source: 'auto' / 'manual', 仅用于结果标注
    """
    def report(pct, msg):
        if progress:
            progress(pct, msg)

    report(5, '读取图片...')
    im_rgb = Image.open(img_path).convert('RGB')
    g = np.array(im_rgb.convert('L'), dtype=np.float64)

    if bar is None:
        report(15, '检测 scale bar...')
        bar = detect_scale_bar(im_rgb, scale_um)
        bar_source = bar_source or 'auto'
    else:
        report(15, '使用手动标尺...' if bar_source != 'auto' else '使用指定标尺...')
        bar = normalize_bar(bar, scale_um)
        bar_source = bar_source or 'manual'
    um_per_px = bar['um_per_px']

    report(30, '定位圆心...')
    cx, cy = refine_center(g)

    report(45, '径向采样 (0.25°)...')
    th = np.linspace(0, 2 * np.pi, NTH, endpoint=False)
    R = np.arange(0, R_MAX, 0.5)
    samp = radial(g, cx, cy, R, th)

    report(65, '检测内孔/外壁边界...')
    rin = fill_nan_periodic(despike(_inner_radius(samp, R)))
    rout = fill_nan_periodic(despike(_outer_radius(samp, R)))
    rc = (rin + rout) / 2.0

    report(80, '检测同心环暗带...')
    med = np.median(samp, axis=1)
    i_w0 = int(np.searchsorted(R, 900))
    i_w1 = int(np.searchsorted(R, 1700))
    pk, _ = find_peaks(-savgol_filter(med, 41, 3)[i_w0:i_w1], distance=60, prominence=6)
    Rref = R[i_w0 + pk]
    band_r = []
    for k in range(len(Rref)):
        arr = np.full(NTH, np.nan)
        band_r.append(arr)
    for a in range(NTH):
        s = savgol_filter(samp[:, a], 41, 3)
        mk, _ = find_peaks(-s[i_w0:i_w1], distance=50, prominence=10)
        for p in mk:
            rp = R[i_w0 + p]
            k = int(np.argmin(np.abs(Rref - rp)))
            if abs(Rref[k] - rp) < 60 and np.isnan(band_r[k][a]):
                band_r[k][a] = rp

    report(95, '计算统计量...')
    stats = compute_stats(rin, rout, th, um_per_px)

    report(100, '完成')
    return dict(img_path=img_path, im_rgb=im_rgb, g=g,
                th=th, rin=rin, rout=rout, rc=rc,
                band_r=band_r, Rref=Rref,
                cx=cx, cy=cy, um_per_px=um_per_px, bar=bar,
                bar_source=bar_source, stats=stats)
