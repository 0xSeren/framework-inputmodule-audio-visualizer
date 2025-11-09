import sys
import time
import subprocess
import argparse
from typing import List, Optional, Tuple
from enum import IntEnum

try:
    import numpy as np
except ImportError:
    print("Error: numpy not installed.")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Error: pyserial not installed.")
    sys.exit(1)

FWK_MAGIC = [0x32, 0xAC]
FRAMEWORK_VID = 0x32AC
LEDMATRIX_PID = 0x0020

def get_default_monitor() -> Optional[str]:
    """Get the monitor source for the default audio output."""
    try:
        result = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        default_sink = result.stdout.strip()
        return f"{default_sink}.monitor"
    except Exception:
        return None

def find_led_matrices() -> List[str]:
    """Find all connected Framework LED matrix devices."""
    return sorted([p.device for p in serial.tools.list_ports.comports()
                   if p.vid == FRAMEWORK_VID and p.pid == LEDMATRIX_PID])

class CommandVals(IntEnum):
    Brightness = 0x00
    DisplayOn = 0x14
    ClearRam = 0x18
    FillRows = 0x22

class LEDMatrix:
    WIDTH = 9
    HEIGHT = 34

    def __init__(self):
        self.ser = None
        self.serial_port = None
        self.connected = False

    def connect(self, serial_port: str) -> bool:
        """Connect to the specified serial port."""
        self.disconnect()
        try:
            self.ser = serial.Serial(serial_port, 115200, timeout=0.1)
            time.sleep(0.1)
            self.serial_port = serial_port
            self.connected = True
            self.send_command(CommandVals.DisplayOn, [0x01])
            self.send_command(CommandVals.ClearRam, [])
            return True
        except Exception as e:
            self.connected = False
            self.ser = None
            return False

    def disconnect(self):
        """Disconnect from the serial port."""
        if self.ser:
            try:
                self.ser.close()
            except:
                pass
        self.ser = None
        self.serial_port = None
        self.connected = False

    def send_command(self, command: int, parameters: List[int] = None) -> bool:
        """Send a command, return True if successful."""
        if not self.connected or not self.ser:
            return False
        if parameters is None:
            parameters = []
        try:
            packet = bytes(FWK_MAGIC + [command] + parameters)
            self.ser.write(packet)
            return True
        except (serial.SerialException, OSError):
            self.connected = False
            return False

    def set_brightness(self, brightness: int) -> bool:
        return self.send_command(CommandVals.Brightness, [max(0, min(255, brightness))])

    def fill_rows(self, widths: List[int], from_right: bool) -> bool:
        direction = 1 if from_right else 0
        return self.send_command(CommandVals.FillRows, widths + [direction])

    def clear(self) -> bool:
        return self.fill_rows([0] * 34, False)

class AudioVisualizer:
    def __init__(self, chunk_size: int = 1024, sample_rate: int = 44100,
                 smoothing: float = 0.0, mirror: bool = False, mono: bool = False):
        self.left_matrix = LEDMatrix()
        self.right_matrix = LEDMatrix()
        self.chunk_size = chunk_size
        self.sample_rate = sample_rate
        self.ffmpeg_proc = None
        self.last_bars_left = [0.0] * 34
        self.last_bars_right = [0.0] * 34
        self.smoothing = smoothing
        self.mirror = mirror
        self.mono = mono
        self.channels = 1 if mono else 2
        self.brightness = 100

        # Monitoring state
        self.current_monitor = None
        self.last_check_time = 0
        self.check_interval = 5.0  # Check every 5 seconds

        # Frequency bands (34 bands from 60Hz to 12kHz)
        min_f, max_f = 60, 12000
        ratio = (max_f / min_f) ** (1/34)
        res = sample_rate / chunk_size
        self.freq_bins = [(int((min_f * ratio**i)/res), int((min_f * ratio**(i+1))/res)) for i in range(34)]

    def connect_matrices(self) -> bool:
        """Find and connect to LED matrices."""
        ports = find_led_matrices()

        if len(ports) < 2:
            return False

        # Try to connect - ACM1 = Left, ACM0 = Right
        left_ok = self.left_matrix.connect(ports[1])
        right_ok = self.right_matrix.connect(ports[0])

        if left_ok:
            print(f"Left matrix: {ports[1]}")
            self.left_matrix.set_brightness(self.brightness)
        if right_ok:
            print(f"Right matrix: {ports[0]}")
            self.right_matrix.set_brightness(self.brightness)

        return left_ok or right_ok

    def check_and_reconnect_matrices(self):
        """Check matrix connections and reconnect if needed."""
        if self.left_matrix.connected and self.right_matrix.connected:
            return

        ports = find_led_matrices()
        if len(ports) < 2:
            return

        if not self.left_matrix.connected:
            # Try to find a port that's not used by right matrix
            for port in ports:
                if port != self.right_matrix.serial_port:
                    if self.left_matrix.connect(port):
                        print(f"Reconnected left matrix: {port}")
                        self.left_matrix.set_brightness(self.brightness)
                        break

        if not self.right_matrix.connected:
            for port in ports:
                if port != self.left_matrix.serial_port:
                    if self.right_matrix.connect(port):
                        print(f"Reconnected right matrix: {port}")
                        self.right_matrix.set_brightness(self.brightness)
                        break

    def start_audio_capture(self, monitor_source: str):
        """Start FFmpeg with the specified monitor source."""
        if self.ffmpeg_proc:
            self.ffmpeg_proc.terminate()
            try:
                self.ffmpeg_proc.wait(timeout=2)
            except:
                self.ffmpeg_proc.kill()

        try:
            cmd = [
                "ffmpeg", "-loglevel", "quiet", "-f", "pulse", "-i", monitor_source,
                "-ac", str(self.channels), "-ar", str(self.sample_rate), "-f", "s16le", "-"
            ]
            self.ffmpeg_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                                 bufsize=self.chunk_size*2*self.channels)
            self.current_monitor = monitor_source
            print(f"Audio: {monitor_source}")
        except Exception as e:
            print(f"Audio capture failed: {e}")
            self.ffmpeg_proc = None

    def check_connections(self):
        """Periodically check audio and matrix connections."""
        now = time.time()
        if now - self.last_check_time < self.check_interval:
            return
        self.last_check_time = now

        # Check audio output
        new_monitor = get_default_monitor()
        if new_monitor and new_monitor != self.current_monitor:
            print(f"\nAudio output changed...")
            self.start_audio_capture(new_monitor)

        # Check matrix connections
        self.check_and_reconnect_matrices()

    def process_channel(self, data: np.ndarray, last_bars: List[float]) -> Tuple[List[int], List[float]]:
        """Process audio data for one channel."""
        fft = np.abs(np.fft.rfft(data * np.hanning(len(data))))

        new_bars = []
        for i, (low, high) in enumerate(self.freq_bins):
            val = np.mean(fft[low:high+1]) if low <= high else 0
            boost = 1.0 + (i / 33) ** 1.5 * 4.0
            new_bars.append(val * boost)

        max_val = max(new_bars) if max(new_bars) > 0 else 1
        new_bars = [val / max_val for val in new_bars]

        bars = []
        updated_last = []
        for i in range(34):
            smoothed = last_bars[i] * self.smoothing + new_bars[i] * (1.0 - self.smoothing)
            updated_last.append(smoothed)
            width = int(1 + smoothed * 8) if smoothed > 0.01 else 0
            bars.append(min(9, width))

        return bars, updated_last

    def apply_mirror(self, bars: List[int]) -> List[int]:
        """Mirror mode: lows in middle, highs at top and bottom."""
        half = bars[:17]
        return half[::-1] + half

    def run(self, brightness: int = 100):
        self.brightness = brightness

        # Initial connection
        print("Connecting to LED matrices...")
        if not self.connect_matrices():
            print("Warning: Could not connect to matrices, will retry...")

        # Start audio capture
        print("Detecting audio output...")
        monitor = get_default_monitor() or "default"
        self.start_audio_capture(monitor)

        mode = "mono" if self.mono else "stereo"
        print(f"Visualizer running ({mode}). Play music!")

        try:
            while True:
                # Check connections every 5 seconds
                self.check_connections()

                if not self.ffmpeg_proc:
                    time.sleep(0.1)
                    continue

                bytes_to_read = self.chunk_size * 2 * self.channels
                raw_data = self.ffmpeg_proc.stdout.read(bytes_to_read)
                if not raw_data:
                    if self.ffmpeg_proc.poll() is not None:
                        # FFmpeg died, try to restart
                        print("Audio capture ended, restarting...")
                        monitor = get_default_monitor() or "default"
                        self.start_audio_capture(monitor)
                    continue

                data = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)
                if len(data) == 0:
                    continue

                if self.mono:
                    bars_left, self.last_bars_left = self.process_channel(data, self.last_bars_left)
                    bars_right = bars_left
                else:
                    left_data = data[0::2]
                    right_data = data[1::2]
                    bars_left, self.last_bars_left = self.process_channel(left_data, self.last_bars_left)
                    bars_right, self.last_bars_right = self.process_channel(right_data, self.last_bars_right)

                if self.mirror:
                    display_left = self.apply_mirror(bars_left)
                    display_right = self.apply_mirror(bars_right)
                else:
                    display_left = bars_left[::-1]
                    display_right = bars_right[::-1]

                # Send to matrices (failures are handled gracefully)
                self.left_matrix.fill_rows(display_left, from_right=False)
                self.right_matrix.fill_rows(display_right, from_right=True)

        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            if self.ffmpeg_proc:
                self.ffmpeg_proc.terminate()
            self.left_matrix.clear()
            self.right_matrix.clear()
            self.left_matrix.disconnect()
            self.right_matrix.disconnect()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--brightness', type=int, default=100)
    parser.add_argument('--smoothing', type=float, default=0.5, help='0.0=instant, 0.9=very smooth')
    parser.add_argument('--mirror', action='store_true', help='Mirror mode: lows in middle, highs at top/bottom')
    parser.add_argument('--mono', action='store_true', help='Use mono audio (default: stereo)')
    args = parser.parse_args()

    vis = AudioVisualizer(smoothing=args.smoothing, mirror=args.mirror, mono=args.mono)
    vis.run(brightness=args.brightness)

if __name__ == "__main__":
    main()
