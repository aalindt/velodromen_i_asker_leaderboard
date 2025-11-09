import math
import random
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests

from config_loader import load_config

# ======================================================
# 🌍 KONFIG FRA YAML/TOML VIA config_loader
# ======================================================

_cfg = load_config()

LOCATION_ID: int = _cfg["location_id"]
BASE_ACTIVITIES_URL: str = _cfg["urls"]["activities"]          # Ferdig formatert med location_id
BASE_SESSIONS_URL: str = _cfg["urls"]["sessions"]              # Skal inneholde {activity_id}
USER_AGENTS: List[str] = _cfg["http"]["user_agents"]
REQUEST_TIMEOUT: int = _cfg["http"].get("timeout", 10)
MAX_RETRIES: int = _cfg["http"].get("max_retries", 3)


# ======================================================
# 🔧 FELLES HJELPEFUNKSJONER
# ======================================================

def _get_headers() -> Dict[str, str]:
    """Generer standard headers med random User-Agent."""
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://sporthive.com/",
        "Origin": "https://sporthive.com",
    }


def _to_float(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _floor2(x: float) -> float:
    return math.floor(x * 100) / 100


# ======================================================
# 📦 1) Hent alle økter inneværende måned
# ======================================================

def get_current_month_activities(page_size: int = 100) -> List[Dict[str, Any]]:
    """
    Henter alle aktiviteter (økter) for inneværende måned fra Sporthive API.

    Returnerer liste av:
        {
            "activity_id": int,
            "chipLabel": str | None,
            "chipCode": str | None,
            "startTime": datetime
        }
    """
    if not isinstance(LOCATION_ID, int):
        raise ValueError("LOCATION_ID må være et heltall")

    today = datetime.today()
    target_year, target_month = today.year, today.month

    offset = 0
    activities_out: List[Dict[str, Any]] = []

    print(f"Henter økter for {target_year}-{target_month:02d} fra LOCATION_ID={LOCATION_ID}...")

    while True:
        params = {"count": page_size, "offset": offset}

        try:
            resp = requests.get(
                BASE_ACTIVITIES_URL,
                headers=_get_headers(),
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            print(f"[Feil] Request-feil ved offset {offset}: {e}")
            break

        activities = data.get("activities", [])
        if not activities:
            break

        stop = False
        for act in activities:
            start_time = act.get("startTime")
            if not start_time:
                continue

            try:
                dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except Exception:
                continue

            # Inneværende måned
            if dt.year == target_year and dt.month == target_month:
                activities_out.append(
                    {
                        "activity_id": act.get("id"),
                        "chipLabel": act.get("chipLabel"),
                        "chipCode": act.get("chipCode"),
                        "startTime": dt,
                    }
                )
            # Når vi treffer eldre måneder, kan vi avslutte tidlig
            elif (dt.year < target_year) or (
                dt.year == target_year and dt.month < target_month
            ):
                stop = True
                break

        if stop:
            break

        offset += page_size
        total = data.get("activityCount")
        if total is not None and offset >= total:
            break

    print(f"✅ Fant {len(activities_out)} økter i inneværende måned.")
    return activities_out


# ======================================================
# 🏁 2) Hent bestlap-info for én activity
# ======================================================

def get_bestlap_info_for_activity(
    activity_id: int,
    retries: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Henter bestlap-informasjon for én activity.

    Returnerer:
      {
        "activity_id": int,
        "bestLapTime_s": float,
        "lapSpeed_kph": float,
        "first100_time_s": float | None,
        "first100_speed_kph": float | None,
        "last100_time_s": float | None,
        "last100_speed_kph": float | None,
      }
      eller None hvis noe mangler/feiler.
    """
    if retries is None:
        retries = MAX_RETRIES

    url = BASE_SESSIONS_URL.format(activity_id=activity_id)

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(
                url,
                headers=_get_headers(),
                timeout=REQUEST_TIMEOUT,
            )

            # Midlertidige feil / rate limits
            if resp.status_code in (403, 429, 500, 502, 503, 504):
                wait = random.uniform(1.5, 3.5)
                print(
                    f"[Advarsel] Status {resp.status_code} for activity {activity_id} – "
                    f"prøver igjen om {wait:.1f}s..."
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            break

        except (requests.RequestException, ValueError) as e:
            if attempt < retries:
                wait = random.uniform(1.0, 3.0)
                print(
                    f"[Forsøk {attempt}/{retries}] Feil for activity {activity_id}: {e}. "
                    f"Prøver igjen om {wait:.1f}s..."
                )
                time.sleep(wait)
            else:
                print(f"[Feil] Ga opp etter {retries} forsøk for activity {activity_id}")
                return None

    best = data.get("bestLap") or {}
    sessions = data.get("sessions") or []

    session_id = best.get("sessionId")
    lap_nr = best.get("lapNr")
    best_time_s = _to_float(best.get("duration"))
    lap_speed_kph = _floor2((best.get("speed") or {}).get("kph") or 0.0)

    if not session_id or not lap_nr or best_time_s is None:
        return None

    session = next((s for s in sessions if s.get("id") == session_id), None)
    if not session:
        return None

    laps = session.get("laps") or []
    lap = next((l for l in laps if l.get("nr") == lap_nr), None)
    if not lap:
        return None

    sections = lap.get("sections") or []
    sec_by_name = {sec.get("name"): sec for sec in sections}

    def sec_vals(sec):
        if not sec:
            return None, None
        dur = _to_float(sec.get("duration"))
        spd = (sec.get("speed") or {}).get("kph")
        return dur, _floor2(spd) if spd is not None else None

    first100_time, first100_speed = sec_vals(sec_by_name.get("Finish to 100m"))
    last100_time, last100_speed = sec_vals(sec_by_name.get("100m to Finish"))

    return {
        "activity_id": activity_id,
        "bestLapTime_s": best_time_s,
        "lapSpeed_kph": lap_speed_kph,
        "first100_time_s": first100_time,
        "first100_speed_kph": first100_speed,
        "last100_time_s": last100_time,
        "last100_speed_kph": last100_speed,
    }
