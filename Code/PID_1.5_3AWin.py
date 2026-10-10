"""Two-stream, three-accelerometer vibration sweep.

Each frequency: tune mean bath Z AC RMS -> BATH_PAIR (channels 0/2)
-> stop Bath 2 -> start shaker -> SHAKER_PAIR (channels 0/4).
Frequency and commanded amplitude are frozen across both capture blocks and
switching. Bath 1 remains streaming. Stop/start are firmware commands, not
Python-side filtering. The supplied firmware powers down the inactive accel.

CSV starts with the original seven columns. Step, Phase, Timestamp_us,
Window_Start_us and Window_End_us identify paired measurement blocks.
Raw X/Y/Z and device timestamps are preserved, never remapped or reset.
Capture windows use the SAME device-time bounds for both members of a pair.
This requires a common, monotonic device microsecond clock; Python cannot
provide hardware sample synchronization. Sequential blocks are not simultaneous.

Shaker vertical is provisionally Y; its planar axes are X/Z. Bath vertical
is Z and planar axes are X/Y. Verify mounting before interpreting results.
Rate-check revision: reads the configured ODR back, sizes RMS windows using it,
uses a 5 ms acquisition timer and 10 Hz plotting, stops unused gyro/fake streams,
and saves detailed diagnostics on failure. It does NOT reorder/drop samples or
rewrite timestamps. This may help host-side backlog, not repair firmware data.
CSV rates are configured nominal rates, not measured achieved sample rates.
Dependencies: pip install pyserial numpy matplotlib
P: pause progression AFTER both blocks (drive continues); P again resumes.
S: skip during tuning only; Q or close window: stop everything.
"""
import csv
import datetime
import math
import re
import time
from collections import deque

import serial
import numpy as np
import matplotlib.pyplot as plt

# --- EXISTING EXPERIMENT SETTINGS ---
PORT = 'COM5'
BAUD_RATE = 115200
SWEEP_START_FREQ = 25
SWEEP_END_FREQ = 300
SWEEP_STEP_SIZE = 5
TARGET_PEAK_G = 1.0
MAX_AMPLITUDE = 0.8
TOLERANCE_PCT = 0.07
STABILITY_WINDOW = 3.0
UPDATE_INTERVAL = 0.25
COLLECT_TIME_SEC = 3.0       # Per pair: 3 seconds + 3 seconds at each frequency.
WINDOW_SIZE = 100
CONTROL_WINDOW_SEC = 0.25  # Keep the RMS estimate long enough as ODR increases.
ODR_SETTING = 3330  # Up to 4995Hz the PID will run, but it will record at 3330Hz.
READ_INTERVAL_MS = 5
PLOT_INTERVAL_SEC = 0.10  # Plot less often than serial polling.
SHOW_LIVE_PLOT = True    # False keeps status/controls but avoids waveform rendering.
BMASS = 0.070
DEGREE = '180'
STINGER_LENGTH = 100
SPACER = 10
APP_VERSION = '1.5_3Accel_Paired_RateCheck'
PHYS_VERSION = '1.5'

# Command port and streamed channel ID are different identifiers.
SENSOR_PORT_TO_CHANNEL = {0: 0, 1: 2, 2: 4}
CHANNEL_TO_PORT = {ch: port for port, ch in SENSOR_PORT_TO_CHANNEL.items()}
CHANNEL_LABELS = {0: 'Bath 1', 2: 'Bath 2', 4: 'Base shaker'}
BATH_PAIR = (0, 2)
SHAKER_PAIR = (0, 4)        # Bath 1 is retained throughout each frequency step.
SHAKER_VERTICAL_AXIS = 'y'
VERTICAL_AXES = {0: 'z', 2: 'z', 4: SHAKER_VERTICAL_AXIS}
# Mean of the two individual Z-axis AC RMS values, NOT RMS of averaged traces.
# Set to (0,) to restore the previous Bath-1-only feedback definition.
FEEDBACK_CHANNELS = BATH_PAIR
STREAM_START_TIMEOUT_SEC = 10.0
STREAM_STALE_TIMEOUT_SEC = 2.0
SWITCH_QUIET_SEC = 0.15     # Observe old stream stop BEFORE enabling its replacement.
SWITCH_SETTLE_SEC = 0.25    # Refill incoming stream before opening a capture window.
DRIVE_SETTLE_SEC = 0.5
MIN_START_SAMPLES = 20
# This is a gross clock/backlog check, not a claim of sample-level synchronization.
MAX_PAIR_CLOCK_SKEW_SEC = 0.1


def build_csv_filename():
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return (f'{timestamp}_v{APP_VERSION}-{PHYS_VERSION}_vibecheck_sweep_'
            f'{SWEEP_START_FREQ}-{SWEEP_END_FREQ}Hz_req{ODR_SETTING}Hz_'
            f'{TARGET_PEAK_G}G_{DEGREE}F_{BMASS}kg_'
            f'Total_Stinger_{STINGER_LENGTH}mm_Spacer_{SPACER}mm.csv')


def get_ac_rms(values):
    return float(np.std(values)) if len(values) >= MIN_START_SAMPLES else 0.0


class Acquisition:
    """One serial reader for replies and data, including during stream switches."""
    def __init__(self, device, clock=time.monotonic):
        self.device, self.clock = device, clock
        self.buffer = bytearray()
        self.replies = deque(maxlen=100)
        buffer_size = max(WINDOW_SIZE, math.ceil(ODR_SETTING * CONTROL_WINDOW_SEC))
        self.data = {ch: {axis: deque(maxlen=buffer_size) for axis in 'xyzt'}
                     for ch in CHANNEL_LABELS}
        self.last_received = {ch: None for ch in CHANNEL_LABELS}
        self.last_timestamp = {ch: None for ch in CHANNEL_LABELS}
        self.samples = {ch: 0 for ch in CHANNEL_LABELS}
        self.on_sample = None
        self.allowed_channels = set(CHANNEL_LABELS)  # Startup stop/drain only.
        self.shut_down = False
        self.initializing = True
        self.configured_odr = {}
        self.recent_records = deque(maxlen=16)
        self.max_backlog_bytes = 0
        self.last_wire_time = self.clock()
        self.diagnostic_path = None

    def send(self, command):
        self.device.write((command + '\n').encode('utf-8'))

    def command(self, command, timeout=1.5):
        self.poll()
        self.replies.clear()
        print(f'Sending: {command}')
        self.send(command)
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            self.poll()
            while self.replies:
                reply = self.replies.popleft()
                if re.search(r'\b(error|fail|failed|invalid)\b', reply, re.I):
                    raise RuntimeError(f'{command}: {reply}')
                if re.search(r'\b(ack|ok)\b', reply, re.I):
                    print(f'   -> Board: {reply}')
                    return reply
            time.sleep(0.005)
        raise RuntimeError(f'No ACK/OK for command: {command}')

    def clear_traces(self, channels):
        for ch in channels:
            for values in self.data[ch].values():
                values.clear()

    def poll(self):
        waiting = self.device.in_waiting
        self.max_backlog_bytes = max(self.max_backlog_bytes, waiting)
        self.buffer.extend(self.device.read(min(waiting, 262144)))
        if len(self.buffer) > 1048576:
            raise RuntimeError('Serial input has no valid line endings.')
        lines = self.buffer.split(b'\n')
        self.buffer[:] = lines.pop()
        for raw_line in lines:
            line = raw_line.decode('utf-8', errors='strict').strip()
            parts = line.split()
            if not parts:
                continue
            if parts[0] != 'data':
                self.replies.append(line)
                if re.search(r'\b(error|failed|invalid)\b', line, re.I):
                    raise RuntimeError(f'Board reported: {line}')
                continue
            self.last_wire_time = self.clock()
            # Discard residual packets ONLY while startup stops/drains all streams.
            # Updating last_wire_time above still requires a quiet drain period.
            # Normal packet/timestamp validation resumes before sensors are started.
            if self.initializing:
                continue
            try:
                count = int(parts[1])
                if count < 0 or len(parts) != 2 + 5 * count:
                    raise ValueError('wrong packet length')
                records = []
                for i in range(count):
                    idx = 2 + 5 * i
                    ch, timestamp = int(parts[idx]), int(parts[idx + 1])
                    xyz = tuple(float(v) for v in parts[idx + 2:idx + 5])
                    if timestamp < 0 or not all(math.isfinite(v) for v in xyz):
                        raise ValueError('invalid measurement')
                    records.append((ch, timestamp, xyz))
            except (ValueError, IndexError) as error:
                raise RuntimeError(f'Malformed data packet: {error}') from error
            for ch, timestamp, xyz in records:
                if ch not in self.data:
                    if not self.initializing:
                        raise RuntimeError(f'Unexpected data channel {ch}; unused streams should be stopped')
                    continue
                if ch not in self.allowed_channels:
                    raise RuntimeError(f'Inactive channel {ch} is still transmitting; '
                                       'cannot maintain two-stream acquisition.')
                old = self.last_timestamp[ch]
                if old is not None and timestamp <= old:
                    context = list(self.recent_records) + [(ch, timestamp, xyz)]
                    raise RuntimeError(
                        f'Channel {ch}: previous={old} us, new={timestamp} us, '
                        f'change={timestamp - old} us; requested ODR={ODR_SETTING}, '
                        f'configured ODR={self.configured_odr.get(ch, "unknown")}; '
                        f'current backlog={self.device.in_waiting} bytes, '
                        f'max observed backlog={self.max_backlog_bytes} bytes; '
                        f'recent raw records (channel, timestamp_us, XYZ)={context}')
                self.recent_records.append((ch, timestamp, xyz))
                self.last_timestamp[ch] = timestamp
                self.last_received[ch] = self.clock()
                self.samples[ch] += 1
                for axis, value in zip('xyz', xyz):
                    self.data[ch][axis].append(value)
                self.data[ch]['t'].append(timestamp / 1e6)
                if self.on_sample is not None:
                    self.on_sample(ch, timestamp, xyz)

    def initialize(self):
        # Stop ALL streams first; never start all three for discovery.
        self.send('wavegen stop')
        self.send('sensor fakedata stop')
        for port in SENSOR_PORT_TO_CHANNEL:
            self.send(f'sensor {port} stop accel')
            self.send(f'sensor {port} stop gyro')
        started = self.clock()
        deadline = started + STREAM_START_TIMEOUT_SEC
        while True:
            self.poll()
            latest = max([started, self.last_wire_time] + [v for v in self.last_received.values()
                                      if v is not None])
            if self.clock() - latest >= SWITCH_QUIET_SEC and not self.device.in_waiting:
                break
            if self.clock() >= deadline:
                raise RuntimeError('Sensors did not stop during initialization.')
            time.sleep(0.005)
        self.allowed_channels.clear()
        self.initializing = False
        for port in SENSOR_PORT_TO_CHANNEL:
            self.command(f'sensor {port} set accel range 8')
            self.command(f'sensor {port} set accel odr {ODR_SETTING}')
            reply = self.command(f'sensor {port} get accel odr')
            match = re.fullmatch(r'(?:ack|ok)\s+(\d+)', reply.strip(), re.I)
            if not match or int(match.group(1)) <= 0:
                raise RuntimeError(f'Cannot verify configured ODR for sensor port {port}: {reply}')
            rate = int(match.group(1))
            ch = SENSOR_PORT_TO_CHANNEL[port]
            self.configured_odr[ch] = rate
            size = max(WINDOW_SIZE, math.ceil(rate * CONTROL_WINDOW_SEC))
            self.data[ch] = {axis: deque(maxlen=size) for axis in 'xyzt'}
            print(f'CHANNEL {ch}: requested {ODR_SETTING} Hz; board configured {rate} Hz')
        if len(set(self.configured_odr.values())) != 1:
            raise RuntimeError(f'Sensors report different ODRs: {self.configured_odr}')
        self.command('wavegen set waveform sine')
        self.clear_traces(CHANNEL_LABELS)
        # Configure does not prove the requested ODR is the actual hardware rate.

    def shutdown(self):
        if self.shut_down:
            return
        self.shut_down = True
        errors = []
        for command in ['wavegen stop', 'sensor fakedata stop'] + [f'sensor {p} stop {kind}'
                                          for p in SENSOR_PORT_TO_CHANNEL for kind in ('accel', 'gyro')]:
            try:
                self.send(command)
            except Exception as error:
                errors.append(f'{command}: {error}')
        if errors:
            print('Shutdown command errors: ' + '; '.join(errors))


class PairSwitcher:
    """Stop, verify silence, then start; no waveform commands are issued here."""
    def __init__(self, acquisition):
        self.a = acquisition
        self.active = set()
        self.target = ()
        self.state = 'IDLE'
        self.started = 0.0
        self.ready_since = None

    def request(self, pair):
        if self.state not in ('IDLE', 'READY'):
            raise RuntimeError('Pair switch already in progress')
        if len(pair) != 2 or len(set(pair)) != 2:
            raise ValueError('Exactly two distinct channels are required')
        self.target = tuple(pair)
        self.leaving = self.active - set(pair)
        self.joining = set(pair) - self.active
        self.started = self.a.clock()
        self.ready_since = None
        for ch in self.leaving:
            self.a.send(f'sensor {CHANNEL_TO_PORT[ch]} stop accel')
        # Allowed still includes the outgoing stream until its queued data drains.
        self.active -= self.leaving
        self.state = 'STOPPING'

    def tick(self):
        now = self.a.clock()
        if self.state == 'READY':
            for ch in self.active:
                if self.a.last_received[ch] is None or now - self.a.last_received[ch] > STREAM_STALE_TIMEOUT_SEC:
                    raise RuntimeError(f'Active channel {ch} stopped streaming')
            return
        if self.state == 'IDLE':
            return
        if now - self.started > STREAM_START_TIMEOUT_SEC:
            raise RuntimeError(f'Pair switch to {self.target} timed out in {self.state}')
        if self.state == 'STOPPING':
            quiet = all(now - max(self.started, self.a.last_received[ch] or self.started)
                        >= SWITCH_QUIET_SEC for ch in self.leaving)
            if not quiet or self.a.device.in_waiting:
                return
            self.a.allowed_channels = set(self.target)
            self.a.clear_traces(self.joining)
            self.start_counts = {ch: self.a.samples[ch] for ch in self.target}
            for ch in self.joining:
                self.a.send(f'sensor {CHANNEL_TO_PORT[ch]} start accel')
            self.active = set(self.target)
            self.state = 'STARTING'
        if self.state == 'STARTING':
            ready = all(self.a.samples[ch] - self.start_counts[ch] >= MIN_START_SAMPLES
                        and now - self.a.last_received[ch] < STREAM_STALE_TIMEOUT_SEC
                        for ch in self.target)
            if ready:
                stamps = [self.a.last_timestamp[ch] for ch in self.target]
                ready = max(stamps) - min(stamps) <= MAX_PAIR_CLOCK_SKEW_SEC * 1e6
            # Incoming bytes are normal during streaming; they must not reset
            # the settle timer. STOPPING retains its separate drain check.
            if not ready:
                self.ready_since = None
                return
            if self.ready_since is None:
                self.ready_since = now
            if now - self.ready_since >= SWITCH_SETTLE_SEC:
                self.state = 'READY'
                print(f'Active pair verified: {self.target}')


class SweepController:
    def __init__(self, acquisition, filename):
        self.a = acquisition
        self.pairs = PairSwitcher(acquisition)
        self.freqs = list(range(SWEEP_START_FREQ, SWEEP_END_FREQ + 1, SWEEP_STEP_SIZE))
        self.idx = 0
        self.current_freq = self.freqs[0]
        self.current_amp = 0.0
        self.target_rms = TARGET_PEAK_G / np.sqrt(2)
        self.Kp, self.Ki, self.Kd = 0.02, 0.004, 0.002
        self.state = 'NEW'
        self.phase = None
        self.pause_requested = False
        self.wave_running = False
        self.failure = None
        self.a.diagnostic_path = str(filename) + '.diagnostics.txt'
        self.csv_file = open(filename, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(['Timestamp', 'Freq', 'Drive_Amp', 'Channel', 'X', 'Y', 'Z',
                                  'Step', 'Phase', 'Timestamp_us', 'Window_Start_us', 'Window_End_us',
                                  'Requested_ODR_Hz', 'Configured_ODR_Hz'])
        self.csv_file.flush()
        self.a.on_sample = self.record_sample

    def start(self):
        self.pairs.request(BATH_PAIR)
        self.state = 'WAIT_BATH'

    def record_sample(self, ch, timestamp, xyz):
        if self.state not in ('COLLECT_BATH', 'COLLECT_SHAKER') or ch not in self.capture_pair:
            return
        if self.window_start <= timestamp < self.window_end:
            self.csv_writer.writerow([timestamp / 1e6, self.current_freq, self.current_amp,
                                      ch, *xyz, self.idx + 1, self.phase, timestamp,
                                      self.window_start, self.window_end, ODR_SETTING,
                                      self.a.configured_odr.get(ch, "")])
            self.capture_counts[ch] += 1

    def begin_frequency(self):
        self.current_amp = 0.005
        self.error_sum = self.last_error = 0.0
        self.a.send(f'wavegen set frequency {self.current_freq}')
        self.a.send(f'wavegen set amplitude {self.current_amp:.4f}')
        if not self.wave_running:
            self.a.send('wavegen start')
            self.wave_running = True
        self.a.clear_traces(BATH_PAIR)
        self.last_tune_time = self.a.clock()
        self.settle_until = self.last_tune_time + DRIVE_SETTLE_SEC
        self.state = 'TUNING'

    def begin_capture(self, phase, pair):
        stamps = [self.a.last_timestamp[ch] for ch in pair]
        if max(stamps) - min(stamps) > MAX_PAIR_CLOCK_SKEW_SEC * 1e6:
            raise RuntimeError('Pair timestamps disagree; check board clock and serial backlog')
        self.phase, self.capture_pair = phase, tuple(pair)
        self.window_start = max(stamps) + 1
        self.window_end = self.window_start + round(COLLECT_TIME_SEC * 1e6)
        self.capture_counts = dict.fromkeys(pair, 0)
        self.capture_started = self.a.clock()
        self.state = 'COLLECT_BATH' if phase == 'BATH_PAIR' else 'COLLECT_SHAKER'
        print(f'{self.current_freq} Hz | {phase} | fixed drive {self.current_amp:.4f}')

    def finish_capture(self):
        if any(n < MIN_START_SAMPLES for n in self.capture_counts.values()):
            raise RuntimeError(f'Insufficient captured samples: {self.capture_counts}')
        self.csv_file.flush()
        print(f'  Completed {self.phase}: samples {self.capture_counts}')
        if self.state == 'COLLECT_BATH':
            self.state = 'WAIT_SHAKER'
            self.phase = None
            self.pairs.request(SHAKER_PAIR)
        else:
            self.advance()

    def advance(self):
        self.phase = None
        self.csv_file.flush()
        self.idx += 1
        if self.idx >= len(self.freqs):
            self.state = 'DONE'
            self.a.shutdown()
        elif self.pause_requested:
            self.state = 'PAUSED'
        else:
            self.current_freq = self.freqs[self.idx]
            self.pairs.request(BATH_PAIR)
            self.state = 'WAIT_BATH'

    def tick(self):
        if self.state in ('NEW', 'DONE', 'ERROR'):
            return
        self.pairs.tick()
        now = self.a.clock()
        if self.state == 'PAUSED':
            return
        if self.state == 'WAIT_BATH':
            if self.pairs.state == 'READY':
                self.begin_frequency()
            return
        if self.state == 'WAIT_SHAKER':
            if self.pairs.state == 'READY':
                self.begin_capture('SHAKER_PAIR', SHAKER_PAIR)
            return
        if self.state in ('COLLECT_BATH', 'COLLECT_SHAKER'):
            # NO PID adjustments, frequency writes, or waveform stops in these states.
            if all(self.a.last_timestamp[ch] >= self.window_end for ch in self.capture_pair):
                self.finish_capture()
            elif now - self.capture_started > COLLECT_TIME_SEC + STREAM_START_TIMEOUT_SEC:
                raise RuntimeError('Capture timed out before both device clocks reached window end')
            return
        if now < self.settle_until:
            return
        if any(len(self.a.data[ch]['z']) < MIN_START_SAMPLES for ch in BATH_PAIR):
            return
        measured = np.mean([get_ac_rms(self.a.data[ch]['z']) for ch in FEEDBACK_CHANNELS])
        error = self.target_rms - measured
        in_bounds = abs(error) <= self.target_rms * TOLERANCE_PCT
        if self.state == 'HOLDING':
            if not in_bounds:
                self.state = 'TUNING'
                self.last_tune_time = now
            elif now - self.hold_started >= STABILITY_WINDOW:
                self.begin_capture('BATH_PAIR', BATH_PAIR)
        elif self.state == 'TUNING' and now - self.last_tune_time >= UPDATE_INTERVAL:
            if in_bounds:
                self.state = 'HOLDING'
                self.hold_started = now
            else:
                dt = now - self.last_tune_time
                if self.current_amp < MAX_AMPLITUDE or error < 0:
                    self.error_sum += error * dt
                adjustment = (self.Kp * error + self.Ki * self.error_sum
                              + self.Kd * (error - self.last_error) / dt)
                # Log the exact quantized amplitude sent to the board.
                self.current_amp = round(max(0.005, min(MAX_AMPLITUDE,
                                                       self.current_amp + adjustment)), 4)
                self.a.send(f'wavegen set amplitude {self.current_amp:.4f}')
            self.last_error, self.last_tune_time = error, now

    def on_key(self, event):
        key = (event.key or '').lower()
        if key == 'q':
            self.state = 'DONE'
            self.a.shutdown()
        elif key == 'p':
            self.pause_requested = not self.pause_requested
            if self.state == 'PAUSED' and not self.pause_requested:
                self.current_freq = self.freqs[self.idx]
                self.pairs.request(BATH_PAIR)
                self.state = 'WAIT_BATH'
            print('Pause after both captures requested' if self.pause_requested else 'Pause cancelled/resumed')
        elif key == 's':
            if self.state in ('TUNING', 'HOLDING'):
                print(f'Skipping {self.current_freq} Hz before capture')
                self.advance()
            else:
                print('Skip ignored: both paired captures must finish uninterrupted')

    def abort(self, error):
        self.failure = str(error)
        self.state = 'ERROR'
        self.a.shutdown()
        print(f'ACQUISITION STOPPED: {error}')
        if self.a.diagnostic_path:
            try:
                with open(self.a.diagnostic_path, 'w') as report:
                    report.write(f'Requested ODR: {ODR_SETTING} Hz\n'
                                 f'Configured ODR by channel: {self.a.configured_odr}\n'
                                 f'Frequency: {self.current_freq} Hz\n'
                                 f'Phase: {self.phase}\n'
                                 f'Max observed serial backlog: {self.a.max_backlog_bytes} bytes\n'
                                 f'Error: {error}\n')
                print(f'Diagnostic saved: {self.a.diagnostic_path}')
            except OSError as save_error:
                print(f'Could not save diagnostic: {save_error}')
        self.a.shutdown()
        self.csv_file.flush()
        print('Last frequency may be incomplete; use Phase and window columns to check it.')


class LiveView:
    """Exactly two vertical traces. Device time is shared, not per-sensor index."""
    def __init__(self, controller):
        self.c, self.a = controller, controller.a
        self.fig, self.ax = plt.subplots(figsize=(13, 6))
        self.lines = [self.ax.plot([], [], lw=1, color=color)[0]
                      for color in ('purple', 'darkorange')]
        self.ax.set_xlabel('Device time relative to newest active sample (s)')
        self.ax.set_ylabel('Vertical AC acceleration (g)')
        self.ax.set_ylim(-2, 2)
        self.ax.grid(True, alpha=0.25)
        self.status = self.fig.text(0.02, 0.02, '')
        self.fig.subplots_adjust(bottom=0.18)
        self.fig.canvas.mpl_connect('key_press_event', controller.on_key)
        self.fig.canvas.mpl_connect('close_event', self.on_close)
        self.last_pair = None
        self.timer = None
        self.last_draw = float("-inf")

    def on_close(self, event):
        if self.timer is not None:
            self.timer.stop()
        self.a.shutdown()

    def draw(self):
        pair = tuple(sorted(self.c.pairs.active))
        if pair != self.last_pair:
            for i, line in enumerate(self.lines):
                line.set_visible(i < len(pair))
                if i < len(pair):
                    ch = pair[i]
                    line.set_label(f'{CHANNEL_LABELS[ch]} {VERTICAL_AXES[ch].upper()}')
            handles = self.lines[:len(pair)]
            old_legend = self.ax.get_legend()
            if old_legend is not None:
                old_legend.remove()
            if handles:
                self.ax.legend(handles=handles, loc='upper right')
            self.last_pair = pair
        newest = max([self.a.data[ch]['t'][-1] for ch in pair
                      if self.a.data[ch]['t']] or [0.0])
        oldest = 0.0
        peak = 0.0
        for line, ch in zip(self.lines, pair):
            t = np.asarray(self.a.data[ch]['t'])[-WINDOW_SIZE:]
            full_y = np.asarray(self.a.data[ch][VERTICAL_AXES[ch]])
            y = full_y[-WINDOW_SIZE:]
            if t.size:
                t = t - newest
                oldest = min(oldest, float(t[0]))
                y = y - full_y.mean()  # Longer DC estimate; CSV remains raw.
                peak = max(peak, float(np.max(np.abs(y))))
            line.set_data(t, y)
        self.ax.set_xlim(min(oldest, -WINDOW_SIZE / max(self.a.configured_odr.values(), default=ODR_SETTING)), 0.0)
        limit = max(2.0, peak * 1.1)
        self.ax.set_ylim(-limit, limit)
        self.ax.set_title(f'{self.c.current_freq} Hz | Drive {self.c.current_amp:.4f} | {self.c.state}')
        self.status.set_text('Target: mean bath Z RMS = '
                             f'{self.c.target_rms:.3f} g | P: pause after both blocks | S: skip tuning | Q: stop'
                             + (' | Pause queued' if self.c.pause_requested else ''))
        return self.lines + [self.status]

    def update(self, frame):
        try:
            self.a.poll()
            self.c.tick()
            if self.c.state in ('DONE', 'ERROR'):
                if self.timer is not None:
                    self.timer.stop()
                plt.close(self.fig)
                return []
            if self.a.clock() - self.last_draw >= PLOT_INTERVAL_SEC:
                if SHOW_LIVE_PLOT:
                    self.draw()
                else:
                    self.ax.set_title(f'{self.c.current_freq} Hz | {self.c.state} | live traces disabled')
                self.fig.canvas.draw_idle()
                self.last_draw = self.a.clock()
            return []
        except Exception as error:
            self.c.abort(error)
            if self.timer is not None:
                self.timer.stop()
            plt.close(self.fig)
            return []

    def on_timer(self):
        self.update(0)
        return self.c.state not in ('DONE', 'ERROR')


def main():
    if SHAKER_VERTICAL_AXIS not in 'xyz' or len(SHAKER_VERTICAL_AXIS) != 1:
        raise ValueError('SHAKER_VERTICAL_AXIS must be x, y, or z')
    if not FEEDBACK_CHANNELS or not set(FEEDBACK_CHANNELS) <= set(BATH_PAIR):
        raise ValueError('Feedback must use one or both bath sensors')
    filename = build_csv_filename()
    device = serial.Serial(PORT, BAUD_RATE, timeout=0, write_timeout=2.0)
    acquisition = Acquisition(device)
    controller = None
    try:
        controller = SweepController(acquisition, filename)
        print(f'CSV: {filename}\nTwo-stream sequence: {BATH_PAIR} -> {SHAKER_PAIR}')
        acquisition.initialize()
        controller.start()
        view = LiveView(controller)
        view.timer = view.fig.canvas.new_timer(interval=READ_INTERVAL_MS)
        view.timer.add_callback(view.on_timer)
        view.timer.start()
        plt.show()
        if controller.failure:
            raise RuntimeError(controller.failure)
    finally:
        acquisition.shutdown()
        device.close()
        if controller is not None:
            controller.csv_file.close()


if __name__ == '__main__':
    main()
