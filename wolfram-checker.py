import wolframalpha
import re
import time
import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Wolfram Alpha query helpers ─────────────────────────────

class WolframSolar:
    """
    Queries Wolfram Alpha for sun position, sunrise/sunset,
    and optimal tilt angle. Runs on a background thread and
    caches results so the control loop is never blocked.
    """

    def __init__(self, app_id: str, latitude: float, longitude: float,
                 poll_interval: int = 60):
        self.client       = wolframalpha.Client(app_id)
        self.lat          = latitude
        self.lon          = longitude
        self.poll_interval = poll_interval

        # Cached results (updated by background thread)
        self.altitude      = None   # degrees
        self.azimuth       = None   # degrees
        self.optimal_tilt  = None   # degrees
        self.sunrise       = None   # datetime (UTC)
        self.sunset        = None   # datetime (UTC)
        self.last_updated  = None

        self._lock   = threading.Lock()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)

    def start(self):
        self._thread.start()
        logger.info("Wolfram Alpha background poller started.")

    # ── Background polling ──────────────────────────────────

    def _poll_loop(self):
        while True:
            try:
                self._update_sun_position()
                self._update_sunrise_sunset()
                self._update_optimal_tilt()
                with self._lock:
                    self.last_updated = datetime.now(timezone.utc)
                logger.info(f"[Wolfram] alt={self.altitude:.2f}°  "
                            f"az={self.azimuth:.2f}°  "
                            f"tilt={self.optimal_tilt:.2f}°  "
                            f"sunrise={self.sunrise}  sunset={self.sunset}")
            except Exception as e:
                logger.warning(f"[Wolfram] query failed: {e}")
            time.sleep(self.poll_interval)

    # ── Individual queries ──────────────────────────────────

    def _query(self, q: str) -> wolframalpha.Result:
        return self.client.query(q)

    def _extract_float(self, result, keyword: str) -> float | None:
        """Walk result pods and pull the first float matching keyword."""
        for pod in result.pods:
            if keyword.lower() in pod.title.lower():
                for sub in pod.subpods:
                    text = sub.plaintext or ""
                    nums = re.findall(r"[-+]?\d+\.?\d*", text)
                    if nums:
                        return float(nums[0])
        return None

    def _update_sun_position(self):
        q = (f"sun altitude azimuth at latitude {self.lat} "
             f"longitude {self.lon} now")
        res = self._query(q)
        alt = self._extract_float(res, "altitude")
        az  = self._extract_float(res, "azimuth")
        with self._lock:
            if alt is not None: self.altitude = alt
            if az  is not None: self.azimuth  = az

    def _update_sunrise_sunset(self):
        q = (f"sunrise sunset at latitude {self.lat} "
             f"longitude {self.lon} today")
        res = self._query(q)
        # Parse times from plaintext — Wolfram returns "6:42 am EDT" style
        for pod in res.pods:
            text = (pod.subpods[0].plaintext or "") if pod.subpods else ""
            if "sunrise" in pod.title.lower():
                t = self._parse_time(text)
                with self._lock:
                    if t: self.sunrise = t
            elif "sunset" in pod.title.lower():
                t = self._parse_time(text)
                with self._lock:
                    if t: self.sunset = t

    def _update_optimal_tilt(self):
        # Wolfram can compute the optimal fixed tilt for annual energy
        q = (f"optimal solar panel tilt angle latitude {self.lat}")
        res = self._query(q)
        tilt = self._extract_float(res, "tilt")
        with self._lock:
            if tilt is not None: self.optimal_tilt = tilt

    @staticmethod
    def _parse_time(text: str) -> datetime | None:
        """Parse Wolfram time strings like '6:42 am EDT' into UTC datetime."""
        import re
        from datetime import date
        import pytz

        # Strip timezone abbreviation for basic parse
        match = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)", text, re.IGNORECASE)
        if not match:
            return None
        hour, minute, ampm = int(match[1]), int(match[2]), match[3].lower()
        if ampm == "pm" and hour != 12: hour += 12
        if ampm == "am" and hour == 12: hour  = 0

        today = date.today()
        # Assume local time from Wolfram, convert to UTC naively
        naive = datetime(today.year, today.month, today.day, hour, minute)
        return naive.replace(tzinfo=timezone.utc)  # approximate

    # ── Thread-safe getters ─────────────────────────────────

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "altitude":     self.altitude,
                "azimuth":      self.azimuth,
                "optimal_tilt": self.optimal_tilt,
                "sunrise":      self.sunrise,
                "sunset":       self.sunset,
                "last_updated": self.last_updated,
            }

    def is_daytime(self) -> bool:
        with self._lock:
            if self.sunrise is None or self.sunset is None:
                return True   # default to active if unknown
            now = datetime.now(timezone.utc)
            return self.sunrise <= now <= self.sunset