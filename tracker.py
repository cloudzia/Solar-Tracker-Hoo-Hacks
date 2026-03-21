import serial
import time
import logging
import pysolar.solar as solar
from datetime import datetime, timezone
from wolfram_checker import WolframSolar

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s")
logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────
LATITUDE      =  38.033
LONGITUDE     = -78.508
WOLFRAM_APPID = "YOUR-APP-ID-HERE"   # from developer.wolframalpha.com
SERIAL_PORT   = "COM3"
BAUD_RATE     = 9600

KP, KI, KD   = 3.0, 0.1, 0.8
DEADBAND      = 1.0
LOOP_HZ       = 20

PANEL_ANGLE_MIN = -45.0
PANEL_ANGLE_MAX =  45.0

# Cross-check threshold — warn if pysolar and Wolfram disagree by this much
CROSSCHECK_THRESHOLD_DEG = 3.0

# Which source wins when they disagree
TRUSTED_SOURCE = "pysolar"   # or "wolfram"

# ── Sun position (pysolar) ──────────────────────────────────
def pysolar_altitude() -> float:
    now = datetime.now(timezone.utc)
    return solar.get_altitude(LATITUDE, LONGITUDE, now)

# ── Cross-check logic ───────────────────────────────────────
def get_target_angle(wolfram: WolframSolar) -> float:
    py_alt = pysolar_altitude()
    wf     = wolfram.get_snapshot()
    wf_alt = wf["altitude"]

    # Use pysolar as baseline; optionally park at night using Wolfram's times
    if not wolfram.is_daytime():
        logger.info("[Night] Sun below horizon — parking panel at 0°")
        return 0.0

    if wf_alt is not None:
        diff = abs(py_alt - wf_alt)
        if diff > CROSSCHECK_THRESHOLD_DEG:
            logger.warning(
                f"[Cross-check] Disagreement: pysolar={py_alt:.2f}°  "
                f"wolfram={wf_alt:.2f}°  delta={diff:.2f}° "
                f"— trusting {TRUSTED_SOURCE}"
            )
        else:
            logger.debug(f"[Cross-check] OK  pysolar={py_alt:.2f}°  "
                         f"wolfram={wf_alt:.2f}°  delta={diff:.2f}°")

    # Pick trusted source
    if TRUSTED_SOURCE == "wolfram" and wf_alt is not None:
        raw = wf_alt
    else:
        raw = py_alt

    # Clamp below horizon
    if raw <= 0:
        return 0.0

    return max(PANEL_ANGLE_MIN, min(PANEL_ANGLE_MAX, raw))

# ── PID (unchanged from before) ─────────────────────────────
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

# ── Main loop ───────────────────────────────────────────────
def run():
    # Start Wolfram background poller
    wolfram = WolframSolar(WOLFRAM_APPID, LATITUDE, LONGITUDE,
                           poll_interval=60)
    wolfram.start()

    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    pid = PID(KP, KI, KD)

    print(f"\n{'Time':>10}  {'Source':>8}  {'Target°':>8}  "
          f"{'Actual°':>8}  {'Error°':>8}  {'PWM':>5}")

    while True:
        loop_start = time.time()

        line = ser.readline().decode("utf-8").strip()
        if not line:
            continue
        try:
            actual_angle = float(line)
        except ValueError:
            continue

        target_angle = get_target_angle(wolfram)
        duty         = pid.compute(target_angle, actual_angle)
        ser.write(f"{duty}\n".encode())

        wf      = wolfram.get_snapshot()
        source  = TRUSTED_SOURCE if wf["altitude"] else "pysolar"
        error   = target_angle - actual_angle

        print(f"{datetime.now().strftime('%H:%M:%S'):>10}  "
              f"{source:>8}  {target_angle:>8.2f}  "
              f"{actual_angle:>8.2f}  {error:>8.2f}  {duty:>5}")

        time.sleep(max(0, 1/LOOP_HZ - (time.time() - loop_start)))

if __name__ == "__main__":
    run()