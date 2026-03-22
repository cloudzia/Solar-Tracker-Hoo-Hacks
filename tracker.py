import serial
import time
import logging
import hid
import struct
from datetime import datetime
from wolfram_checker import WolframSolar

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────
LATITUDE      =  40
LONGITUDE     =  28
WOLFRAM_APPID = "225A76QL7X"
SERIAL_PORT   = "COM4"
BAUD_RATE     = 9600

# PID gains
KP, KI, KD = 3.0, 0.1, 0.8
DEADBAND    = 1.0
LOOP_HZ     = 20

# Panel angle limits

PANEL_ANGLE_MIN = 60.0
PANEL_ANGLE_MAX = 172.0

# DP100 power supply settings
VENDOR_ID           = 0x2E3C
PRODUCT_ID          = 0xAF01
PROFILE             = 0
PSU_VOLTAGE_MV      = 5000   # millivolts — fixed
PSU_CURRENT_MIN     = 0      # milliamps — no movement
PSU_CURRENT_MAX     = 5000    # milliamps — max safe SMA current
PSU_UPDATE_INTERVAL = 2.0    # seconds between PSU updates

# ── HID helpers ─────────────────────────────────────────────
def modbus_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF

def make_packet(cmd, payload=b''):
    pkt = bytearray(64)
    pkt[0] = 0xFB
    pkt[1] = cmd
    pkt[2] = 0x00
    pkt[3] = len(payload)
    for i, b in enumerate(payload):
        pkt[4 + i] = b
    crc = modbus_crc(pkt[:4 + len(payload)])
    pkt[4 + len(payload)]     = crc & 0xFF
    pkt[4 + len(payload) + 1] = (crc >> 8) & 0xFF
    return pkt

def send_recv(dev, pkt):
    dev.write(bytes([0x00]) + bytes(pkt))
    return dev.read(64, timeout_ms=3000)

def set_profile_and_activate(dev, profile, voltage_mv, current_ma):
    pkt = make_packet(0x35, bytes([profile]))
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x35:
        raise RuntimeError("Bad response reading profile")
    data = bytearray(resp[4:14])
    data[0] = 0x40 + profile
    struct.pack_into('<H', data, 2, voltage_mv)
    struct.pack_into('<H', data, 4, current_ma)
    pkt2 = bytearray(64)
    pkt2[0] = 0xFB
    pkt2[1] = 0x35
    pkt2[2] = 0x00
    pkt2[3] = len(data)
    pkt2[4:4+len(data)] = data
    crc = modbus_crc(pkt2[:4+len(data)])
    pkt2[4+len(data)]   = crc & 0xFF
    pkt2[4+len(data)+1] = (crc >> 8) & 0xFF
    dev.write(bytes([0x00]) + bytes(pkt2))
    dev.read(64, timeout_ms=3000)
    data[0] = 0x80 + profile
    pkt3 = bytearray(64)
    pkt3[0] = 0xFB
    pkt3[1] = 0x35
    pkt3[2] = 0x00
    pkt3[3] = len(data)
    pkt3[4:4+len(data)] = data
    crc = modbus_crc(pkt3[:4+len(data)])
    pkt3[4+len(data)]   = crc & 0xFF
    pkt3[4+len(data)+1] = (crc >> 8) & 0xFF
    dev.write(bytes([0x00]) + bytes(pkt3))
    dev.read(64, timeout_ms=3000)

def set_output(dev, profile, on: bool):
    pkt = make_packet(0x35, bytes([profile]))
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x35:
        raise RuntimeError("Bad response reading profile for on/off")
    data = bytearray(resp[4:14])
    data[0] = 0x20 + profile
    data[1] = 0x01 if on else 0x00
    pkt2 = bytearray(64)
    pkt2[0] = 0xFB
    pkt2[1] = 0x35
    pkt2[2] = 0x00
    pkt2[3] = len(data)
    pkt2[4:4+len(data)] = data
    crc = modbus_crc(pkt2[:4+len(data)])
    pkt2[4+len(data)]   = crc & 0xFF
    pkt2[4+len(data)+1] = (crc >> 8) & 0xFF
    dev.write(bytes([0x00]) + bytes(pkt2))
    dev.read(64, timeout_ms=3000)
    print(f"Output {'ON' if on else 'OFF'}")

def read_output(dev):
    pkt = make_packet(0x30)
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x30:
        raise RuntimeError("Bad response from read_output")
    vin  = struct.unpack_from('<H', bytes(resp), 4)[0]
    vout = struct.unpack_from('<H', bytes(resp), 6)[0]
    iout = struct.unpack_from('<H', bytes(resp), 8)[0]
    return vin / 1000, vout / 1000, iout / 1000

# ── Sun altitude → panel angle ──────────────────────────────
def altitude_to_panel_angle(altitude: float, azimuth: float) -> float:
    """
    Maps sun altitude (0-90°) and azimuth to panel physical angle.

    Morning   (az < 180°, sun in east) → tilts from 132° toward 60°
    Afternoon (az > 180°, sun in west) → tilts from 132° toward 170°
    Flat (132°) = sun directly overhead at solar noon

    tilt = how far from flat the panel needs to move
           0° altitude (horizon) = maximum tilt (72° from flat)
           90° altitude (overhead) = no tilt (stay flat at 132°)
    """
    tilt = (1.0 - altitude / 90.0) * (132.0 - 60.0)   # 0 at noon, 72 at horizon

    if azimuth <= 180.0:
        return 132.0 - tilt    # morning — tilt toward 60°
    else:
        return 132.0 + tilt    # afternoon — tilt toward 170°

# ── PID controller ──────────────────────────────────────────
class PID:
    def __init__(self, kp, ki, kd, out_min=0, out_max=255):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_min, out_max
        self.integral   = 0.0
        self.prev_error = 0.0
        self.prev_time  = time.time()

    def compute(self, setpoint: float, measured: float) -> int:
        now = time.time()
        dt  = max(now - self.prev_time, 1e-3)
        error = setpoint - measured
        if abs(error) < DEADBAND:
            self.prev_time = now
            return 0
        self.integral = max(-500, min(500, self.integral + error * dt))
        derivative    = -(measured - self.prev_error) / dt
        output        = (self.kp * error
                         + self.ki * self.integral
                         + self.kd * derivative)
        self.prev_error = measured
        self.prev_time  = now
        return int(max(self.out_min, min(self.out_max, output)))

# ── Map PID duty (0-255) → milliamps ───────────────────────
def duty_to_ma(duty: int) -> int:
    ratio = duty / 255.0
    return int(PSU_CURRENT_MIN + ratio * (PSU_CURRENT_MAX - PSU_CURRENT_MIN))

# ── Main loop ───────────────────────────────────────────────
def run():
    # 1. Start Wolfram Alpha background poller
    wolfram = WolframSolar(WOLFRAM_APPID, LATITUDE, LONGITUDE,
                           poll_interval=60)
    wolfram.start()

    # 2. Connect to Arduino over Serial
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    logger.info(f"Serial connected on {SERIAL_PORT}")

    # 3. Connect to DP100 power supply via HID
    dev = hid.device()
    dev.open(VENDOR_ID, PRODUCT_ID)
    dev.set_nonblocking(False)
    logger.info("Connected to DP100")

    # Set initial voltage, zero current, output on
    set_profile_and_activate(dev, PROFILE, PSU_VOLTAGE_MV, PSU_CURRENT_MIN)
    time.sleep(0.5)
    set_output(dev, PROFILE, True)
    time.sleep(0.5)

    pid           = PID(KP, KI, KD)
    last_ma       = PSU_CURRENT_MIN
    last_psu_time = time.time()
    actual_angle  = PANEL_ANGLE_MIN   # safe default until serial arrives

    print(f"\n{'Time':>10}  {'Alt°':>6}  {'Az°':>6}  {'Target°':>8}  "
          f"{'Actual°':>8}  {'Error°':>8}  {'Duty':>5}  {'mA':>6}")

    try:
        while True:
            loop_start = time.time()

            # 4. Read panel angle from Arduino potentiometer
            line = ser.readline().decode("utf-8").strip()
            if line:
                try:
                    actual_angle = float(line)
                except ValueError:
                    pass

            # 5. Get sun data from Wolfram Alpha cache
            snap         = wolfram.get_snapshot()
            raw_altitude = snap["altitude"] or 0.0
            raw_altitude = max(0.0, raw_altitude)
            azimuth      = snap["azimuth"] or 0.0

            # 6. Compute target panel angle from sun altitude + azimuth
            if not wolfram.is_daytime() or raw_altitude <= 0:
                target_angle = 132.0   # park flat at night
            else:
                target_angle = altitude_to_panel_angle(raw_altitude, azimuth)
                target_angle = max(60.0, min(170.0, target_angle))

            # 7. PID → duty (0-255) → milliamps
            duty = pid.compute(target_angle, actual_angle)
            ma   = duty_to_ma(duty)

            # 8. Send to PSU every PSU_UPDATE_INTERVAL seconds if value changed
            now = time.time()
            if (now - last_psu_time) >= PSU_UPDATE_INTERVAL and ma != last_ma:
                set_profile_and_activate(dev, PROFILE, PSU_VOLTAGE_MV, ma)
                set_output(dev, PROFILE, True)
                logger.info(f"PSU: {last_ma}mA → {ma}mA")
                last_ma       = ma
                last_psu_time = now

            error = target_angle - actual_angle
            print(f"{datetime.now().strftime('%H:%M:%S'):>10}  "
                  f"{raw_altitude:>6.1f}  {azimuth:>6.1f}  "
                  f"{target_angle:>8.2f}  {actual_angle:>8.2f}  "
                  f"{error:>8.2f}  {duty:>5}  {ma:>6}")

            time.sleep(max(0, 1/LOOP_HZ - (time.time() - loop_start)))

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        set_profile_and_activate(dev, PROFILE, PSU_VOLTAGE_MV, 0)
        time.sleep(0.5)
        set_output(dev, PROFILE, False)
        dev.close()
        ser.close()
        logger.info("PSU off. Serial closed. Goodbye.")

if __name__ == "__main__":
    run()