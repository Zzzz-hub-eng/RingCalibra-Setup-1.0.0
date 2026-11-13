# -*- coding: utf-8 -*-
"""RingCalibra 命令行批量分析工具

用法:
  python scripts/batch_analyze.py <图片目录> [输出目录] [--scale 1000]

对目录中所有图片 (jpg/jpeg/png/tif/bmp) 运行自动流水线,
每张图输出完整图表与数据, 并生成 batch_summary.csv 汇总。
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from ringcalibra import pipeline as rp

IMG_EXTS = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp')


def process_image(img_path, out_dir, scale_um):
    res = rp.analyze_image(img_path, scale_um)
    os.makedirs(out_dir, exist_ok=True)
    th, rin, rout, rc = res['th'], res['rin'], res['rout'], res['rc']
    band_r, Rref = res['band_r'], res['Rref']
    cx, cy, upx = res['cx'], res['cy'], res['um_per_px']
    bar = res['bar']
    s = upx
    angd = np.rad2deg(th)

    stats = rp.compute_stats(rin, rout, th, upx)
    reports = [stats['inner'], stats['outer'], stats['centerline']]
    band_reports = [rp.boundary_stats(f'band{k+1}', band_r[k], th, upx)
                    for k in range(len(Rref))]
    reports += band_reports
    nb = len(Rref)

    # ---- CSV ----
    with open(f'{out_dir}/diameter_vs_angle.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f)
        head = ['angle_deg']
        for nm, arr in [('inner', rin), ('outer', rout), ('centerline', rc)]:
            head += [f'{nm}_radius_px', f'{nm}_diameter_px',
                     f'{nm}_radius_um', f'{nm}_diameter_um']
        head += ['wall_thickness_um']
        head += [f'band{k+1}_diameter_um' for k in range(nb)]
        w.writerow(head)
        for a in range(len(th)):
            row = [round(angd[a], 3)]
            for arr in (rin, rout, rc):
                row += [round(arr[a], 3), round(2 * arr[a], 3),
                        round(arr[a] * s, 2), round(2 * arr[a] * s, 2)]
            row += [round((rout[a] - rin[a]) * s, 2)]
            for k in range(nb):
                v = band_r[k][a]
                row += [round(2 * v * s, 2) if np.isfinite(v) else '']
            w.writerow(row)

    # ---- summary.json ----
    summary = dict(
        image=os.path.basename(img_path),
        scale_bar=dict(label_um=scale_um, length_px=bar['bar_len_px'],
                       x_range_px=[bar['x0'], bar['x1']], y_row_px=bar['y'],
                       um_per_px=round(upx, 6)),
        center_px=[round(cx, 3), round(cy, 3)],
        centerline_perimeter_um=stats['centerline_perimeter_um'],
        mean_wall_thickness_um=stats['mean_wall_um'],
        mean_dia_diff_um=stats['mean_dia_diff_um'],
        angular_step_deg=round(360.0 / len(th), 4), n_angles=len(th),
        band_reference_radii_um=[round(x * s, 1) for x in Rref],
        results=reports)
    with open(f'{out_dir}/summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ---- (1a) diameter_vs_angle.png ----
    fig, axes = plt.subplots(3, 1, figsize=(11, 15))
    ax = axes[0]
    ax.plot(angd, 2 * rin * s, '.', ms=1.5,
            label=f"inner Ø={reports[0]['dia_mean_um']:.0f} µm")
    ax.plot(angd, 2 * rout * s, '.', ms=1.5,
            label=f"outer Ø={reports[1]['dia_mean_um']:.0f} µm")
    ax.plot(angd, 2 * rc * s, '.', ms=1.5,
            label=f"centerline Ø={reports[2]['dia_mean_um']:.0f} µm")
    for i, c in enumerate(['C0', 'C1', 'C2']):
        r = reports[i]
        ax.axhline(r['dia_mean_um'], color=c, ls='--', lw=0.8)
        ax.fill_between(angd, r['dia_p95_lo_um'], r['dia_p95_hi_um'],
                        color=c, alpha=0.13, label=f"{r['name']} 95% interval")
    ax.set_xlabel('azimuth angle (deg)')
    ax.set_ylabel('diameter (µm)')
    ax.set_title(f'ring diameter vs azimuth '
                 f'(scale bar {scale_um:.0f} µm = {bar["bar_len_px"]} px)')
    ax.legend(loc='best', fontsize=8)

    ax = axes[1]
    for k in range(nb):
        ax.plot(angd, 2 * band_r[k] * s, '.', ms=1.5,
                label=f"band{k+1} Ø={band_reports[k]['dia_mean_um']:.0f} µm")
    ax.set_xlabel('azimuth angle (deg)')
    ax.set_ylabel('band diameter (µm)')
    ax.set_title('concentric ring (band) diameter vs azimuth angle')
    ax.legend(loc='best', fontsize=7, ncol=2)

    ax = axes[2]
    ax.plot(rin * np.cos(th) * s, rin * np.sin(th) * s, '.', ms=1.5, label='inner')
    ax.plot(rout * np.cos(th) * s, rout * np.sin(th) * s, '.', ms=1.5, label='outer')
    ax.plot(rc * np.cos(th) * s, rc * np.sin(th) * s, '.', ms=1.0, label='centerline')
    ax.set_aspect('equal')
    ax.set_xlabel('x (µm)')
    ax.set_ylabel('y (µm)')
    ax.set_title('detected boundaries (Cartesian, calibrated)')
    ax.legend(loc='best', fontsize=8)
    plt.tight_layout()
    plt.savefig(f'{out_dir}/diameter_vs_angle.png', dpi=130)
    plt.close()

    # ---- (1b) polar_map.png ----
    R = np.arange(0, rp.R_MAX, 0.5)
    i_w0 = int(np.searchsorted(R, 900))
    i_w1 = int(np.searchsorted(R, 1700))
    samp = rp.radial(res['g'], cx, cy, R, th)
    fig, ax = plt.subplots(figsize=(11, 5))
    im_ = ax.imshow(samp[i_w0:i_w1].T, aspect='auto', cmap='gray', origin='lower',
                    extent=[0, 360, R[i_w0] * s, R[i_w1] * s])
    ax.plot(angd, rin * s, 'r-', lw=0.8, label='inner')
    ax.plot(angd, rout * s, 'r-', lw=0.8, label='outer')
    for k in range(nb):
        ax.plot(angd, band_r[k] * s, lw=0.6, alpha=0.8, label=f'band{k+1}')
    ax.set_xlabel('azimuth angle (deg)')
    ax.set_ylabel('radius (µm)')
    ax.set_title('polar (r-θ) unwrapped map, calibrated')
    ax.legend(fontsize=6, ncol=4)
    plt.colorbar(im_, ax=ax, label='intensity')
    plt.tight_layout()
    plt.savefig(f'{out_dir}/polar_map.png', dpi=130)
    plt.close()

    # ---- (3) centerline_diameter_vs_angle.png ----
    rep_c = reports[2]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(angd, 2 * rc * s, '.', ms=2, color='C2',
            label='(D_inner + D_outer)/2 per angle')
    ax.axhline(rep_c['dia_mean_um'], color='k', ls='--', lw=1,
               label=f"mean = {rep_c['dia_mean_um']:.1f} µm "
                     f"(std {rep_c['dia_std_um']:.1f})")
    ax.fill_between(angd, rep_c['dia_p95_lo_um'], rep_c['dia_p95_hi_um'],
                    color='C2', alpha=0.18,
                    label=f"95% range [{rep_c['dia_p95_lo_um']:.0f}, "
                          f"{rep_c['dia_p95_hi_um']:.0f}] µm")
    ax.set_xlabel('azimuth angle (deg)')
    ax.set_ylabel('ring centerline diameter (µm)')
    ax.set_title(f"ring center diameter (D_in+D_out)/2 vs azimuth | "
                 f"95%CI of mean ±{rep_c['dia_ci95_mean_um']:.2f} µm, "
                 f"circularity {rep_c['circ_ratio']:.3f}")
    ax.legend(loc='best', fontsize=8)
    ax.set_xlim(0, 360)
    plt.tight_layout()
    plt.savefig(f'{out_dir}/centerline_diameter_vs_angle.png', dpi=140)
    plt.close()

    # ---- (2a) ring_calibrated.png ----
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5))
    ax = axes[0]
    ax.plot(angd, rin * s, 'r.', ms=1.5,
            label=f"inner r(θ), mean {reports[0]['r_mean_um']:.0f} µm")
    ax.plot(angd, rout * s, 'b.', ms=1.5,
            label=f"outer r(θ), mean {reports[1]['r_mean_um']:.0f} µm")
    ax.axhline(reports[0]['r_mean_um'], color='r', ls='--', lw=0.8)
    ax.axhline(reports[1]['r_mean_um'], color='b', ls='--', lw=0.8)
    ax.set_xlabel('azimuth angle (deg)')
    ax.set_ylabel('radius (µm)')
    ax.set_title('inner/outer radius vs azimuth (calibrated)')
    ax.legend(fontsize=8)
    ax.set_xlim(0, 360)
    ax = axes[1]
    thf = np.linspace(0, 2 * np.pi, 721)
    for rep, r_arr, c in ((reports[0], rin, 'r'),
                          (reports[1], rout, 'b'),
                          (reports[2], rc, 'g')):
        ax.plot(r_arr * np.cos(th) * s, r_arr * np.sin(th) * s, '.',
                ms=1, color=c, alpha=0.5)
        a_e = rep['ellipse_a_um']
        b_e = rep['ellipse_b_um']
        ph = np.deg2rad(rep['ellipse_phi_deg'])
        re = a_e * b_e / np.sqrt((b_e * np.cos(thf - ph)) ** 2
                                 + (a_e * np.sin(thf - ph)) ** 2)
        ax.plot(re * np.cos(thf), re * np.sin(thf), '-', lw=1.2, color=c,
                label=f"{rep['name']} ellipse a={a_e:.0f} b={b_e:.0f} µm")
    ax.set_aspect('equal')
    ax.set_xlabel('x (µm)')
    ax.set_ylabel('y (µm)')
    ax.set_title('ellipse fits (calibrated)')
    ax.legend(fontsize=8)
    plt.suptitle(f'Inner/outer ring calibration | scale bar {scale_um:.0f} µm '
                 f'= {bar["bar_len_px"]} px ({upx:.4f} µm/px)', fontsize=11)
    plt.tight_layout()
    plt.savefig(f'{out_dir}/ring_calibrated.png', dpi=140)
    plt.close()

    # ---- (2b) ring_calibrated_overlay.png ----
    fig, ax = plt.subplots(figsize=(10.5, 10.8))
    ax.imshow(np.array(res['im_rgb']), origin='upper')
    ax.plot(cx + rin * np.cos(th), cy + rin * np.sin(th), 'r-', lw=1.2,
            label=f"inner Ø {reports[0]['dia_mean_um']:.0f} µm")
    ax.plot(cx + rout * np.cos(th), cy + rout * np.sin(th), 'b-', lw=1.2,
            label=f"outer Ø {reports[1]['dia_mean_um']:.0f} µm")
    ax.plot(cx + rc * np.cos(th), cy + rc * np.sin(th), 'g--', lw=1.0,
            label=f"centerline Ø {reports[2]['dia_mean_um']:.0f} µm")
    ax.plot([bar['x0'], bar['x1']], [bar['y'], bar['y']], '-',
            color='deepskyblue', lw=3)
    ax.plot(cx, cy, 'k+', ms=12, mew=2)
    ax.text(bar['x0'], bar['y'] - 90,
            f'scale bar: {scale_um:.0f} µm = {bar["bar_len_px"]} px\n'
            f'({upx:.4f} µm/px)', fontsize=9, bbox=dict(fc='white', alpha=0.85))
    ax.text(0.01, 0.01,
            f"centerline perimeter: {stats['centerline_perimeter_um']:.1f} µm\n"
            f"mean(r_out - r_in): {stats['mean_wall_um']:.1f} µm (wall thickness)\n"
            f"mean(D_out - D_in): {stats['mean_dia_diff_um']:.1f} µm",
            transform=ax.transAxes, va='bottom', fontsize=10,
            bbox=dict(fc='lightyellow', alpha=0.9))
    ax.legend(loc='upper left', fontsize=9, framealpha=0.85)
    ax.set_title(f'Calibrated ring overlay | center ({cx:.0f},{cy:.0f}) px | '
                 f'inner Ø {reports[0]["dia_mean_um"]:.0f} µm, '
                 f'outer Ø {reports[1]["dia_mean_um"]:.0f} µm')
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(f'{out_dir}/ring_calibrated_overlay.png', dpi=110)
    plt.close()

    print(f"  inner Ø {reports[0]['dia_mean_um']:.1f} µm | "
          f"outer Ø {reports[1]['dia_mean_um']:.1f} µm | "
          f"centerline Ø {reports[2]['dia_mean_um']:.1f} µm | "
          f"perimeter {stats['centerline_perimeter_um']:.1f} µm | "
          f"wall {stats['mean_wall_um']:.1f} µm | bands {nb}")
    return reports, stats, upx


def main():
    ap = argparse.ArgumentParser(description='RingCalibra 命令行批量分析')
    ap.add_argument('img_dir', help='图片目录')
    ap.add_argument('out_dir', nargs='?', default=None,
                    help='输出目录 (默认 <图片目录>/batch_results)')
    ap.add_argument('--scale', type=float, default=1000.0,
                    help='标尺标注长度 µm (默认 1000)')
    args = ap.parse_args()

    img_dir = os.path.abspath(args.img_dir)
    out_root = os.path.abspath(args.out_dir
                               or os.path.join(img_dir, 'batch_results'))
    files = sorted(f for f in os.listdir(img_dir)
                   if f.lower().endswith(IMG_EXTS))
    if not files:
        print(f'no images found in {img_dir}')
        return
    os.makedirs(out_root, exist_ok=True)

    rows = []
    for i, fn in enumerate(files):
        stem = os.path.splitext(fn)[0]
        print(f'\n[{i + 1}/{len(files)}] {fn}')
        try:
            reports, stats, upx = process_image(
                os.path.join(img_dir, fn),
                os.path.join(out_root, stem), args.scale)
        except Exception as e:
            print(f'  FAILED: {type(e).__name__}: {e}')
            rows.append(dict(image=fn, boundary='', error=str(e)))
            continue
        for r in reports:
            rows.append(dict(image=fn, um_per_px=upx, boundary=r['name'],
                             n=r['n'],
                             dia_mean_um=r['dia_mean_um'],
                             dia_std_um=r['dia_std_um'],
                             dia_ci95_mean_um=r['dia_ci95_mean_um'],
                             dia_p95_lo_um=r['dia_p95_lo_um'],
                             dia_p95_hi_um=r['dia_p95_hi_um'],
                             circ_ratio=r['circ_ratio'],
                             eccentricity=r['eccentricity'],
                             centerline_perimeter_um=stats['centerline_perimeter_um'],
                             mean_wall_um=stats['mean_wall_um'],
                             mean_dia_diff_um=stats['mean_dia_diff_um'],
                             error=''))

    cols = ['image', 'boundary', 'um_per_px', 'n', 'dia_mean_um', 'dia_std_um',
            'dia_ci95_mean_um', 'dia_p95_lo_um', 'dia_p95_hi_um',
            'circ_ratio', 'eccentricity',
            'centerline_perimeter_um', 'mean_wall_um', 'mean_dia_diff_um',
            'error']
    with open(f'{out_root}/batch_summary.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f'\nbatch done: {len(files)} image(s), summary -> '
          f'{out_root}/batch_summary.csv')


if __name__ == '__main__':
    main()
