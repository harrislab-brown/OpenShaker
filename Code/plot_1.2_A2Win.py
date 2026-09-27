"""Two-bath VibeCheck plotting for Windows (no hardware required).

Install dependencies: py -3.13 -m pip install numpy pandas matplotlib
Run: py -3.13 plot_1.2_A2Win.py "C:/data/sweep.csv"
Without a CSV argument, search beside this script, then the working folder.
If no sweep CSV is found, a file picker opens. --no-show saves without windows.
Plots go into PID and PID2 beside the selected CSV, with compact filenames.
Calculations preserve the original two-bath definitions and ratio floor.
Missing/insufficient measurements are marked unavailable rather than zero.
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
SECOND_OUTPUT_DIR = "PID2"
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


def output_path(csv_filename, suffix, output_dir=OUTPUT_DIR):
    # Compact names avoid duplicating the very long source filename on Windows.
    source = Path(csv_filename).resolve()
    folder = source.parent / output_dir
    folder.mkdir(parents=True, exist_ok=True)
    import hashlib
    token = hashlib.sha256(source.name.encode("utf-8")).hexdigest()[:8]
    return folder / f"{source.stem[:48]}_{token}_{suffix}.png"


def finish_figure(fig):
    if SHOW_PLOTS:
        plt.show()
    plt.close(fig)




def get_ac_rms(series):
    """Calculates pure AC RMS by taking the standard deviation, stripping DC bias."""
    if len(series) < 2:
        return np.nan
    return float(np.std(series.to_numpy(dtype=float), ddof=0))

def process_sweep_data(filename):
    print(f"Loading raw data from {filename}...")
    df = load_sweep_csv(filename)
    counts = df.groupby(['Freq', 'Channel']).size().unstack(fill_value=0)
    for channel, label in [(0, 'Bath 1'), (2, 'Bath 2')]:
        available = counts.get(channel, pd.Series(0, index=counts.index))
        if (available < 2).any():
            print(f'Warning: {label} has insufficient samples at some frequencies; '
                  'dependent results will be unavailable.')
    
    results = []
    grouped = df.groupby('Freq')
    
    print(f"Processing {len(grouped)} discrete frequencies...")
    for freq, group in grouped:
        drive_amp = group['Drive_Amp'].mean()
        
        # Isolate data by channel
        ch0 = group[group['Channel'] == 0]  # Bath 1
        ch2 = group[group['Channel'] == 2]  # Bath 2
        
        # Primary Z-Axis AC RMS
        rms_0_z = get_ac_rms(ch0['Z'])
        rms_2_z = get_ac_rms(ch2['Z'])
        
        # --- PLANAR CALCULATIONS ---
        rms_0_x = get_ac_rms(ch0['X'])
        rms_0_y = get_ac_rms(ch0['Y'])
        bath1_planar = np.sqrt(rms_0_x**2 + rms_0_y**2)
        
        rms_2_x = get_ac_rms(ch2['X'])
        rms_2_y = get_ac_rms(ch2['Y'])
        bath2_planar = np.sqrt(rms_2_x**2 + rms_2_y**2)
        
        avg_bath_planar = (bath1_planar + bath2_planar) / 2.0
        avg_bath_z = (rms_0_z + rms_2_z) / 2.0
        uniformity_gap = abs(rms_0_z - rms_2_z)
        planar_to_z_ratio = avg_bath_planar / max(avg_bath_z, 0.001)

        results.append({
            'Freq': freq,
            'Drive_Amp': drive_amp,
            'Bath1_Z': rms_0_z,
            'Bath2_Z': rms_2_z,
            'Bath1_Planar': bath1_planar,
            'Bath2_Planar': bath2_planar,
            'Avg_Bath_Planar': avg_bath_planar,
            'Uniformity_Gap': uniformity_gap,
            'Planar_to_Z_Ratio': planar_to_z_ratio
        })
        
    return pd.DataFrame(results)

def generate_plots(df, csv_filename):
    # Ensure output directories exist

    # Dynamic File Naming based on CSV
    base_name = os.path.basename(csv_filename)
    output_image = output_path(csv_filename, "analysis", OUTPUT_DIR)

    # 2x2 Grid for two bath sensors
    fig, axs = plt.subplots(2, 2, figsize=(22, 12))
    
    # Title with CSV filename included underneath
    fig.suptitle(f"Vibration Sweep Analysis: Two Bath Sensors\nData Source: {textwrap.fill(base_name, width=110)}", 
                 fontsize=18, fontweight='bold', y=0.98)
    
    freqs = df['Freq']
    
    # --- PLOT 1: Sensor Uniformity [TOP LEFT] ---
    axs[0, 0].plot(freqs, df['Bath1_Z'], marker='o', color='purple', label='Bath 1 (Z)')
    axs[0, 0].plot(freqs, df['Bath2_Z'], marker='o', color='darkorange', label='Bath 2 (Z)')
    axs[0, 0].fill_between(freqs, df['Bath1_Z'], df['Bath2_Z'], color='red', alpha=0.15, label='Uniformity Gap')
    axs[0, 0].set_title("Sensor Uniformity (Bath 1 vs Bath 2)")
    axs[0, 0].set_xlabel("Frequency (Hz)")
    axs[0, 0].set_ylabel("RMS Acceleration (G)")
    axs[0, 0].grid(True, linestyle='--', alpha=0.6)
    axs[0, 0].legend()

    # --- PLOT 2: Absolute Planar Acceleration [TOP RIGHT] ---
    axs[0, 1].plot(freqs, df['Avg_Bath_Planar'], marker='o', color='#e74c3c', linewidth=2.5, label='Average Bath Planar')
    axs[0, 1].plot(freqs, df['Bath1_Planar'], linestyle=':', color='purple', alpha=0.8, label='Bath 1 Planar')
    axs[0, 1].plot(freqs, df['Bath2_Planar'], linestyle=':', color='darkorange', alpha=0.8, label='Bath 2 Planar')
    axs[0, 1].set_title("Absolute Planar Acceleration", fontsize=14, pad=10)
    axs[0, 1].set_xlabel("Frequency (Hz)", fontsize=12)
    axs[0, 1].set_ylabel("RMS Acceleration (G)", fontsize=12)
    axs[0, 1].legend(loc='upper left', frameon=True, shadow=True)
    axs[0, 1].grid(True, linestyle='--', alpha=0.7)

    # --- PLOT 3: Drive Amplitude [BOTTOM LEFT] ---
    axs[1, 0].plot(freqs, df['Drive_Amp'], marker='o', color='black', linewidth=2, label='Drive Amplitude')
    axs[1, 0].set_title("Controller Drive Amplitude")
    axs[1, 0].set_xlabel("Frequency (Hz)")
    axs[1, 0].set_ylabel("Amplitude (V)")
    axs[1, 0].grid(True, linestyle='--', alpha=0.6)
    axs[1, 0].legend()

    # --- PLOT 4: Planar-to-Z Ratio [BOTTOM RIGHT] ---
    axs[1, 1].plot(freqs, df['Planar_to_Z_Ratio'], marker='o', color='#16a085', linewidth=2.5, label='Avg Bath Planar / Avg Bath Z')
    axs[1, 1].set_title("Planar-to-Z Ratio", fontsize=14, pad=10)
    axs[1, 1].set_xlabel("Frequency (Hz)", fontsize=12)
    axs[1, 1].set_ylabel("Ratio (non-dimensional)", fontsize=12)
    axs[1, 1].set_yscale('log')
    axs[1, 1].set_ylim(0.01, 100)
    axs[1, 1].grid(True, linestyle='--', alpha=0.7, which='both')
    axs[1, 1].legend(loc='best', frameon=True, shadow=True)

    plt.tight_layout()
    plt.subplots_adjust(top=0.90, hspace=0.25, wspace=0.2)
    
    print(f"Saving high-resolution plot to {output_image}...")
    fig.savefig(output_image, dpi=300, bbox_inches='tight')
    finish_figure(fig)

    # --- ADDITIONAL PLOT: Bath Z RMS Comparison ---
    fig2, ax2 = plt.subplots(figsize=(12, 7))
    ax2.plot(freqs, df['Bath1_Z'], marker='o', color='purple', label='Bath 1 Z RMS')
    ax2.plot(freqs, df['Bath2_Z'], marker='o', color='darkorange', label='Bath 2 Z RMS')
    ax2.set_title('Bath Z RMS Comparison by Frequency')
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('RMS Acceleration (G)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    
    avg_output_image = output_path(csv_filename, "bath_z_comparison", SECOND_OUTPUT_DIR)
    print(f"Saving average RMS plot to {avg_output_image}...")
    fig2.savefig(avg_output_image, dpi=300, bbox_inches='tight')
    finish_figure(fig2)

    plot_time_traces(csv_filename, SECOND_OUTPUT_DIR)


def plot_time_traces(csv_filename, output_dir):
    raw_df = load_sweep_csv(csv_filename)
    frequencies = sorted(raw_df['Freq'].unique())
    channels = [(0, 'Bath 1'), (2, 'Bath 2')]
    # Paginate long sweeps so Windows does not need one enormous bitmap.
    per_page = 6
    for start in range(0, len(frequencies), per_page):
        freqs = frequencies[start:start + per_page]
        fig, axs = plt.subplots(2, len(freqs), squeeze=False,
                                figsize=(max(10, len(freqs) * 3), 8),
                                sharex='col', sharey='row')
        for row, (channel, label) in enumerate(channels):
            for col, freq in enumerate(freqs):
                ax = axs[row, col]
                subset = raw_df[(raw_df['Freq'] == freq) &
                                (raw_df['Channel'] == channel)].sort_values('Timestamp')
                if subset.empty:
                    ax.text(0.5, 0.5, 'No data', transform=ax.transAxes, ha='center', va='center')
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
                if row == 1:
                    ax.set_xlabel('Time (s)')
                ax.tick_params(labelsize=8)
                ax.grid(True, linestyle=':', alpha=0.3)
        page = start // per_page + 1
        fig.suptitle(f'Sample Time Traces (Last 5 Periods) - Page {page}',
                     fontsize=16, fontweight='bold')
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        destination = output_path(csv_filename, f'time_traces_{page:02d}', output_dir)
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
        print(f'Done. Plots saved in {filename.parent / OUTPUT_DIR} and {filename.parent / SECOND_OUTPUT_DIR}')
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
