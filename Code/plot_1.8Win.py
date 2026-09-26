"""Windows-compatible VibeCheck sweep plotting.

Install: py -m pip install pandas numpy matplotlib
Run:     py plot_1.8Win.py "C:/path/to/sweep.csv"
Or put this script beside the CSV and run without arguments.
Outputs are written to a PID folder beside the selected CSV.
Use --no-show to save plots without opening plot windows.
Channel mapping is preserved: 0 = Bath 1, 2 = Bath 2, 4 = Shaker.
Missing measurements are NaN, never invented zero measurements.
"""
import argparse
from pathlib import Path
import textwrap
import sys
import pandas as pd
import numpy as np
import matplotlib
if "--no-show" in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

# --- CONFIGURATION ---
OUTPUT_DIR = "PID"
SHOW_PLOTS = True


def load_sweep_csv(filename):
    """Read the supplied numeric CSV and reject malformed measurements."""
    df = pd.read_csv(filename, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    required = ["Timestamp", "Freq", "Drive_Amp", "Channel", "X", "Y", "Z"]
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError("Missing CSV columns: " + ", ".join(missing))
    if df.empty:
        raise ValueError("The CSV contains no measurements.")
    for name in required:
        df[name] = pd.to_numeric(df[name], errors="raise")
        if not np.isfinite(df[name].to_numpy(dtype=float)).all():
            raise ValueError(f"Column {name} contains blank or non-finite values.")
    if (df["Freq"] <= 0).any():
        raise ValueError("Frequencies must be greater than zero.")
    if (df["Channel"] % 1 != 0).any():
        raise ValueError("Channel IDs must be integers.")
    return df


def output_path(csv_filename, suffix):
    # Compact names avoid duplicating the very long source filename on Windows.
    source = Path(csv_filename).resolve()
    folder = source.parent / OUTPUT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    import hashlib
    token = hashlib.sha256(source.name.encode("utf-8")).hexdigest()[:8]
    return folder / f"{source.stem[:48]}_{token}_{suffix}.png"


def finish_figure(fig):
    if SHOW_PLOTS:
        plt.show()
    plt.close(fig)


def ratio(response, excitation):
    # Preserve the original 0.001 G denominator floor for measured data only.
    if not np.isfinite(excitation):
        return np.nan
    return response / max(excitation, 0.001)


def mark_unavailable(ax, message):
    ax.text(0.5, 0.5, message, transform=ax.transAxes,
            ha="center", va="center", fontsize=11,
            bbox=dict(facecolor="white", edgecolor="gray", alpha=0.95))

def get_ac_rms(series):
    """Calculates pure AC RMS by taking the standard deviation, stripping DC bias."""
    if len(series) < 2:
        return np.nan
    return float(np.std(series.to_numpy(dtype=float), ddof=0))

def process_sweep_data(filename):
    print(f"Loading raw data from {filename}...")
    df = load_sweep_csv(filename)
    counts = df.groupby(["Freq", "Channel"]).size().unstack(fill_value=0)
    for channel, label in [(0, "Bath 1"), (2, "Bath 2"), (4, "Shaker")]:
        insufficient = counts.index[counts.get(channel, pd.Series(0, index=counts.index)) < 2]
        if len(insufficient):
            print(f"Warning: {label} (channel {channel}) has fewer than two samples at "
                  f"{len(insufficient)} frequency points. Dependent results are unavailable.")
    
    results = []
    grouped = df.groupby('Freq')
    
    print(f"Processing {len(grouped)} discrete frequencies...")
    for freq, group in grouped:
        drive_amp = group['Drive_Amp'].mean()
        
        # Isolate data by channel
        ch0 = group[group['Channel'] == 0] # Bath 1
        ch2 = group[group['Channel'] == 2] # Bath 2
        ch4 = group[group['Channel'] == 4] # Base Shaker
        
        # Calculate Primary Z-Axis / Y-Axis AC RMS
        rms_0_z = get_ac_rms(ch0['Z'])
        rms_2_z = get_ac_rms(ch2['Z'])
        rms_4_y = get_ac_rms(ch4['Y']) 
        
        # --- PLANAR CALCULATIONS ---
        rms_0_x = get_ac_rms(ch0['X']) if 'X' in ch0.columns else 0.0
        rms_0_y = get_ac_rms(ch0['Y']) if 'Y' in ch0.columns else 0.0
        bath1_planar = np.sqrt(rms_0_x**2 + rms_0_y**2)
        
        rms_2_x = get_ac_rms(ch2['X']) if 'X' in ch2.columns else 0.0
        rms_2_y = get_ac_rms(ch2['Y']) if 'Y' in ch2.columns else 0.0
        bath2_planar = np.sqrt(rms_2_x**2 + rms_2_y**2)
        
        rms_4_x = get_ac_rms(ch4['X']) if 'X' in ch4.columns else 0.0
        rms_4_z = get_ac_rms(ch4['Z']) if 'Z' in ch4.columns else 0.0
        shaker_planar = np.sqrt(rms_4_x**2 + rms_4_z**2)
        
        avg_bath_planar = (bath1_planar + bath2_planar) / 2.0

        # Compare Bath sensors Z RMS to Shaker Y RMS
        avg_rms_0 = rms_0_z
        avg_rms_2 = rms_2_z
        avg_rms_4 = rms_4_y

        # Prevent division by zero
        denom = rms_4_y 
        denom_planar = shaker_planar
        
        # Transmissibility (Response / Excitation)
        trans_1 = ratio(rms_0_z, denom)
        trans_2 = ratio(rms_2_z, denom)
        planar_trans = ratio(avg_bath_planar, denom_planar)
        
        # Absolute Difference (Response - Excitation)
        diff_1 = rms_0_z - rms_4_y
        diff_2 = rms_2_z - rms_4_y

        # Uniformity Error (Absolute divergence between the two baths)
        uniformity_gap = abs(rms_0_z - rms_2_z)
        
        results.append({
            'Freq': freq,
            'Drive_Amp': drive_amp,
            'Bath1_Z': rms_0_z,
            'Bath2_Z': rms_2_z,
            'Shaker_Y': rms_4_y,
            'Bath1_Avg_RMS': avg_rms_0,
            'Bath2_Avg_RMS': avg_rms_2,
            'Shaker_Avg_RMS': avg_rms_4,
            'Trans_1': trans_1,
            'Trans_2': trans_2,
            'Diff_1': diff_1,
            'Diff_2': diff_2,
            'Uniformity_Gap': uniformity_gap,
            'Bath1_Planar': bath1_planar,
            'Bath2_Planar': bath2_planar,
            'Avg_Bath_Planar': avg_bath_planar,
            'Shaker_Planar': shaker_planar,
            'Planar_Transmissibility': planar_trans
        })
        
    return pd.DataFrame(results)

def generate_plots(df, csv_filename):
    # Ensure output directory exists

    # Dynamic File Naming based on CSV
    base_name = os.path.basename(csv_filename)
    output_image = output_path(csv_filename, "analysis")

    # 2x3 Grid (2 rows, 3 columns)
    fig, axs = plt.subplots(2, 3, figsize=(22, 12))
    
    # Title with CSV filename included underneath
    fig.suptitle(f"Vibration Sweep Analysis: Transmissibility & Uniformity\nData Source: {textwrap.fill(base_name, width=110)}", 
                 fontsize=18, fontweight='bold', y=0.98)
    
    freqs = df['Freq']
    
    # --- PLOT 1: Drive Amplitude [TOP LEFT] ---
    axs[0, 0].plot(freqs, df['Drive_Amp'], marker='o', color='black', linewidth=2, label='Drive Amplitude')
    axs[0, 0].set_title("Controller Drive Amplitude")
    axs[0, 0].set_xlabel("Frequency (Hz)")
    axs[0, 0].set_ylabel("Amplitude (V)")
    axs[0, 0].grid(True, linestyle='--', alpha=0.6)
    axs[0, 0].legend()
    
    # --- PLOT 2: Acceleration Output Difference [TOP MIDDLE] ---
    axs[0, 1].plot(freqs, df['Diff_1'], marker='o', color='purple', label='Bath 1 Δ')
    axs[0, 1].plot(freqs, df['Diff_2'], marker='o', color='darkorange', label='Bath 2 Δ')
    axs[0, 1].axhline(0, color='black', linestyle='--', linewidth=1.5, label='Perfect Match (0 G)')
    axs[0, 1].fill_between(freqs, 0, df['Diff_1'], where=(df['Diff_1'] > 0), color='green', alpha=0.1)
    axs[0, 1].fill_between(freqs, 0, df['Diff_1'], where=(df['Diff_1'] < 0), color='red', alpha=0.1)
    axs[0, 1].set_title("Acceleration Output Difference (Bath - Base Shaker)")
    axs[0, 1].set_xlabel("Frequency (Hz)")
    axs[0, 1].set_ylabel("Difference (G)")
    axs[0, 1].grid(True, linestyle='--', alpha=0.6)
    axs[0, 1].legend()

    # --- PLOT 3: Absolute Planar Acceleration [TOP RIGHT] ---
    axs[0, 2].plot(freqs, df['Shaker_Planar'], marker='s', color='#34495e', linewidth=2.5, label='Base Shaker Planar Wobble')
    axs[0, 2].plot(freqs, df['Avg_Bath_Planar'], marker='o', color='#e74c3c', linewidth=2.5, label='Average Bath Planar Wobble')
    
    # Lightly plot individual baths for transparency
    axs[0, 2].plot(freqs, df['Bath1_Planar'], linestyle=':', color='purple', alpha=0.5, label='Bath 1 (Ref)')
    axs[0, 2].plot(freqs, df['Bath2_Planar'], linestyle=':', color='darkorange', alpha=0.5, label='Bath 2 (Ref)')

    axs[0, 2].set_title("Absolute Transverse Acceleration", fontsize=14, pad=10)
    axs[0, 2].set_xlabel("Frequency (Hz)", fontsize=12)
    axs[0, 2].set_ylabel("RMS Acceleration (G)", fontsize=12)
    axs[0, 2].legend(loc='upper left', frameon=True, shadow=True)
    axs[0, 2].grid(True, linestyle='--', alpha=0.7)

    # --- PLOT 4: Sensor Uniformity [BOTTOM LEFT] ---
    axs[1, 0].plot(freqs, df['Bath1_Z'], marker='o', color='purple', label='Bath 1 (Z)')
    axs[1, 0].plot(freqs, df['Bath2_Z'], marker='o', color='darkorange', label='Bath 2 (Z)')
    axs[1, 0].fill_between(freqs, df['Bath1_Z'], df['Bath2_Z'], color='red', alpha=0.15, label='Uniformity Gap')
    axs[1, 0].set_title("Sensor Uniformity (Bath 1 vs Bath 2)")
    axs[1, 0].set_xlabel("Frequency (Hz)")
    axs[1, 0].set_ylabel("RMS Acceleration (G)")
    axs[1, 0].grid(True, linestyle='--', alpha=0.6)
    axs[1, 0].legend()

    # --- PLOT 5: Transmissibility Ratio (T) [BOTTOM MIDDLE] ---
    axs[1, 1].plot(freqs, df['Trans_1'], marker='o', color='purple', label='Bath 1 (T)')
    axs[1, 1].plot(freqs, df['Trans_2'], marker='o', color='darkorange', label='Bath 2 (T)')
    axs[1, 1].axhline(1.0, color='red', linestyle='--', linewidth=1.5, label='T = 1.0 (1:1 Transfer)')
    
    # Highlight Amplification vs Isolation Zones
    axs[1, 1].axhspan(1.0, max(1.5, df[['Trans_1', 'Trans_2']].max().max()), color='red', alpha=0.05, label='Amplification Zone')
    axs[1, 1].axhspan(0, 1.0, color='blue', alpha=0.05, label='Isolation Zone')
    
    axs[1, 1].set_title("Transmissibility Ratio (Bath Z / Shaker Y)")
    axs[1, 1].set_xlabel("Frequency (Hz)")
    axs[1, 1].set_ylabel("Transmissibility (T)")
    axs[1, 1].set_ylim(bottom=0) 
    axs[1, 1].grid(True, linestyle='--', alpha=0.6)
    axs[1, 1].legend()

    # --- PLOT 6: Planar Transmissibility [BOTTOM RIGHT] ---
    t_data = df['Planar_Transmissibility']
    axs[1, 2].plot(freqs, t_data, marker='D', color='#2980b9', linewidth=2.5, label='Planar Transmissibility (Avg Bath / Shaker)')
    
    # The Critical 1:1 Reference Line
    axs[1, 2].axhline(1.0, color='black', linestyle='--', linewidth=2, label='1:1 Transfer (T=1.0)')
    
    # Shade Regions
    max_t = max(1.5, t_data.max() * 1.1) # Dynamic top limit
    axs[1, 2].axhspan(1.0, max_t, color='red', alpha=0.08, label='Amplification Zone (T > 1)')
    axs[1, 2].axhspan(0, 1.0, color='green', alpha=0.08, label='Isolation Zone (T < 1)')
    
    # Annotate the Maximum Peak (Worst Case Resonance)
    if t_data.notna().any():
        max_idx = t_data.idxmax()
        max_freq = df.loc[max_idx, 'Freq']
        max_val = t_data.loc[max_idx]
        axs[1, 2].annotate(f'Worst Case: {max_val:.2f}x at {max_freq:g} Hz',
                          xy=(max_freq, max_val), xytext=(0.04, 0.85),
                          textcoords='axes fraction',
                          arrowprops=dict(arrowstyle='->'),
                          fontsize=10, color='darkred')

    axs[1, 2].set_title("Planar Transmissibility Ratio (T)", fontsize=14, pad=10)
    axs[1, 2].set_xlabel("Frequency (Hz)", fontsize=12)
    axs[1, 2].set_ylabel("Transmissibility Ratio", fontsize=12)
    axs[1, 2].set_ylim(0, max_t)
    axs[1, 2].legend(loc='upper right', frameon=True, shadow=True)
    axs[1, 2].grid(True, linestyle='--', alpha=0.7)

    for ax, columns in [(axs[0, 1], ['Diff_1', 'Diff_2']),
                        (axs[1, 1], ['Trans_1', 'Trans_2']),
                        (axs[1, 2], ['Planar_Transmissibility'])]:
        if not df[columns].notna().any().any():
            mark_unavailable(ax, "Unavailable: requires bath and shaker data\n"
                             "(shaker = channel 4)")

    # Final Polish
    plt.tight_layout()
    plt.subplots_adjust(top=0.90, hspace=0.25, wspace=0.2) # Adjust spacing for title and wide layout
    
    print(f"Saving high-resolution plot to {output_image}...")
    fig.savefig(output_image, dpi=300, bbox_inches='tight')
    finish_figure(fig)

    # --- ADDITIONAL PLOT: Bath Z RMS vs Shaker Y RMS ---
    fig2, ax2 = plt.subplots(figsize=(12, 7))
    ax2.plot(freqs, df['Bath1_Avg_RMS'], marker='o', color='purple', label='Bath 1 Z RMS')
    ax2.plot(freqs, df['Bath2_Avg_RMS'], marker='o', color='darkorange', label='Bath 2 Z RMS')
    ax2.plot(freqs, df['Shaker_Avg_RMS'], marker='o', color='#34495e', label='Shaker Y RMS')
    ax2.set_title('Bath Z RMS vs Shaker Y RMS by Frequency')
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('RMS Acceleration (G)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    
    avg_output_image = output_path(csv_filename, "bath_z_vs_shaker_y")
    print(f"Saving average RMS plot to {avg_output_image}...")
    fig2.savefig(avg_output_image, dpi=300, bbox_inches='tight')
    finish_figure(fig2)

    plot_time_traces(csv_filename)


def plot_time_traces(csv_filename):
    raw_df = load_sweep_csv(csv_filename)
    frequencies = sorted(raw_df['Freq'].unique())
    channels = [(0, 'Bath 1'), (2, 'Bath 2'), (4, 'Shaker')]
    # Paginate long sweeps so Windows does not need one enormous bitmap.
    per_page = 6
    for start in range(0, len(frequencies), per_page):
        freqs = frequencies[start:start + per_page]
        fig, axs = plt.subplots(3, len(freqs), squeeze=False,
                                figsize=(max(10, len(freqs) * 3), 8),
                                sharex='col', sharey='row')
        for row, (channel, label) in enumerate(channels):
            for col, freq in enumerate(freqs):
                ax = axs[row, col]
                subset = raw_df[(raw_df['Freq'] == freq) &
                                (raw_df['Channel'] == channel)].sort_values('Timestamp')
                if subset.empty:
                    mark_unavailable(ax, 'No data')
                else:
                    times = subset['Timestamp']
                    t_start = max(times.iloc[0], times.iloc[-1] - 5.0 / freq)
                    sample = subset.loc[times >= t_start]
                    for axis in ['X', 'Y', 'Z']:
                        ax.plot(sample['Timestamp'] - t_start, sample[axis],
                                linewidth=1, label=axis)
                    if row == 0 and col == len(freqs) - 1:
                        ax.legend(fontsize=8)
                if row == 0:
                    ax.set_title(f'{freq:g} Hz')
                if col == 0:
                    ax.set_ylabel(f'{label} (G)')
                if row == 2:
                    ax.set_xlabel('Time (s)')
                ax.tick_params(labelsize=8)
                ax.grid(True, linestyle=':', alpha=0.3)
        page = start // per_page + 1
        fig.suptitle(f'Sample Time Traces (Last 5 Periods) - Page {page}',
                     fontsize=16, fontweight='bold')
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        destination = output_path(csv_filename, f'time_traces_{page:02d}')
        print(f'Saving time traces to {destination}...')
        fig.savefig(destination, dpi=300, bbox_inches='tight')
        finish_figure(fig)


def find_latest_sweep_csv():
    """Search beside the script first, then in the working directory."""
    directories = dict.fromkeys([Path(__file__).resolve().parent, Path.cwd()])
    for folder in directories:
        candidates = [p for p in folder.iterdir()
                      if p.is_file() and p.suffix.lower() == '.csv'
                      and '_vibecheck_sweep_' in p.name.lower()]
        if candidates:
            return max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name))
    return None


def choose_csv():
    """Optional native file picker if automatic discovery finds nothing."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title='Select VibeCheck sweep CSV',
                filetypes=[('CSV files', '*.csv'), ('All files', '*.*')])
        finally:
            root.destroy()
        return Path(selected) if selected else None
    except Exception:
        return None


def main():
    global SHOW_PLOTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', nargs='?', help='CSV path (quote paths containing spaces)')
    parser.add_argument('--no-show', action='store_true', help='Save plots without GUI windows')
    args = parser.parse_args()
    SHOW_PLOTS = not args.no_show
    filename = Path(args.csv).expanduser() if args.csv else find_latest_sweep_csv()
    if filename is None and SHOW_PLOTS:
        filename = choose_csv()
    if filename is None:
        parser.error('No sweep CSV found. Put it beside the script or supply its path.')
    try:
        filename = filename.resolve()
        summary = process_sweep_data(filename)
        generate_plots(summary, filename)
        print(f'Done. Plots saved in {filename.parent / OUTPUT_DIR}')
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
