import glob
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# --- CONFIGURATION ---
OUTPUT_DIR = "PID"
SECOND_OUTPUT_DIR = "PID2"

def get_ac_rms(series):
    """Calculates pure AC RMS by taking the standard deviation, stripping DC bias."""
    if len(series) < 2:
        return 0.0
    return np.std(series)

def process_sweep_data(filename):
    print(f"Loading raw data from {filename}...")
    df = pd.read_csv(filename)
    
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
        rms_0_x = get_ac_rms(ch0['X']) if not ch0['X'].empty else 0.0
        rms_0_y = get_ac_rms(ch0['Y']) if not ch0['Y'].empty else 0.0
        bath1_planar = np.sqrt(rms_0_x**2 + rms_0_y**2)
        
        rms_2_x = get_ac_rms(ch2['X']) if not ch2['X'].empty else 0.0
        rms_2_y = get_ac_rms(ch2['Y']) if not ch2['Y'].empty else 0.0
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SECOND_OUTPUT_DIR, exist_ok=True)

    # Dynamic File Naming based on CSV
    base_name = os.path.basename(csv_filename)
    output_image = os.path.join(OUTPUT_DIR, f"{os.path.splitext(base_name)[0]}.png")

    # 2x2 Grid for two bath sensors
    fig, axs = plt.subplots(2, 2, figsize=(22, 12))
    
    # Title with CSV filename included underneath
    fig.suptitle(f"Vibration Sweep Analysis: Two Bath Sensors\nData Source: {base_name}", 
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
    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.show()

    # --- ADDITIONAL PLOT: Bath Z RMS Comparison ---
    fig2, ax2 = plt.subplots(figsize=(12, 7))
    ax2.plot(freqs, df['Bath1_Z'], marker='o', color='purple', label='Bath 1 Z RMS')
    ax2.plot(freqs, df['Bath2_Z'], marker='o', color='darkorange', label='Bath 2 Z RMS')
    ax2.set_title('Bath Z RMS Comparison by Frequency')
    ax2.set_xlabel('Frequency (Hz)')
    ax2.set_ylabel('RMS Acceleration (G)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    
    avg_output_image = os.path.join(SECOND_OUTPUT_DIR, f"{os.path.splitext(base_name)[0]}_bath_z_comparison.png")
    print(f"Saving average RMS plot to {avg_output_image}...")
    fig2.savefig(avg_output_image, dpi=300, bbox_inches='tight')
    plt.show()

    plot_time_traces(csv_filename, SECOND_OUTPUT_DIR)


def plot_time_traces(csv_filename, output_dir):
    raw_df = pd.read_csv(csv_filename)
    freqs = sorted(raw_df['Freq'].unique())
    channels = [
        (0, 'Bath 1'),
        (2, 'Bath 2')
    ]
    n_cols = len(freqs)
    n_rows = len(channels)
    fig, axs = plt.subplots(n_rows, n_cols, figsize=(max(15, n_cols * 1.2), n_rows * 2), sharex='col', sharey='row')

    for row, (ch, label) in enumerate(channels):
        for col, freq in enumerate(freqs):
            ax = axs[row][col] if n_rows > 1 else axs[col]
            subset = raw_df[(raw_df['Freq'] == freq) & (raw_df['Channel'] == ch)]
            if subset.empty:
                ax.text(0.5, 0.5, 'No data', ha='center', va='center', color='gray')
            else:
                times = subset['Timestamp']
                period = 1.0 / freq if freq > 0 else 0.0
                window = 5.0 * period
                t_end = times.iloc[-1]
                t_start = max(times.iloc[0], t_end - window)
                window_mask = times >= t_start
                times_window = times[window_mask] - t_start
                ax.plot(times_window, subset.loc[window_mask, 'X'], linewidth=1, label='X')
                ax.plot(times_window, subset.loc[window_mask, 'Y'], linewidth=1, label='Y')
                ax.plot(times_window, subset.loc[window_mask, 'Z'], linewidth=1, label='Z')
                if row == 0 and col == n_cols - 1:
                    ax.legend(loc='upper right', fontsize=6)
            if row == 0:
                ax.set_title(f'{freq} Hz', fontsize=9)
            if col == 0:
                ax.set_ylabel(label, fontsize=8)
            if row == n_rows - 1:
                ax.set_xlabel('Time (s)', fontsize=8)
            ax.tick_params(labelsize=6)
            ax.grid(True, linestyle=':', alpha=0.3)

    base_name = os.path.basename(csv_filename)
    fig.suptitle('Sample Time Traces (Last 5 Periods) by Frequency and Sensor', fontsize=16, fontweight='bold')
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    output_image = os.path.join(output_dir, f"{os.path.splitext(base_name)[0]}_time_traces.png")
    print(f"Saving time trace plot to {output_image}...")
    fig.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.show()


def find_latest_sweep_csv():
    candidates = sorted(glob.glob("*_vibecheck_sweep_*.csv"))
    if not candidates:
        return None
    return candidates[-1]

if __name__ == "__main__":
    csv_filename = None
    if len(sys.argv) > 1:
        csv_filename = sys.argv[1]
    else:
        csv_filename = find_latest_sweep_csv()

    if not csv_filename:
        print("Error: No VibeCheck sweep CSV file found. Provide a filename as the first argument.")
        sys.exit(1)

    try:
        summary_df = process_sweep_data(csv_filename)
        generate_plots(summary_df, csv_filename)
    except FileNotFoundError:
        print(f"Error: Could not find {csv_filename}. Ensure the file exists in the same directory.")
    except Exception as e:
        print(f"An error occurred: {e}")
