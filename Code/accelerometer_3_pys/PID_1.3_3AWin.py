"""Three-accelerometer sweep acquisition.

CSV X/Y/Z are RAW sensor axes, including DC/gravity, for channels 0, 2, 4.
Bath vertical = Z; shaker vertical provisionally = Y (verify mounting).
Later AC planar RMS: baths sqrt(std(X)**2 + std(Y)**2),
shaker sqrt(std(X)**2 + std(Z)**2) when shaker Y is vertical.
Rotation around vertical does not change combined planar RMS; tilt does.
Set PORT for your computer (for example 'COM3' on Windows).
"""
import serial
import time
import csv
import datetime
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from collections import deque

# --- CONFIGURATION ---
PORT = 'COM5' 
BAUD_RATE = 115200 

# --- SWEEP & CONTROL SETTINGS ---
SWEEP_START_FREQ = 25   
SWEEP_END_FREQ = 300     
SWEEP_STEP_SIZE = 5
TARGET_PEAK_G = 1.0      
MAX_AMPLITUDE = 0.8      
TOLERANCE_PCT = 0.07
STABILITY_WINDOW = 3.0   
UPDATE_INTERVAL = 0.25    
COLLECT_TIME_SEC = 3.0   
WINDOW_SIZE = 100         
ODR_SETTING = 2400        # sample rate
BMASS = 0.070            # bath mass in kg
DEGREE = "180"             # Degree setting
STINGER_LENGTH = 100         # Stinger gap in millimeters
SPACER = 10               # Spacer thickness in millimeters
APP_VERSION = '1.5_3Accel'   # Application version included in file names
PHYS_VERSION = '1.5'      # Physical system version suffix

def build_csv_filename():
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    version_tag = f"{APP_VERSION}-{PHYS_VERSION}"
    stinger_label = f"Total_Stinger_{STINGER_LENGTH}mm_Spacer_{SPACER}mm"
    return f"{timestamp}_v{version_tag}_vibecheck_sweep_{SWEEP_START_FREQ}-{SWEEP_END_FREQ}Hz_{ODR_SETTING}Hz_{TARGET_PEAK_G}G_{DEGREE}F_{BMASS}kg_{stinger_label}.csv"

CSV_FILENAME = build_csv_filename()

# Firmware command ports are distinct from the channel IDs in data packets.
# Existing mapping: command ports 0/1 -> data channels 0/2.
# Third port 2 -> data channel 4 is inferred from that pattern; verify on board.
SENSOR_PORT_TO_CHANNEL = {0: 0, 1: 2, 2: 4}
INIT_CHANNELS = list(SENSOR_PORT_TO_CHANNEL)
PLOT_CHANNELS = list(SENSOR_PORT_TO_CHANNEL.values())
CHANNEL_LABELS = {0: "Bath 1", 2: "Bath 2", 4: "Base shaker"}
SHAKER_VERTICAL_AXIS = 'y'  # Provisional; changing this never changes CSV axes.
VERTICAL_AXES = {0: 'z', 2: 'z', 4: SHAKER_VERTICAL_AXIS}
STREAM_START_TIMEOUT_SEC = 10.0
STREAM_STALE_TIMEOUT_SEC = 2.0
MIN_START_SAMPLES = 20

# --- SERIAL & UTILITY ---
device = None
serial_buffer = bytearray()
last_received = {ch: None for ch in PLOT_CHANNELS}

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

shutdown_initiated = False

def stop_hardware():
    global shutdown_initiated
    if shutdown_initiated:
        return
    shutdown_initiated = True
    print("--- FINAL HARDWARE SHUTDOWN ---")
    send_command_async("wavegen stop")
    for ch in INIT_CHANNELS:
        send_command_async(f"sensor {ch} stop accel")

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
        
        self.Kp, self.Ki, self.Kd = 0.02, 0.004, 0.002
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
        
        # Wait until the buffer actually has a little data before tuning
        if rms_0 == 0.0:
            return 

        current_rms = rms_0
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
        self.csv_file.flush()
        self.idx += 1
        if self.idx >= len(self.freqs):
            self.state = "DONE"
            send_command_async("wavegen stop")
        else:
            self.current_freq = self.freqs[self.idx]
            self.state = "INIT"

def on_key_press(event):
    if (event.key or '').lower() == 'p': controller.paused = not controller.paused
    elif (event.key or '').lower() == 's': controller.skip_req = True

ani = None

def read_sensor_data():
    """Drain available serial bytes; retain incomplete lines between callbacks."""
    serial_buffer.extend(device.read(min(device.in_waiting, 65536)))
    complete_lines = serial_buffer.split(b'\n')
    serial_buffer[:] = complete_lines.pop()
    for raw_line in complete_lines:
        parts = raw_line.decode('utf-8', errors='ignore').split()
        if not parts or parts[0] != "data":
            continue
        try:
            count = int(parts[1])
            if count < 0 or len(parts) != 2 + 5 * count:
                raise ValueError("Invalid data packet length")
            samples = []
            for i in range(count):
                idx = 2 + i * 5
                ch = int(parts[idx])
                ts_sec = int(parts[idx + 1]) / 1000000.0
                values = tuple(float(v) for v in parts[idx + 2:idx + 5])
                if not all(np.isfinite(v) for v in values):
                    raise ValueError("Non-finite acceleration")
                samples.append((ch, ts_sec, values))
        except (ValueError, IndexError):
            print("Warning: skipped malformed sensor packet")
            continue
        for ch, ts_sec, values in samples:
            if ch not in sensor_data:
                continue
            for axis, value in zip(('x', 'y', 'z'), values):
                sensor_data[ch][axis].append(value)
            sensor_data[ch]['t'].append(ts_sec)
            last_received[ch] = time.monotonic()
            # Preserve RAW sensor axes; do not swap Y/Z or guess gravity sign.
            if controller.state == "COLLECTING" and not controller.paused:
                controller.csv_writer.writerow([
                    round(ts_sec, 6), controller.current_freq,
                    round(controller.current_amp, 4), ch, *values
                ])


def get_ac_trace(values):
    """Remove measured DC for display only; raw CSV and buffers stay intact."""
    arr = np.asarray(values, dtype=float)
    return arr - arr.mean() if arr.size else arr


def wait_for_all_sensors():
    deadline = time.monotonic() + STREAM_START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        read_sensor_data()
        now = time.monotonic()
        if all(len(sensor_data[ch]['t']) >= MIN_START_SAMPLES
               and last_received[ch] is not None
               and now - last_received[ch] < STREAM_STALE_TIMEOUT_SEC
               for ch in PLOT_CHANNELS):
            print("Verified data streams: channels 0, 2, 4")
            return
        time.sleep(0.01)
    missing = [ch for ch in PLOT_CHANNELS
               if len(sensor_data[ch]['t']) < MIN_START_SAMPLES
               or last_received[ch] is None
               or time.monotonic() - last_received[ch] >= STREAM_STALE_TIMEOUT_SEC]
    raise RuntimeError(f"Missing/stale data channels {missing}. "
                       "Check wiring and SENSOR_PORT_TO_CHANNEL; sweep not started.")


def update_data(frame):
    read_sensor_data()
    stale = [ch for ch in PLOT_CHANNELS if last_received[ch] is None
             or time.monotonic() - last_received[ch] >= STREAM_STALE_TIMEOUT_SEC]
    if stale:
        print(f"Acquisition stopped: no recent data from channels {stale}.")
        controller.state = "DONE"
    controller.run_tick()
    if controller.state == "DONE":
        if ani is not None and getattr(ani, 'event_source', None) is not None:
            ani.event_source.stop()
            ani._stop()
        stop_hardware()
        plt.close(fig)
        return []
    up_lines = []
    
    for ch in PLOT_CHANNELS:
        for ax_n in ['x', 'y', 'z']:
            lines[ch][ax_n].set_data(range(len(sensor_data[ch][ax_n])), get_ac_trace(sensor_data[ch][ax_n]))
            up_lines.append(lines[ch][ax_n])
            
    for ch, line in overlay_lines.items():
        values = get_ac_trace(sensor_data[ch][VERTICAL_AXES[ch]])
        line.set_data(range(len(values)), values)
        up_lines.append(line)

    return up_lines

def main():
    global device, controller, fig, lines, overlay_lines, ani
    if SHAKER_VERTICAL_AXIS not in ('x', 'y', 'z'):
        raise ValueError("SHAKER_VERTICAL_AXIS must be x, y, or z")
    device = serial.Serial(PORT, BAUD_RATE, timeout=0.01)
    controller = None
    try:
        controller = SweepController()
        # --- PLOT SETUP ---
        fig = plt.figure(figsize=(16, 9))
        fig.suptitle(f"Automated Vibration Sweep | Target: {TARGET_PEAK_G} G Peak", fontsize=16, fontweight='bold')

        gs = gridspec.GridSpec(2, len(PLOT_CHANNELS), figure=fig, hspace=0.4, top=0.90)
        axs = [fig.add_subplot(gs[0, i]) for i in range(len(PLOT_CHANNELS))]
        lines = {}
        for i, chan in enumerate(PLOT_CHANNELS):
            ax = axs[i]
            lines[chan] = {ax_n: ax.plot([], [], label=ax_n.upper())[0] for ax_n in ['x', 'y', 'z']}
            ax.set_xlim(0, WINDOW_SIZE); ax.set_ylim(-4.0, 4) 
            ax.set_title(f"Chan {chan}: {CHANNEL_LABELS[chan]}")
            ax.set_xlabel("Sample index (per sensor)")
            ax.set_ylabel("AC acceleration (g)")
            ax.legend(loc='upper right')

        ax_overlay = fig.add_subplot(gs[1, :])
        overlay_lines = {
            ch: ax_overlay.plot([], [], label=f"{CHANNEL_LABELS[ch]} {VERTICAL_AXES[ch].upper()}")[0]
            for ch in PLOT_CHANNELS
        }
        ax_overlay.set_xlim(0, WINDOW_SIZE); ax_overlay.set_ylim(-2, 2)
        ax_overlay.set_title("Vertical AC overlay (shaker axis provisional; sample indices are not synchronized)")
        ax_overlay.set_xlabel("Sample index (per sensor)")
        ax_overlay.set_ylabel("AC acceleration (g)")
        ax_overlay.legend()

        fig.canvas.mpl_connect('key_press_event', on_key_press)
        # --- STARTUP ---
        print("--- PRE-FLIGHT: THREE ACCELEROMETERS ---")
        print(f"CSV: {CSV_FILENAME}")
        print(f"Command port -> data channel: {SENSOR_PORT_TO_CHANNEL}")
        send_command_sync("wavegen stop")
        for ch in INIT_CHANNELS: 
            send_command_sync(f"sensor {ch} stop accel")
            send_command_sync(f"sensor {ch} set accel range 8")
            send_command_sync(f"sensor {ch} set accel odr {ODR_SETTING}")
            # Verify ODR setting
            device.write(f"sensor {ch} get accel odr\n".encode('utf-8'))
            start_time = time.time()
            while (time.time() - start_time) < 1.0:
                line = device.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    print(f"Channel {ch} accel ODR response: {line}")
                    break
            send_command_sync(f"sensor {ch} start accel")

        wait_for_all_sensors()

        print("\n--- STARTING WAVEGEN ---")
        send_command_sync("wavegen set waveform sine")
        send_command_sync(f"wavegen set frequency {SWEEP_START_FREQ}")
        send_command_sync("wavegen set amplitude 0.005")
        send_command_sync("wavegen start")

        ani = FuncAnimation(fig, update_data, interval=30, blit=True, cache_frame_data=False)
        plt.show()

    finally:
        try:
            stop_hardware()
        finally:
            if device.is_open:
                device.close()
            if controller is not None:
                controller.csv_file.close()


if __name__ == '__main__':
    main()
