import serial
import time
import csv
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from collections import deque

# --- CONFIGURATION ---
PORT = '/dev/tty.usbmodem3646396830331' 
BAUD_RATE = 115200 

# --- SWEEP & CONTROL SETTINGS ---
SWEEP_START_FREQ = 30   
SWEEP_END_FREQ = 220     
SWEEP_STEP_SIZE = 10     
TARGET_PEAK_G = 2.0       
MAX_AMPLITUDE = 0.6      
TOLERANCE_PCT = 0.10     
STABILITY_WINDOW = 3.0   
UPDATE_INTERVAL = 0.25    
COLLECT_TIME_SEC = 3.0   
CSV_FILENAME = "sweep_data_182.4g_4g_30_220.csv"
WINDOW_SIZE = 100         
ODR_SETTING = 840        # UPDATED: Increased to 1660Hz

# DISCOVERY FIX: Initialize 1, but plot/read 2
INIT_CHANNELS = [0, 2, 4]   
PLOT_CHANNELS = [0, 2, 4]   

CHANNEL_LABELS = {
    0: "Bath 1 (Z-axis)",
    2: "Bath 2 (Z-axis)",     
    4: "Base Shaker (Y-axis)"
}

# --- SERIAL & UTILITY ---
device = serial.Serial(PORT, BAUD_RATE, timeout=0.01)

def send_command_sync(cmd, timeout_sec=1.5):
    print(f"Sending: {cmd}")
    device.write(f"{cmd}\n".encode('utf-8')) 
    start_time = time.time()
    while (time.time() - start_time) < timeout_sec:
        line = device.readline().decode('utf-8', errors='ignore').strip()
        if line and any(x in line.lower() for x in ["ack", "ok"]):
            print(f"   -> Board: {line}")
            return line
    return None

def send_command_async(cmd):
    device.write(f"{cmd}\n".encode('utf-8'))

def get_ac_rms(data_deque):
    """Calculates pure AC RMS. Using np.std inherently strips out static DC bias/gravity offset."""
    if len(data_deque) < 20: return 0.0 # Wait for at least a tiny bit of data
    arr = np.array(data_deque)
    return np.std(arr) 

def get_combined_rms(axis1, axis2):
    return np.sqrt(get_ac_rms(axis1)**2 + get_ac_rms(axis2)**2)

# --- DATA STORAGE ---
sensor_data = {
    chan: {ax: deque(maxlen=WINDOW_SIZE) for ax in ['x', 'y', 'z', 't']}
    for chan in PLOT_CHANNELS
}

# --- CONTROLLER LOGIC ---
class SweepController:
    def __init__(self):
        self.freqs = list(range(SWEEP_START_FREQ, SWEEP_END_FREQ + 1, SWEEP_STEP_SIZE))
        self.idx = 0
        self.state = "INIT"
        self.paused = False
        self.skip_req = False
        self.current_freq = self.freqs[self.idx]
        self.current_amp = 0.0  # Initialized here to ensure it exists for early raw logging
        
        self.Kp, self.Ki, self.Kd = 0.01, 0.002, 0.001
        self.error_sum = 0
        self.last_error = 0
        self.last_tune_time = 0
        self.timer_start = 0
        self.target_rms = TARGET_PEAK_G / np.sqrt(2)

        self.csv_file = open(CSV_FILENAME, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        
        # UPDATED: New CSV Header for raw data logging
        self.csv_writer.writerow([
            "Timestamp", "Freq", "Drive_Amp", "Channel", "X", "Y", "Z"
        ])

    def get_status_text(self):
        if self.paused: return "PAUSED"
        if self.state == "HOLDING":
            time_left = max(0.0, STABILITY_WINDOW - (time.time() - self.timer_start))
            return f"Holding ({time_left:.1f}s)"
        elif self.state == "COLLECTING":
            time_left = max(0.0, COLLECT_TIME_SEC - (time.time() - self.timer_start))
            return f"Collecting Data ({time_left:.1f}s)"
        elif self.state == "DONE":
            return "SWEEP COMPLETE"
        else:
            return self.state

    def run_tick(self):
        if self.paused or self.state == "DONE": return
        if self.skip_req:
            self.skip_req = False
            self.next_freq()
            return

        now = time.time()
        if self.state == "INIT":
            self.current_amp = 0.005 
            self.error_sum = 0
            send_command_async(f"wavegen set frequency {self.current_freq}")
            send_command_async(f"wavegen set amplitude {self.current_amp}")
            self.state = "TUNING"
            self.last_tune_time = now + 0.5 
            return

        rms_0 = get_ac_rms(sensor_data[0]['z'])
        rms_2 = get_ac_rms(sensor_data[2]['z'])
        
        # Wait until the buffers actually have a little data before tuning
        if rms_0 == 0.0 or rms_2 == 0.0:
            return 

        current_rms = (rms_0 + rms_2) / 2.0
        error = self.target_rms - current_rms
        in_bounds = abs(error) <= (self.target_rms * TOLERANCE_PCT)

        if self.state == "TUNING":
            if now - self.last_tune_time >= UPDATE_INTERVAL:
                if in_bounds:
                    self.state = "HOLDING"
                    self.timer_start = now
                    print(f"[*] Target {TARGET_PEAK_G}G reached at {self.current_freq} Hz | Final Drive Amp: {self.current_amp:.4f}")
                else:
                    dt = now - self.last_tune_time
                    
                    # Anti-Windup Logic
                    if self.current_amp < MAX_AMPLITUDE or error < 0:
                        self.error_sum += error * dt
                        
                    adj = (self.Kp * error) + (self.Ki * self.error_sum) + (self.Kd * (error - self.last_error)/dt)
                    self.current_amp = max(0.005, min(MAX_AMPLITUDE, self.current_amp + adj))
                    send_command_async(f"wavegen set amplitude {self.current_amp:.4f}")
                    self.last_error = error; self.last_tune_time = now

        elif self.state == "HOLDING":
            if not in_bounds: self.state = "TUNING"
            elif now - self.timer_start >= STABILITY_WINDOW:
                self.state = "COLLECTING"; self.timer_start = now

        elif self.state == "COLLECTING":
            # UPDATED: Removed the old summary CSV logger from here. 
            # Raw data logging is now handled entirely inside `update_data`.
            if now - self.timer_start >= COLLECT_TIME_SEC:
                self.next_freq()

    def next_freq(self):
        self.idx += 1
        if self.idx >= len(self.freqs):
            self.state = "DONE"
            send_command_async("wavegen stop")
        else:
            self.current_freq = self.freqs[self.idx]
            self.state = "INIT"

controller = SweepController()

# --- PLOT SETUP ---
fig = plt.figure(figsize=(16, 9))
fig.suptitle(f"Automated Vibration Sweep | Target: {TARGET_PEAK_G} G Peak", fontsize=16, fontweight='bold')

gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, top=0.90)
axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
lines = {}
for i, chan in enumerate(PLOT_CHANNELS):
    ax = axs[i]
    lines[chan] = {ax_n: ax.plot([], [], label=ax_n.upper())[0] for ax_n in ['x', 'y', 'z']}
    ax.set_xlim(0, WINDOW_SIZE); ax.set_ylim(-4.0, 4) 
    ax.set_title(f"Chan {chan}: {CHANNEL_LABELS[chan]}")
    ax.legend(loc='upper right')

ax_overlay = fig.add_subplot(gs[1, :])
line_ov_0, = ax_overlay.plot([], [], label='Bath 1 Z', color='purple')
line_ov_2, = ax_overlay.plot([], [], label='Bath 2 Z', color='darkorange')
ax_overlay.set_xlim(0, WINDOW_SIZE); ax_overlay.set_ylim(-2, 2)
ax_overlay.set_title("Overlay: Bath 1 vs Bath 2 (Z)")
ax_overlay.legend()

def on_key_press(event):
    if event.key.lower() == 'p': controller.paused = not controller.paused
    elif event.key.lower() == 's': controller.skip_req = True

fig.canvas.mpl_connect('key_press_event', on_key_press)

def update_data(frame):
    lines_processed = 0
    while device.in_waiting and lines_processed < 60:
        line = device.readline().decode('utf-8', errors='ignore').strip()
        lines_processed += 1
        if line.startswith("data"):
            parts = line.split()
            try:
                for i in range(int(parts[1])):
                    idx = 2 + (i * 5)
                    ch = int(parts[idx])
                    timestamp = int(parts[idx+1])
                    ts_sec = timestamp / 1000000.0
                    if ch in PLOT_CHANNELS:
                        x, y, z = float(parts[idx+2]), float(parts[idx+3]), float(parts[idx+4])
                        
                        # Gravity offsets
                        if ch in [0, 2]: z -= 1.0
                        elif ch == 4: y -= 1.0
                        
                        sensor_data[ch]['x'].append(x)
                        sensor_data[ch]['y'].append(y)
                        sensor_data[ch]['z'].append(z)
                        sensor_data[ch]['t'].append(ts_sec)
                        
                        # UPDATED: Log raw data continuously as it arrives
                        controller.csv_writer.writerow([
                            round(ts_sec, 6),      # Device timestamp in seconds with microsecond precision
                            controller.current_freq, 
                            round(controller.current_amp, 4), 
                            ch, 
                            round(x, 4), round(y, 4), round(z, 4) # Truncate sensor precision
                        ])
            except Exception as e: 
                continue
            
    controller.run_tick()
    up_lines = []
    
    for ch in PLOT_CHANNELS:
        for ax_n in ['x', 'y', 'z']:
            lines[ch][ax_n].set_data(range(len(sensor_data[ch][ax_n])), sensor_data[ch][ax_n])
            up_lines.append(lines[ch][ax_n])
            
    line_ov_0.set_data(range(len(sensor_data[0]['z'])), sensor_data[0]['z'])
    line_ov_2.set_data(range(len(sensor_data[2]['z'])), sensor_data[2]['z'])
    up_lines.extend([line_ov_0, line_ov_2])
    
    return up_lines

# --- STARTUP ---
print("--- PRE-FLIGHT (DISCOVERY MODE) ---")
send_command_sync("wavegen stop")
for ch in INIT_CHANNELS: 
    send_command_sync(f"sensor {ch} stop accel")
    send_command_sync(f"sensor {ch} set accel range 8")
    send_command_sync(f"sensor {ch} set accel odr {ODR_SETTING}")
    send_command_sync(f"sensor {ch} start accel")

print("\n--- STARTING WAVEGEN ---")
send_command_sync("wavegen set waveform sine")
send_command_sync("wavegen start")

ani = FuncAnimation(fig, update_data, interval=30, blit=True)
plt.show()

# Cleanup
device.write("wavegen stop\n".encode())
for ch in INIT_CHANNELS: device.write(f"sensor {ch} stop accel\n".encode())
device.close()
controller.csv_file.close()
