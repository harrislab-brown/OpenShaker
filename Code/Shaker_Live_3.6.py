import serial
import time
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.animation import FuncAnimation
from collections import deque

# --- CONFIGURATION ---
PORT = '/dev/tty.usbmodem3646396830331' 
BAUD_RATE = 115200 # Kept at 115200 for high-speed streaming

# Directly input your target frequency and amplitude here
TARGET_FREQ = 100 
DRIVE_AMP = 0.065        

INIT_CHANNELS = [0, 1, 4]   # Hardware IDs needed to turn them on
PLOT_CHANNELS = [0, 2, 4]   # Software IDs outputted by the board
WINDOW_SIZE = 50    

CHANNEL_LABELS = {
    0: "Bath 1",
    2: "Bath 2",     
    4: "Base Shaker"
}

# --- SERIAL SETUP ---
device = serial.Serial(PORT, BAUD_RATE, timeout=0.01)

def send_command(cmd, timeout_sec=1.5):
    """Sends command, waits for 'ack', and catches errors."""
    print(f"Sending: {cmd}")
    device.write(f"{cmd}\n".encode('utf-8')) 
    
    start_time = time.time()
    
    while (time.time() - start_time) < timeout_sec:
        line = device.readline().decode('utf-8', errors='ignore').strip()
        
        if line:
            if line.startswith("data"):
                continue 
            print(f"   -> Board Reply: {line}") 
            
            if "ack" in line.lower() or "ok" in line.lower():
                return line
            if "error" in line.lower() or "nack" in line.lower():
                print(f"   -> [!] COMMAND FAILED: {cmd}")
                return line
    return None

# --- DATA STORAGE ---
sensor_data = {
    chan: {
        'x': deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE),
        'y': deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE),
        'z': deque([0]*WINDOW_SIZE, maxlen=WINDOW_SIZE)
    } for chan in PLOT_CHANNELS
}

# --- PLOT SETUP ---
fig = plt.figure(figsize=(16, 9)) 
gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.4, wspace=0.25, top=0.88, bottom=0.08)

title_text = f"Live Acceleration - Channels {PLOT_CHANNELS} ({TARGET_FREQ}Hz)\n"
title_text += f"Drive Amp: {DRIVE_AMP:.3f}"
fig.suptitle(title_text, fontsize=14)

axs = [fig.add_subplot(gs[0, i]) for i in range(3)]
lines = {}
colors = {'x': 'red', 'y': 'green', 'z': 'blue'}

for i, chan in enumerate(PLOT_CHANNELS):
    ax = axs[i]
    line_x, = ax.plot([], [], label='X-Axis', color=colors['x'], alpha=0.7)
    line_y, = ax.plot([], [], label='Y-Axis', color=colors['y'], alpha=0.7)
    line_z, = ax.plot([], [], label='Z-Axis', color=colors['z'], linewidth=1.5)
    
    lines[chan] = {'x': line_x, 'y': line_y, 'z': line_z}
    
    ax.set_xlim(0, WINDOW_SIZE)
    ax.set_ylim(-2, 2) 
    ax.set_title(f"Chan {chan}: {CHANNEL_LABELS[chan]}")
    ax.set_ylabel("G-Force (G)")
    ax.set_xlabel("Sample History")
    ax.grid(True, linestyle='--', alpha=0.1)
    
    if i == 2: 
        ax.legend(loc='upper right')

ax_overlay = fig.add_subplot(gs[1, :])
line_overlay_0, = ax_overlay.plot([], [], label=f'Chan 0 ({CHANNEL_LABELS[0]}) - Z', color='purple', linewidth=2)
line_overlay_2, = ax_overlay.plot([], [], label=f'Chan 2 ({CHANNEL_LABELS[2]}) - Z', color='darkorange', linewidth=2)

ax_overlay.set_xlim(0, WINDOW_SIZE)
ax_overlay.set_ylim(-2, 2)
ax_overlay.set_title("Z-Axis Overlay: Bath 1 vs Bath 2")
ax_overlay.set_ylabel("G-Force (G)")
ax_overlay.set_xlabel("Sample History")
ax_overlay.grid(True, linestyle='--', alpha=0.3)
ax_overlay.legend(loc='upper right')

# --- SINGLE THREADED GUI UPDATE (Reverted to 3.1.1 architecture) ---
def update_data(frame):
    # Process all available data in the buffer before drawing
    while device.in_waiting:
        try:
            line = device.readline().decode('utf-8', errors='ignore').strip()
            if line.startswith("data"):
                parts = line.split()
                num_points = int(parts[1])
                for i in range(num_points):
                    idx = 2 + (i * 5)
                    chan = int(parts[idx])
                    
                    if chan in PLOT_CHANNELS:
                        x = float(parts[idx+2])
                        y = float(parts[idx+3])
                        z = float(parts[idx+4])
                        
                        if chan in [0, 2]:
                            z -= 1.0
                        elif chan == 4:
                            y -= 1.0
                        
                        sensor_data[chan]['x'].append(x)
                        sensor_data[chan]['y'].append(y)
                        sensor_data[chan]['z'].append(z)
        except (ValueError, IndexError):
            # Ignore broken packets
            continue

    all_lines = []
    
    # Update Top Plots
    for chan in PLOT_CHANNELS:
        lines[chan]['x'].set_data(range(WINDOW_SIZE), sensor_data[chan]['x'])
        lines[chan]['y'].set_data(range(WINDOW_SIZE), sensor_data[chan]['y'])
        lines[chan]['z'].set_data(range(WINDOW_SIZE), sensor_data[chan]['z'])
        all_lines.extend([lines[chan]['x'], lines[chan]['y'], lines[chan]['z']])
        
    # Update Overlay Plot
    line_overlay_0.set_data(range(WINDOW_SIZE), sensor_data[0]['z'])
    line_overlay_2.set_data(range(WINDOW_SIZE), sensor_data[2]['z'])
    all_lines.extend([line_overlay_0, line_overlay_2])
    
    return all_lines


# --- INITIALIZATION ---
print("--- PRE-FLIGHT CHECK ---")
print("Quieting board from previous runs...")
send_command("wavegen stop", timeout_sec=0.5)

for chan in INIT_CHANNELS:
    send_command(f"sensor {chan} stop accel", timeout_sec=0.5)

device.reset_input_buffer() 
time.sleep(0.5)

print(f"\n--- CONFIGURING SENSORS: {TARGET_FREQ}Hz @ {DRIVE_AMP} Amp ---")
for chan in INIT_CHANNELS: 
    send_command(f"sensor {chan} set accel range 8") 
    send_command(f"sensor {chan} set accel odr 1660") 
    send_command(f"sensor {chan} start accel") 
    time.sleep(0.5) 

print("\n--- STARTING WAVEGEN ---")
send_command(f"wavegen set frequency {TARGET_FREQ}")
send_command(f"wavegen set amplitude {DRIVE_AMP}")
send_command("wavegen set waveform sine")
send_command("wavegen start")

# Interval reverted to 20ms with blit=True
ani = FuncAnimation(fig, update_data, interval=20, blit=True)

try:
    plt.show()
finally:
    print("\nClosing connection and stopping wavegen...")
    device.write("wavegen stop\n".encode('utf-8'))
    for chan in INIT_CHANNELS:
        device.write(f"sensor {chan} stop accel\n".encode('utf-8'))
    device.close()
