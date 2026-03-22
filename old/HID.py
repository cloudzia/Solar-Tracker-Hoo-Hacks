import hid
import struct

# ============================
# SET YOUR VALUES HERE
# ============================
TARGET_VOLTAGE = 5000   # millivolts (e.g. 5000 = 5.0V)
TARGET_CURRENT = 500    # milliamps  (e.g.  500 = 0.5A)
OUTPUT_ON = True        # True to enable output, False to disable
PROFILE = 0             # Profile slot to use (0-9)
# ============================

VENDOR_ID  = 0x2E3C
PRODUCT_ID = 0xAF01

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
    """Build a 64-byte packet for the DP100."""
    pkt = bytearray(64)
    pkt[0] = 0xFB           # host header
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
    """Send a packet and return the 64-byte response."""
    # Windows: prepend a 0x00 report ID byte
    dev.write(bytes([0x00]) + bytes(pkt))
    response = dev.read(64, timeout_ms=3000)
    return response

def get_active_profile(dev):
    """Read the currently active profile and return its raw response."""
    pkt = make_packet(0x35, bytes([0x80]))
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x35:
        raise RuntimeError("Bad response from get_active_profile")
    return resp

def set_profile_and_activate(dev, profile, voltage_mv, current_ma):
    """Write voltage/current to a profile slot and activate it."""
    # First read current profile data so we keep OVP/OCP bytes intact
    pkt = make_packet(0x35, bytes([profile]))
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x35:
        raise RuntimeError("Bad response reading profile")

    # Build change packet: upper nibble 0x4 = change profile
    data = bytearray(resp[4:14])   # 10 bytes of profile data
    data[0] = 0x40 + profile       # command nibble | profile index
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

    # Activate the profile: upper nibble 0x8
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
    print(f"Profile {profile} set to {voltage_mv}mV / {current_ma}mA and activated.")

def set_output(dev, profile, on: bool):
    """Switch output on or off for the given profile."""
    pkt = make_packet(0x35, bytes([profile]))
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x35:
        raise RuntimeError("Bad response reading profile for on/off")

    data = bytearray(resp[4:14])
    data[0] = 0x20 + profile       # 0x2x = switch command
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
    """Read actual output voltage and current."""
    pkt = make_packet(0x30)
    resp = send_recv(dev, pkt)
    if not resp or resp[1] != 0x30:
        raise RuntimeError("Bad response from read_output")
    vin  = struct.unpack_from('<H', bytes(resp), 4)[0]
    vout = struct.unpack_from('<H', bytes(resp), 6)[0]
    iout = struct.unpack_from('<H', bytes(resp), 8)[0]
    return vin, vout, iout

# ─── CONVENIENCE FUNCTIONS ───────────────────────────────────────────────────
# These keep track of the last set values so you only change one at a time.

_current_voltage = TARGET_VOLTAGE
_current_current = TARGET_CURRENT

def set_voltage(dev, voltage_v):
    """Set output voltage. Pass value in VOLTS (e.g. 5.0 for 5V)."""
    global _current_voltage
    _current_voltage = int(voltage_v * 1000)  # convert to millivolts
    set_profile_and_activate(dev, PROFILE, _current_voltage, _current_current)

def set_current(dev, current_a):
    """Set current limit. Pass value in AMPS (e.g. 0.5 for 500mA)."""
    global _current_current
    _current_current = int(current_a * 1000)  # convert to milliamps
    set_profile_and_activate(dev, PROFILE, _current_voltage, _current_current)

# ─── MAIN ────────────────────────────────────────────────────────────────────

dev = hid.device()
dev.open(VENDOR_ID, PRODUCT_ID)
dev.set_nonblocking(False)
print("Connected to DP100")

try:
    # Apply initial values from the top of the file
    set_profile_and_activate(dev, PROFILE, TARGET_VOLTAGE, TARGET_CURRENT)
    set_output(dev, PROFILE, OUTPUT_ON)

    # --- Example: update voltage or current any time like this ---
    # set_voltage(dev, 3.3)   # change to 3.3V
    # set_current(dev, 0.3)   # change current limit to 300mA
    # set_output(dev, PROFILE, False)  # turn output off

    vin, vout, iout = read_output(dev)
    print(f"Vin:  {vin  / 1000:.3f} V")
    print(f"Vout: {vout / 1000:.3f} V")
    print(f"Iout: {iout / 1000:.3f} A")
finally:
    dev.close()
