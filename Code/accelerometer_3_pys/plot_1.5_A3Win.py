"""VibeCheck three-sensor paired-capture plots, version 1.5 (Windows friendly).

Install: py -m pip install numpy pandas matplotlib scipy
Run: py plot_1.5_A3Win.py "C:/data/sweep.csv" --no-show
With no path: newest sweep beside script, then working folder, then file picker.
Exactly three PNGs: PID/analysis; PID2/bath_z_comparison; PID2/time_traces.
Time traces wrap at 10 frequencies per band, with three sensor rows per band.

AXES: baths vertical Z, planar sqrt(std(X)^2+std(Y)^2); shaker vertical Y,
planar sqrt(std(X)^2+std(Z)^2). Change SHAKER_VERTICAL_AXIS if mounting differs.
All amplitudes are AC RMS (DC removed). Average bath = arithmetic mean of
individual sensor RMS amplitudes, never RMS of averaged time-domain signals.
Bath statistics use BATH_PAIR only; shaker uses SHAKER_PAIR only. Bath 1 from
SHAKER_PAIR is used ONLY for the phase-to-phase reference-stability panel.
Cross-phase transmissibilities are sequential amplitude ratios, not simultaneous
transfer functions. They are unavailable if commanded drive differs across phases.

THD_2-5 (%) = 100*sqrt(A2^2+A3^2+A4^2+A5^2)/A1, using harmonic RMS amplitudes.
Bath THD uses the mean of the two bath amplitudes AT EACH harmonic. This is an
aggregate amplitude-spectrum metric, NOT THD of a spatially averaged waveform.
A timestamp-based least-squares sine/cosine fit includes DC and a linear trend.
The fundamental is fitted near the commanded frequency to reduce leakage bias.
The same harmonic orders are used for every valid point: no silent truncation
at Nyquist. Missing/gapped/undersampled records or weak fundamentals give NaN.
THD excludes broadband noise and harmonics above order 5; it is not THD+N.
Sensor bandwidth, aliasing and timestamp accuracy still limit interpretation.
Definition reference: https://knowledge.ni.com/KnowledgeArticleDetails?id=kA03q000000YHDjCAO&l=en-US

Waveforms show raw sensor X/Y/Z with each full-block mean removed. Both baths
share a time origin from their common capture; shaker uses its own later block.
Relative time in those separate blocks must NOT be used for bath/shaker phase.
Legacy files without Phase are treated as a single simultaneous capture; shaker
and cross-phase diagnostics are unavailable if their channels/phases are absent.
"""
import argparse
import hashlib
import math
from pathlib import Path
import sys
import textwrap
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
import matplotlib
if '--no-show' in sys.argv:
    matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUTPUT_DIR = 'PID'
SECOND_OUTPUT_DIR = 'PID2'
SHOW_PLOTS = True
SHAKER_VERTICAL_AXIS = 'Y'
THD_MAX_HARMONIC = 5
MIN_RMS_G = 0.001             # Denominators below this are unavailable, not floored.
MAX_GAP_FACTOR = 1.5         # Relative to median within-block sample interval.
FREQUENCIES_PER_ROW = 10
TRACE_PERIODS = 5
SUMMARY_DPI = 240
TRACE_DPI = 150
COLORS = {'bath1': 'purple', 'bath2': 'darkorange', 'bath': '#d94b42',
          'shaker': '#285a83', 'planar_ratio': '#128572', 'z_transfer': '#9361b4'}


def output_path(csv_filename, suffix, output_dir=OUTPUT_DIR):
    source = Path(csv_filename).resolve()
    folder = source.parent / output_dir
    folder.mkdir(parents=True, exist_ok=True)
    token = hashlib.sha256(source.name.encode('utf-8')).hexdigest()[:8]
    return folder / f'{source.stem[:48]}_{token}_{suffix}.png'


def finish_figure(fig, destination, dpi=SUMMARY_DPI):
    fig.savefig(destination, dpi=dpi, bbox_inches='tight')
    print(f'Saved: {destination}')
    if SHOW_PLOTS:
        plt.show()
    plt.close(fig)
    return destination


def load_sweep_csv(filename):
    df = pd.read_csv(filename, encoding='utf-8-sig')
    df.columns = df.columns.str.strip()
    required = ['Timestamp', 'Freq', 'Drive_Amp', 'Channel', 'X', 'Y', 'Z']
    missing = set(required) - set(df.columns)
    if missing or df.empty:
        raise ValueError(f'Empty CSV or missing columns: {sorted(missing)}')
    numeric = required + [c for c in ('Timestamp_us', 'Window_Start_us', 'Window_End_us') if c in df]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors='raise')
        if not np.isfinite(df[c]).all():
            raise ValueError(f'Non-finite values in {c}')
    if (df.Freq <= 0).any() or (df.Channel % 1 != 0).any():
        raise ValueError('Frequency must be positive and channel IDs must be integers')
    if 'Timestamp_us' in df:
        if not np.allclose(df.Timestamp, df.Timestamp_us / 1e6, rtol=0, atol=1e-6):
            raise ValueError('Timestamp and Timestamp_us disagree')
        df['Timestamp'] = df.Timestamp_us / 1e6
    paired = 'Phase' in df
    if paired:
        if not df.Phase.isin(['BATH_PAIR', 'SHAKER_PAIR']).all():
            raise ValueError('Unknown or missing Phase labels')
        valid = ((df.Phase.eq('BATH_PAIR') & df.Channel.isin([0, 2])) |
                 (df.Phase.eq('SHAKER_PAIR') & df.Channel.isin([0, 4])))
        if not valid.all():
            raise ValueError('Unexpected channel in a paired capture')
        for col in ('Step', 'Window_Start_us', 'Window_End_us'):
            if col in df and (df.groupby(['Freq', 'Phase'])[col].nunique() > 1).any():
                raise ValueError(f'Multiple {col} values at the same frequency/phase; do not pool runs')
        if {'Window_Start_us', 'Window_End_us'} <= set(df.columns):
            us = df.Timestamp.to_numpy() * 1e6
            if ((us < df.Window_Start_us - .01) | (us >= df.Window_End_us + .01)).any():
                raise ValueError('Samples outside declared capture windows')
    else:
        df['Phase'] = 'LEGACY'
        warnings.warn('Legacy CSV: no capture phases; treating recorded channels as simultaneous.')
    for key, g in df.groupby(['Freq', 'Phase', 'Channel'], sort=False):
        if (np.diff(g.Timestamp.to_numpy()) <= 0).any():
            raise ValueError(f'Duplicate/backward timestamps in {key}; refusing to reorder records')
    df.attrs['paired'] = paired
    return df


def ac_rms(g, axis):
    return float(g[axis].std(ddof=0)) if len(g) >= 2 else np.nan


def planar(g, vertical):
    axes = [a for a in 'XYZ' if a != vertical]
    return float(np.hypot(ac_rms(g, axes[0]), ac_rms(g, axes[1])))


def safe_ratio(numerator, denominator):
    if not np.isfinite(numerator) or not np.isfinite(denominator) or denominator < MIN_RMS_G:
        return np.nan
    return numerator / denominator


def harmonic_spectrum(g, axis, commanded_frequency):
    """Return RMS amplitudes H1..H5 and fitted f0, or NaNs with a reason."""
    invalid = np.full(THD_MAX_HARMONIC, np.nan)
    if len(g) < 100:
        return invalid, np.nan, 'insufficient samples'
    t = g.Timestamp.to_numpy(dtype=float)
    t = t - t[0]
    y = g[axis].to_numpy(dtype=float)
    dt = np.diff(t)
    duration = t[-1]
    if duration * commanded_frequency < 10 or (dt <= 0).any():
        return invalid, np.nan, 'short or nonmonotonic record'
    if dt.max() > MAX_GAP_FACTOR * np.median(dt):
        return invalid, np.nan, 'sample gap'
    measured_rate = (len(t) - 1) / duration
    span = max(0.5, commanded_frequency * .01)
    lo, hi = max(.01, commanded_frequency - span), commanded_frequency + span
    # Conservative bandwidth check: all five harmonics below 95% of Nyquist.
    if THD_MAX_HARMONIC * hi >= .95 * measured_rate / 2:
        return invalid, np.nan, 'insufficient bandwidth for all five harmonics'
    # Interpolation is used only to locate an FFT seed. The actual fit uses raw times.
    regular = np.linspace(0, duration, len(t))
    spectrum = np.abs(np.fft.rfft(np.interp(regular, t, y - y.mean()) * np.hanning(len(t))))
    bins = np.fft.rfftfreq(len(t), d=duration / (len(t) - 1))
    eligible = np.flatnonzero((bins >= lo) & (bins <= hi))
    if not len(eligible):
        return invalid, np.nan, 'no fundamental search bins'
    seed = bins[eligible[np.argmax(spectrum[eligible])]]
    centered = t - duration / 2
    nuisance = np.column_stack((np.ones(len(t)), centered / duration))
    y0 = y - nuisance @ np.linalg.lstsq(nuisance, y, rcond=None)[0]
    def objective(f):
        angle = 2 * np.pi * f * centered
        design = np.column_stack((nuisance, np.sin(angle), np.cos(angle)))
        residual = y0 - design @ np.linalg.lstsq(design, y0, rcond=None)[0]
        return float(residual @ residual)
    lower, upper = max(lo, seed - .7 / duration), min(hi, seed + .7 / duration)
    fit = minimize_scalar(objective, bounds=(lower, upper), method='bounded',
                          options={'xatol': 1e-7})
    if not fit.success:
        return invalid, np.nan, 'fundamental fit failed'
    f0 = float(fit.x)
    columns = [nuisance[:, 0], nuisance[:, 1]]
    for h in range(1, THD_MAX_HARMONIC + 1):
        a = 2 * np.pi * h * f0 * centered
        columns.extend([np.sin(a), np.cos(a)])
    design = np.column_stack(columns)
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    if rank != design.shape[1]:
        return invalid, f0, 'rank-deficient harmonic fit'
    amplitudes = np.hypot(coefficients[2::2], coefficients[3::2]) / np.sqrt(2)
    if amplitudes[0] < MIN_RMS_G:
        return invalid, f0, 'weak fundamental'
    return amplitudes, f0, ''


def thd_percent(amplitudes):
    return 100 * safe_ratio(float(np.linalg.norm(amplitudes[1:])), amplitudes[0])


def select_blocks(group, paired):
    empty = group.iloc[:0]
    def get(ch, phase):
        return group[(group.Channel == ch) & (group.Phase == (phase if paired else 'LEGACY'))]
    return get(0, 'BATH_PAIR'), get(2, 'BATH_PAIR'), get(4, 'SHAKER_PAIR'), (get(0, 'SHAKER_PAIR') if paired else empty)


def process_sweep_data(source):
    raw = load_sweep_csv(source) if not isinstance(source, pd.DataFrame) else source
    paired = raw.attrs.get('paired', False)
    rows = []
    for freq, group in raw.groupby('Freq', sort=True):
        b1, b2, shaker, ref = select_blocks(group, paired)
        z1, z2, zs = ac_rms(b1, 'Z'), ac_rms(b2, 'Z'), ac_rms(shaker, SHAKER_VERTICAL_AXIS)
        p1, p2, ps = planar(b1, 'Z'), planar(b2, 'Z'), planar(shaker, SHAKER_VERTICAL_AXIS)
        bz, bp = (z1 + z2) / 2, (p1 + p2) / 2
        fixed_drive = np.ptp(group.Drive_Amp.to_numpy()) <= 1e-7
        if not fixed_drive:
            warnings.warn(f'{freq:g} Hz: drive changes across records; cross-phase ratios unavailable')
        a1, f1, e1 = harmonic_spectrum(b1, 'Z', freq)
        a2, f2, e2 = harmonic_spectrum(b2, 'Z', freq)
        ash, fs, es = harmonic_spectrum(shaker, SHAKER_VERTICAL_AXIS, freq)
        for label, error in [('Bath 1', e1), ('Bath 2', e2), ('shaker', es)]:
            if error:
                warnings.warn(f'{freq:g} Hz {label}: THD unavailable ({error})')
        rows.append(dict(Freq=freq, Drive_Amp=group.Drive_Amp.iloc[0] if fixed_drive else np.nan,
                         Bath1_Z=z1, Bath2_Z=z2, Avg_Bath_Z=bz, Avg_Bath_Planar=bp,
                         Shaker_Z=zs, Shaker_Planar=ps,
                         Bath_Planar_Z=safe_ratio(bp, bz), Shaker_Planar_Z=safe_ratio(ps, zs),
                         Planar_Transfer=safe_ratio(bp, ps) if fixed_drive else np.nan,
                         Z_Transfer=safe_ratio(bz, zs) if fixed_drive else np.nan,
                         Bath_THD=thd_percent((a1 + a2) / 2), Shaker_THD=thd_percent(ash),
                         Reference_Z_Change=100*(safe_ratio(ac_rms(ref, 'Z'), z1)-1),
                         Reference_Planar_Change=100*(safe_ratio(planar(ref, 'Z'), p1)-1),
                         Bath1_F0=f1, Bath2_F0=f2, Shaker_F0=fs))
    return pd.DataFrame(rows)


def decorate(ax, title, ylabel):
    ax.set_title(title, fontsize=13, pad=10)
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel(ylabel)
    ax.grid(True, which='both', ls='--', alpha=.3)


def plot_line(ax, x, y, label, color, log=False, **kwargs):
    values = np.asarray(y, dtype=float)
    if log:
        values = np.where(values > 0, values, np.nan)
    ax.plot(x, values, marker='o', markersize=3, lw=1.7, label=label, color=color, **kwargs)


def generate_plots(summary, csv_filename, raw=None):
    raw = load_sweep_csv(csv_filename) if raw is None else raw
    f = summary.Freq
    fig, axs = plt.subplots(2, 3, figsize=(24, 13))
    fig.suptitle('Vibration sweep: bath uniformity, isolation and waveform quality', fontsize=20, weight='bold', y=.98)
    fig.text(.5, .935, textwrap.fill(Path(csv_filename).name, 140), ha='center', fontsize=9)
    ax = axs[0, 0]
    plot_line(ax, f, summary.Bath1_Z, 'Bath 1 Z', COLORS['bath1'])
    plot_line(ax, f, summary.Bath2_Z, 'Bath 2 Z', COLORS['bath2'])
    ax.fill_between(f, summary.Bath1_Z, summary.Bath2_Z, color='red', alpha=.12, label='Uniformity gap')
    decorate(ax, 'Bath sensor uniformity', 'Vertical AC RMS (g)'); ax.legend(fontsize=9)
    ax = axs[0, 1]
    plot_line(ax, f, summary.Avg_Bath_Planar, 'Mean bath planar (X/Y)', COLORS['bath'])
    planar_axes = '/'.join(a for a in 'XYZ' if a != SHAKER_VERTICAL_AXIS)
    plot_line(ax, f, summary.Shaker_Planar, f'Shaker planar ({planar_axes})', COLORS['shaker'])
    decorate(ax, 'Absolute planar acceleration', 'Planar AC RMS (g)'); ax.legend(fontsize=9)
    ax = axs[1, 0]
    plot_line(ax, f, summary.Drive_Amp, 'Commanded drive amplitude', '#222222')
    decorate(ax, 'Controller input amplitude', 'Drive command (controller units)'); ax.legend(fontsize=9)
    ax = axs[1, 1]
    for col, label, color in [('Bath_Planar_Z', 'Mean bath planar / mean bath vertical', COLORS['planar_ratio']),
                              ('Shaker_Planar_Z', 'Shaker planar / shaker vertical', COLORS['shaker']),
                              ('Planar_Transfer', 'Planar transfer: mean bath / shaker*', COLORS['bath']),
                              ('Z_Transfer', 'Vertical transfer: mean bath / shaker*', COLORS['z_transfer'])]:
        plot_line(ax, f, summary[col], label, color, log=True)
    ax.set_yscale('log'); ax.axhline(1, color='#555555', lw=.9, ls='--')
    decorate(ax, 'Motion ratios and transmissibility', 'Ratio (dimensionless, log scale)'); ax.legend(fontsize=8, loc='best')
    ax = axs[0, 2]
    plot_line(ax, f, summary.Bath_THD, 'Mean bath harmonic spectrum (Z)', COLORS['bath'], log=True)
    plot_line(ax, f, summary.Shaker_THD, f'Shaker vertical ({SHAKER_VERTICAL_AXIS})', COLORS['shaker'], log=True)
    ax.set_yscale('log')
    decorate(ax, f'Vertical harmonic distortion (H2–H{THD_MAX_HARMONIC})', 'THD (% of fundamental RMS, log scale)'); ax.legend(fontsize=9)
    ax = axs[1, 2]
    plot_line(ax, f, summary.Reference_Z_Change, 'Bath 1 vertical RMS change', COLORS['z_transfer'])
    plot_line(ax, f, summary.Reference_Planar_Change, 'Bath 1 planar RMS change', COLORS['planar_ratio'])
    ax.axhline(0, color='#555555', ls='--', lw=.9)
    decorate(ax, 'Bath 1 stability: bath-pair vs. bath–shaker captures', 'Change from bath pair to shaker pair (%)'); ax.legend(fontsize=9)
    if summary.Reference_Z_Change.isna().all():
        ax.text(.5, .5, 'Requires Bath 1 in both capture phases', transform=ax.transAxes, ha='center')
    fig.text(.5, .025, '* Transfer ratios compare sequential captures at the same commanded drive. Z means physical vertical: bath Z, shaker '+SHAKER_VERTICAL_AXIS+'.\n'
             'Bath THD uses mean per-harmonic RMS amplitudes; H2–H5 only, not THD+N. Missing/weak denominators are omitted.',
             ha='center', fontsize=10)
    fig.subplots_adjust(left=.055, right=.985, top=.865, bottom=.12, wspace=.28, hspace=.35)
    paths = [finish_figure(fig, output_path(csv_filename, 'analysis'))]
    # Preserve the standalone PID2 bath uniformity figure's content and styling.
    fig2, ax2 = plt.subplots(figsize=(12, 7))
    ax2.plot(f, summary.Bath1_Z, marker='o', color='purple', label='Bath 1 Z RMS')
    ax2.plot(f, summary.Bath2_Z, marker='o', color='darkorange', label='Bath 2 Z RMS')
    ax2.set_title('Bath Z RMS Comparison by Frequency')
    ax2.set_xlabel('Frequency (Hz)'); ax2.set_ylabel('RMS Acceleration (G)')
    ax2.grid(True, linestyle='--', alpha=.6); ax2.legend()
    paths.append(finish_figure(fig2, output_path(csv_filename, 'bath_z_comparison', SECOND_OUTPUT_DIR), 300))
    paths.append(plot_time_traces(csv_filename, SECOND_OUTPUT_DIR, raw))
    return paths


def plot_time_traces(csv_filename, output_dir=SECOND_OUTPUT_DIR, raw=None):
    raw = load_sweep_csv(csv_filename) if raw is None else raw
    paired = raw.attrs.get('paired', False)
    frequencies = sorted(raw.Freq.unique())
    columns = min(FREQUENCIES_PER_ROW, len(frequencies))
    bands = math.ceil(len(frequencies) / columns)
    fig = plt.figure(figsize=(columns * 3.0 + 1, bands * 5.0 + 1.4))
    outer = fig.add_gridspec(bands, columns, left=.035, right=.995, bottom=.035,
                            top=1 - .9/(bands*5+1.4), hspace=.32, wspace=.28)
    groups = dict(tuple(raw.groupby('Freq', sort=False)))
    axis_colors = {'X': '#cc4949', 'Y': '#22975b', 'Z': '#346cba'}
    for i, freq in enumerate(frequencies):
        band, col = divmod(i, columns)
        inner = outer[band, col].subgridspec(3, 1, hspace=.12)
        b1, b2, shaker, _ = select_blocks(groups[freq], paired)
        present = [g for g in (b1, b2) if len(g)]
        bath_end = min(g.Timestamp.iloc[-1] for g in present) if present else np.nan
        bath_start = bath_end - TRACE_PERIODS / freq
        for row, (g, label) in enumerate([(b1, 'Bath 1 · Z vertical'), (b2, 'Bath 2 · Z vertical'),
                                         (shaker, f'Shaker · {SHAKER_VERTICAL_AXIS} vertical')]):
            ax = fig.add_subplot(inner[row])
            start = bath_start if row < 2 else (g.Timestamp.iloc[-1] - TRACE_PERIODS/freq if len(g) else np.nan)
            end = bath_end if row < 2 else (g.Timestamp.iloc[-1] if len(g) else np.nan)
            if len(g):
                sample = g[(g.Timestamp >= start) & (g.Timestamp <= end)]
                for axis in 'XYZ':
                    ax.plot((sample.Timestamp-start)*1000, sample[axis]-g[axis].mean(),
                            color=axis_colors[axis], lw=.85, label=axis)
            else:
                ax.text(.5, .5, 'No data', ha='center', transform=ax.transAxes, fontsize=8)
            ax.set_xlim(0, TRACE_PERIODS/freq*1000)
            if row == 0:
                ax.set_title(f'{freq:g} Hz', fontsize=10, weight='bold')
            if col == 0:
                ax.set_ylabel(label+'\nAC (g)', fontsize=8)
            if row == 2:
                ax.set_xlabel('Time in local window (ms)', fontsize=7)
            else:
                ax.tick_params(labelbottom=False)
            ax.tick_params(labelsize=6)
            ax.grid(True, ls=':', alpha=.3)
    handles = [plt.Line2D([], [], color=axis_colors[a], label=f'Raw sensor {a}') for a in 'XYZ']
    fig.legend(handles=handles, loc='upper right', ncol=3, fontsize=10)
    fig.suptitle(f'Sample waveforms · last {TRACE_PERIODS} periods · up to 10 frequencies per row', fontsize=16, weight='bold', y=.995)
    fig.text(.5, .018, 'DC removed for display. Each frequency has Bath 1, Bath 2, then shaker. Baths share one time window; shaker is a later capture.\n'
             'Do not infer bath/shaker phase from these separate local time origins.', ha='center', fontsize=10)
    return finish_figure(fig, output_path(csv_filename, 'time_traces', output_dir), TRACE_DPI)


def find_latest_sweep_csv():
    for folder in dict.fromkeys([Path(__file__).resolve().parent, Path.cwd()]):
        candidates = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower()=='.csv' and '_vibecheck_sweep_' in p.name.lower()]
        if candidates:
            return max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name))
    return None


def choose_csv():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        try:
            selected = filedialog.askopenfilename(title='Select VibeCheck sweep CSV', filetypes=[('CSV files', '*.csv')])
        finally:
            root.destroy()
        return Path(selected) if selected else None
    except Exception:
        return None


def main():
    global SHOW_PLOTS, SHAKER_VERTICAL_AXIS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('csv', nargs='?')
    parser.add_argument('--no-show', action='store_true')
    parser.add_argument('--shaker-vertical-axis', choices=list('XYZ'), default=SHAKER_VERTICAL_AXIS)
    args = parser.parse_args()
    SHOW_PLOTS = not args.no_show
    SHAKER_VERTICAL_AXIS = args.shaker_vertical_axis
    filename = Path(args.csv).expanduser() if args.csv else find_latest_sweep_csv()
    if filename is None and SHOW_PLOTS:
        filename = choose_csv()
    if filename is None:
        parser.error('No sweep CSV found. Supply a CSV path or place it beside the script.')
    try:
        print(f'Loading {filename}')
        raw = load_sweep_csv(filename)
        print(f'Analyzing {raw.Freq.nunique()} frequencies; shaker vertical = {SHAKER_VERTICAL_AXIS}')
        summary = process_sweep_data(raw)
        generate_plots(summary, filename, raw)
        print('Done: three images saved in PID and PID2 beside the CSV.')
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
