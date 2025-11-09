"""
Main Streamlit application for displaying Velodromen leaderboard
"""

import os
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.utils.config import load_config
from src.scraper import get_current_month_activities, get_bestlap_info_for_activity


# ============================================================
# Konfig
# ============================================================

_cfg = load_config()
REFRESH_INTERVAL_MINUTES = _cfg["app"]["refresh_minutes"]
REFRESH_INTERVAL = timedelta(minutes=REFRESH_INTERVAL_MINUTES)

PAGE_TITLE = _cfg["app"].get("page_title", "Velodromen i Asker – Leaderboard")
PAGE_ICON = _cfg["app"].get("page_icon", "🚴")

CACHE_PATH = Path(".cache") / "bestlaps.parquet"
CACHE_TTL = REFRESH_INTERVAL


# ============================================================
# Hjelpefunksjoner
# ============================================================

def fetch_data(
    existing_ids: set | None = None,
    progress=None,
    label_placeholder=None,
) -> pd.DataFrame:
    """
    Henter bestlap-data for inneværende måned.

    - Hvis existing_ids er satt:
        henter KUN nye activity_id's som ikke finnes der.
    - Hvis progress/label_placeholder er satt:
        viser fremdrift (brukes ved eksplisitt/førstegangs last).
    """
    activities = get_current_month_activities()
    existing_ids = existing_ids or set()

    new_acts = []
    for act in activities:
        act_id = act.get("activity_id") or act.get("id")
        if not act_id or act_id in existing_ids:
            continue
        new_acts.append(act)

    total = len(new_acts)

    if progress is not None:
        if total == 0:
            progress.progress(1.0)
            if label_placeholder:
                label_placeholder.text("Ingen nye økter å hente.")
            return pd.DataFrame()
        progress.progress(0.0)
        if label_placeholder:
            label_placeholder.text(f"Henter data for {total} nye økter...")

    rows = []
    for i, act in enumerate(new_acts, start=1):
        act_id = act.get("activity_id") or act.get("id")
        chip = act.get("chipLabel") or act.get("chipCode") or "Ukjent"
        dt = act.get("startTime")
        dato = dt.date() if isinstance(dt, datetime) else None

        info = get_bestlap_info_for_activity(act_id)
        if info:
            rows.append(
                {
                    "activity_id": act_id,
                    "Navn": chip,
                    "Dato": dato,
                    "Rundetid": info["bestLapTime_s"],
                    "Hastighet": info["lapSpeed_kph"],
                    "Tid første 100": info["first100_time_s"],
                    "Fart første 100": info["first100_speed_kph"],
                    "Tid siste 100": info["last100_time_s"],
                    "Fart siste 100": info["last100_speed_kph"],
                }
            )

        if progress is not None and total > 0:
            progress.progress(i / total)
            if label_placeholder:
                label_placeholder.text(
                    f"Henter data for {total} nye økter... ({i}/{total})"
                )

    if progress is not None:
        progress.progress(1.0)
        if label_placeholder:
            label_placeholder.text("")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def clean_bestlaps(df: pd.DataFrame) -> pd.DataFrame:
    """Rens bort feilaktige eller ufullstendige rader."""
    if df.empty:
        return df

    df = df.copy()

    for col in ["Rundetid", "Tid første 100", "Tid siste 100"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Rundetid", "Tid første 100", "Tid siste 100"])
    if df.empty:
        return df

    df = df[df["Rundetid"] >= 9.0]
    if df.empty:
        return df

    tol = 0.05
    diff = (df["Tid første 100"] + df["Tid siste 100"] - df["Rundetid"]).abs()
    df = df[diff <= tol]

    return df.reset_index(drop=True)


def compute_views(df: pd.DataFrame):
    """Returnerer toppvisninger uten interne felter."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), None

    # Topp 10 for måneden (beste per navn)
    df_month_top10 = (
        df.sort_values("Rundetid")
        .groupby("Navn", as_index=False)
        .first()
        .sort_values("Rundetid")
        .head(10)
        .drop(columns=["Dato", "activity_id"], errors="ignore")
        .reset_index(drop=True)
    )

    # Topp 10 i dag
    today = datetime.today().date()
    df_today_top10 = (
        df[df["Dato"] == today]
        .sort_values("Rundetid")
        .head(10)
        .drop(columns=["Dato", "activity_id"], errors="ignore")
        .reset_index(drop=True)
    )

    return df_month_top10, df_today_top10, today


# ============================================================
# Server-side cache + Parquet
# ============================================================

@st.cache_data(ttl=int(REFRESH_INTERVAL.total_seconds()))
def load_bestlaps_cached() -> pd.DataFrame:
    """
    Henter og renser bestlap-data for inneværende måned.

    - Leser fra lokal Parquet-cache hvis mulig.
    - Hvis cache er stale:
        - returnerer stale data umiddelbart,
        - refresher inkrementelt i bakgrunnen (kun nye activity_id).
    """

    def mark_generated(df: pd.DataFrame, ts: datetime) -> pd.DataFrame:
        df = df.copy()
        # attrs lagres ikke i parquet, så vi bruker filens mtime ved reload.
        df.attrs["generated_at"] = ts.isoformat()
        return df

    def write_cache(df: pd.DataFrame):
        try:
            if df.empty:
                return
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=str(CACHE_PATH.parent))
            os.close(fd)
            try:
                df.to_parquet(tmp_path)
                os.replace(tmp_path, CACHE_PATH)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        except Exception:
            # Diskfeil skal ikke krasje appen
            pass

    def background_refresh(existing_df: pd.DataFrame):
        try:
            if "activity_id" in existing_df.columns:
                existing_ids = set(existing_df["activity_id"].unique())
            else:
                existing_ids = set()

            new_raw = fetch_data(existing_ids=existing_ids)
            if new_raw.empty:
                updated = mark_generated(existing_df, datetime.now())
                write_cache(updated)
                try:
                    load_bestlaps_cached.clear()
                except Exception:
                    pass
                return

            combined = pd.concat([existing_df, new_raw], ignore_index=True)
            combined = clean_bestlaps(combined)
            if not combined.empty and "activity_id" in combined.columns:
                combined = combined.drop_duplicates(subset=["activity_id"], keep="last")

            combined = mark_generated(combined, datetime.now())
            write_cache(combined)

            try:
                load_bestlaps_cached.clear()
            except Exception:
                pass

        except Exception:
            # Feil i bakgrunnsrefresh skal ikke påvirke visning
            return

    # 1) Forsøk å lese eksisterende Parquet-cache
    if CACHE_PATH.exists():
        try:
            mtime = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
            age = datetime.now() - mtime

            try:
                df_cached = pd.read_parquet(CACHE_PATH)
            except Exception:
                df_cached = None

            if df_cached is not None and not df_cached.empty:
                # Bruk mtime som generated_at ved reload
                if "generated_at" not in df_cached.attrs:
                    df_cached.attrs["generated_at"] = mtime.isoformat()

                # Fresh cache → bruk direkte
                if age <= CACHE_TTL:
                    return df_cached

                # Stale cache → bruk nå, oppdater i bakgrunnen
                t = threading.Thread(
                    target=background_refresh,
                    args=(df_cached.copy(),),
                    daemon=True,
                )
                t.start()
                return df_cached

        except Exception:
            # Fall back til full scraping
            pass

    # 2) Ingen gyldig cache → full blocking scrape
    raw_df = fetch_data(existing_ids=None)
    clean_df = clean_bestlaps(raw_df)

    if not clean_df.empty and "activity_id" in clean_df.columns:
        clean_df = clean_df.drop_duplicates(subset=["activity_id"], keep="last")

    ts = datetime.now()
    clean_df = mark_generated(clean_df, ts)
    write_cache(clean_df)

    return clean_df


# ============================================================
# Session bootstrap
# ============================================================

def ensure_data_loaded(status_ph=None):
    """
    Per-session bootstrap.
    """
    st.session_state.setdefault("initialized", False)
    st.session_state.setdefault("df", pd.DataFrame())
    st.session_state.setdefault("last_updated", None)

    if not st.session_state.initialized:
        if status_ph is None:
            status_ph = st.empty()
        status_ph.info("Laster leaderboard-data...")
        df = load_bestlaps_cached()
        status_ph.empty()

        gen_ts = df.attrs.get("generated_at")
        if gen_ts:
            try:
                last_updated = datetime.fromisoformat(gen_ts)
            except ValueError:
                last_updated = datetime.now()
        else:
            last_updated = datetime.now()

        st.session_state.df = df
        st.session_state.last_updated = last_updated
        st.session_state.initialized = True
    else:
        df = load_bestlaps_cached()
        gen_ts = df.attrs.get("generated_at")
        if gen_ts:
            try:
                last_updated = datetime.fromisoformat(gen_ts)
            except ValueError:
                last_updated = datetime.now()
        else:
            last_updated = datetime.now()

        st.session_state.df = df
        st.session_state.last_updated = last_updated


# ============================================================
# Streamlit UI
# ============================================================

def main():
    st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="centered")

    st.title(PAGE_TITLE)
    st.caption(
        f"Data hentes fra Sporthive og oppdateres automatisk hver {REFRESH_INTERVAL_MINUTES} minutt(er)."
    )

    status_ph = st.empty()
    ensure_data_loaded(status_ph)

    df = st.session_state.df
    if df.empty:
        st.error("Ingen gyldige bestlap-data tilgjengelig.")
        return

    df_month_top10, df_today_top10, today = compute_views(df)

    ts_str = st.session_state.last_updated.strftime("%Y-%m-%d %H:%M:%S")

    st_autorefresh(
        interval=int(REFRESH_INTERVAL.total_seconds() * 1000),
        key="silent_auto_refresh",
        limit=None,
    )

    with st.container():
        col1, col2 = st.columns([3, 1], gap="small")

        with col1:
            st.caption(f"Sist oppdatert (data): {ts_str}")

        with col2:
            if st.button("🔄 Oppdater nå", key="manual_refresh"):
                try:
                    load_bestlaps_cached.clear()
                except Exception:
                    pass
                df = load_bestlaps_cached()

                gen_ts = df.attrs.get("generated_at")
                if gen_ts:
                    try:
                        st.session_state.last_updated = datetime.fromisoformat(gen_ts)
                    except ValueError:
                        st.session_state.last_updated = datetime.now()
                else:
                    st.session_state.last_updated = datetime.now()

                st.session_state.df = df
                st.experimental_rerun()

    st.subheader("🏆 Topp 10 i måneden (raskeste per chip)")
    st.dataframe(df_month_top10, hide_index=True)

    st.subheader(f"🏁 Topp 10 i dag ({today})")
    st.dataframe(df_today_top10, hide_index=True)

    st.markdown("---")
    st.caption("🚴‍♂️ Denne siden er utviklet av Aasmund Lindtveit (Plogen fra Solemskogen).")


if __name__ == "__main__":
    main()
