import requests
import re
import time
import threading
import logging
from datetime import datetime, timezone, date

logger = logging.getLogger(__name__)

WOLFRAM_URL = "https://api.wolframalpha.com/v2/query"


class WolframSolar:
    def __init__(self, app_id: str, latitude: float, longitude: float,
                 poll_interval: int = 60):
        self.app_id        = app_id
        self.lat           = latitude
        self.lon           = longitude
        self.poll_interval = poll_interval
        self.altitude     = None
        self.azimuth      = None
        self.sunrise      = None
        self.sunset       = None
        self.last_updated = None
        self._lock   = threading.Lock()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)

    def start(self):
        self._thread.start()
        logger.info("Wolfram Alpha poller started.")
        logger.info("Waiting for first Wolfram Alpha reading...")
        for _ in range(30):
            with self._lock:
                if self.altitude is not None:
                    break
            time.sleep(1)
        else:
            logger.warning("Timed out waiting for first Wolfram reading — will use 0° until data arrives.")

    def _query(self, input_str: str) -> dict:
        params = {
            "appid":  self.app_id,
            "input":  input_str,
            "output": "JSON",
            "format": "plaintext"
        }
        resp = requests.get(WOLFRAM_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("queryresult", {}).get("success"):
            raise ValueError(f"Wolfram query unsuccessful for: {input_str}")
        return data["queryresult"]

    def _poll_loop(self):
        while True:
            try:
                self._update_sun_position()
                self._update_sunrise_sunset()
                with self._lock:
                    self.last_updated = datetime.now(timezone.utc)
                alt_str = f"{self.altitude:.2f}" if self.altitude is not None else "N/A"
                az_str  = f"{self.azimuth:.2f}"  if self.azimuth  is not None else "N/A"
                logger.info(f"[Wolfram] alt={alt_str}°  az={az_str}°")
            except Exception as e:
                logger.warning(f"[Wolfram] query failed: {e}")
            time.sleep(self.poll_interval)

    def _update_sun_position(self):
        q   = (f"sun altitude azimuth at latitude {self.lat} longitude {self.lon} now")
        res = self._query(q)
        alt, az = None, None
        # Wolfram returns both values in the Result pod plaintext like:
        # "altitude | -39.55239°\nazimuth | 311.5383°"
        for pod in res.get("pods", []):
            if pod.get("id") == "HorizonCoordinates:StarData" or pod.get("title") == "Result":
                for sub in pod.get("subpods", []):
                    text = sub.get("plaintext", "") or ""
                    alt_match = re.search(r"altitude\s*\|\s*([-+]?\d+\.?\d*)", text)
                    az_match  = re.search(r"azimuth\s*\|\s*([-+]?\d+\.?\d*)", text)
                    if alt_match:
                        alt = float(alt_match.group(1))
                    if az_match:
                        az = float(az_match.group(1))
        with self._lock:
            if alt is not None:
                self.altitude = alt
            if az is not None:
                self.azimuth = az

    def _update_sunrise_sunset(self):
        q   = (f"sunrise sunset at latitude {self.lat} longitude {self.lon} today")
        res = self._query(q)
        for pod in res.get("pods", []):
            text = ""
            if pod.get("subpods"):
                text = pod["subpods"][0].get("plaintext", "") or ""
            if "sunrise" in pod.get("title", "").lower():
                t = self._parse_time(text)
                with self._lock:
                    if t:
                        self.sunrise = t
            elif "sunset" in pod.get("title", "").lower():
                t = self._parse_time(text)
                with self._lock:
                    if t:
                        self.sunset = t

    @staticmethod
    def _parse_time(text: str) -> datetime | None:
        match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", text, re.IGNORECASE)
        if not match:
            return None
        hour   = int(match[1])
        minute = int(match[2])
        ampm   = match[3].lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        today = date.today()
        naive = datetime(today.year, today.month, today.day, hour, minute)
        return naive.replace(tzinfo=timezone.utc)

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "altitude":     self.altitude,
                "azimuth":      self.azimuth,
                "sunrise":      self.sunrise,
                "sunset":       self.sunset,
                "last_updated": self.last_updated,
            }

    def get_target_angle(self, angle_min: float, angle_max: float) -> float:
        with self._lock:
            alt     = self.altitude
            sunrise = self.sunrise
            sunset  = self.sunset

        if alt is None:
            logger.warning("[Wolfram] No altitude data yet — parking at 0°")
            return 0.0

        if sunrise is not None and sunset is not None:
            now = datetime.now(timezone.utc)
            if not (sunrise <= now <= sunset):
                logger.info("[Night] Parking panel at 0°")
                return 0.0

        if alt <= 0:
            return 0.0

        return max(angle_min, min(angle_max, alt))

    def is_daytime(self) -> bool:
        with self._lock:
            if self.sunrise is None or self.sunset is None:
                return True
            now = datetime.now(timezone.utc)
            return self.sunrise <= now <= self.sunset


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    appid = os.getenv("WOLFRAM_APP_ID") or input("Enter your Wolfram AppID: ").strip()
    w = WolframSolar(appid, 38.033, -78.508, poll_interval=60)

    print("\nTesting sun position query...")
    try:
        res = w._query("sun altitude azimuth at latitude 38.033 longitude -78.508 now")
        w._update_sun_position()
        with w._lock:
            print(f"Sun altitude: {w.altitude}°")
            print(f"Sun azimuth:  {w.azimuth}°")
        print("Wolfram Alpha is working correctly!")
    except Exception as e:
        print(f"Failed: {e}")