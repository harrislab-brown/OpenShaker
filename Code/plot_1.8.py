import glob
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os

# --- CONFIGURATION ---
OUTPUT_DIR = "PID"

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

        # Prevent division by zero
        denom = max(rms_4_y, 0.001) 
        denom_planar = max(shaker_planar, 0.001)
        
        # Transmissibility (Response / Excitation)
        trans_1 = rms_0_z / denom
        trans_2 = rms_2_z / denom
        planar_trans = avg_bath_planar / denom_planar
        
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Dynamic File Naming based on CSV
    base_name = os.path.basename(csv_filename)
    output_image = os.path.join(OUTPUT_DIR, f"{os.path.splitext(base_name)[0]}.png")

    # 2x3 Grid (2 rows, 3 columns)
    fig, axs = plt.subplots(2, 3, figsize=(22, 12))
    
    # Title with CSV filename included underneath
    fig.suptitle(f"Vibration Sweep Analysis: Transmissibility & Uniformity\nData Source: {base_name}", 
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
    axs[1, 1].axhspan(1.0, max(df[['Trans_1', 'Trans_2']].max().max(), 1.5), color='red', alpha=0.05, label='Amplification Zone')
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
    max_t = max(t_data.max() * 1.1, 1.5) # Dynamic top limit
    axs[1, 2].axhspan(1.0, max_t, color='red', alpha=0.08, label='Amplification Zone (T > 1)')
    axs[1, 2].axhspan(0, 1.0, color='green', alpha=0.08, label='Isolation Zone (T < 1)')
    
    # Annotate the Maximum Peak (Worst Case Resonance)
    max_idx = t_data.idxmax()
    max_freq = df['Freq'].iloc[max_idx]
    max_val = t_data.iloc[max_idx]
    
    axs[1, 2].annotate(f'Worst Case: {max_val:.2f}x at {max_freq}Hz', 
                 xy=(max_freq, max_val), 
                 xytext=(max_freq + 10, max_val),
                 arrowprops=dict(facecolor='black', shrink=0.05, width=1.5, headwidth=6),
                 fontsize=11, fontweight='bold', color='darkred')

    axs[1, 2].set_title("Planar Transmissibility Ratio (T)", fontsize=14, pad=10)
    axs[1, 2].set_xlabel("Frequency (Hz)", fontsize=12)
    axs[1, 2].set_ylabel("Transmissibility Ratio", fontsize=12)
    axs[1, 2].set_ylim(0, max_t)
    axs[1, 2].legend(loc='upper right', frameon=True, shadow=True)
    axs[1, 2].grid(True, linestyle='--', alpha=0.7)

    # Final Polish
    plt.tight_layout()
    plt.subplots_adjust(top=0.90, hspace=0.25, wspace=0.2) # Adjust spacing for title and wide layout
    
    print(f"Saving high-resolution plot to {output_image}...")
    plt.savefig(output_image, dpi=300, bbox_inches='tight')
    plt.show()

def find_latest_sweep_csv():
    candidates = sorted(glob.glob("*_vibecheck_sweep_*Hz.csv"))
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
