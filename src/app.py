"""
Main Streamlit application for displaying leaderboards
"""

import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from src.utils.config import load_config
from src.scraper import get_current_month_activities, get_bestlap_info_for_activity


# ============================================================
# 🌍 KONFIG
# ============================================================

_cfg = load_config()

REFRESH_INTERVAL_MINUTES = _cfg["app"]["refresh_minutes"]
REFRESH_INTERVAL = timedelta(minutes=REFRESH_INTERVAL_MINUTES)

PAGE_TITLE = _cfg["app"].get("page_title", "Velodromen i Asker – Leaderboard")
PAGE_ICON = _cfg["app"].get("page_icon", "🚴")


# ============================================================
# 📦 HJELPEFUNKSJONER
# ============================================================

def fetch_data(
    existing_ids: set | None = None,
    progress=None,
    label_placeholder=None,
) -> pd.DataFrame:
    """Henter bestlap-data for inneværende måned."""
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
        if progress is not None:
            progress.progress(i / total)
            if label_placeholder:
                label_placeholder.text(f"Henter data for {total} nye økter... ({i}/{total})")

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
    df = df[df["Rundetid"] >= 9.0]
    tol = 0.05
    diff = (df["Tid første 100"] + df["Tid siste 100"] - df["Rundetid"]).abs()
    return df[diff <= tol].reset_index(drop=True)


def compute_views(df: pd.DataFrame):
    """Returnerer toppvisninger uten interne felter."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), None
    df_month_top10 = (
        df.sort_values("Rundetid")
        .groupby("Navn", as_index=False)
        .first()
        .sort_values("Rundetid")
        .head(10)
        .drop(columns=["Dato", "activity_id"], errors="ignore")
        .reset_index(drop=True)
    )
    today = datetime.today().date()
    df_today_top10 = (
        df[df["Dato"] == today]
        .sort_values("Rundetid")
        .head(10)
        .drop(columns=["Dato", "activity_id"], errors="ignore")
        .reset_index(drop=True)
    )
    return df_month_top10, df_today_top10, today


def ensure_data_loaded(status_ph=None, progress_ph=None, label_ph=None):
    """Håndterer første last (med fremdrift) og stille auto-oppdatering."""
    now = datetime.now()

    # Init
    st.session_state.setdefault("initialized", False)
    st.session_state.setdefault("loading", False)
    st.session_state.setdefault("auto_refresh_enabled", False)
    st.session_state.setdefault("df", pd.DataFrame())
    st.session_state.setdefault("last_updated", now)
    st.session_state.setdefault("next_refresh", now + REFRESH_INTERVAL)

    # Førstegangslast (vises)
    if not st.session_state.initialized:
        st.session_state.loading = True
        status_ph = status_ph or st.empty()
        progress_ph = progress_ph or st.empty()
        label_ph = label_ph or st.empty()

        status_ph.info("Initialiserer leaderboard-data...")
        progress = progress_ph.progress(0.0)

        new_df = fetch_data(None, progress, label_ph)
        clean_df = clean_bestlaps(new_df)

        progress_ph.empty()
        status_ph.empty()
        label_ph.empty()

        st.session_state.df = clean_df
        st.session_state.last_updated = now
        st.session_state.next_refresh = now + REFRESH_INTERVAL
        st.session_state.initialized = True
        st.session_state.loading = False
        st.session_state.auto_refresh_enabled = True
        return

    # Auto-refresh (helt stille)
    if st.session_state.auto_refresh_enabled and datetime.now() >= st.session_state.next_refresh:
        existing_ids = (
            set(st.session_state.df["activity_id"].unique())
            if "activity_id" in st.session_state.df.columns
            else set()
        )
        new_df = fetch_data(existing_ids=existing_ids)
        if not new_df.empty:
            new_df = clean_bestlaps(new_df)
            if not new_df.empty:
                combined = pd.concat([st.session_state.df, new_df], ignore_index=True)
                combined = combined.drop_duplicates(subset=["activity_id"], keep="last")
                st.session_state.df = combined
        st.session_state.last_updated = datetime.now()
        st.session_state.next_refresh = st.session_state.last_updated + REFRESH_INTERVAL


# ============================================================
# 🖥️ STREAMLIT APP
# ============================================================

def main():
    st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="centered")

    st.title(PAGE_TITLE)
    st.caption(
        f"""Data hentes fra Sporthive og oppdateres automatisk hver {REFRESH_INTERVAL_MINUTES} minutt(er)"""
    )

    status_ph, progress_ph, label_ph = st.empty(), st.empty(), st.empty()
    ensure_data_loaded(status_ph, progress_ph, label_ph)
    df = st.session_state.df
    if df.empty:
        st.error("Ingen gyldige bestlap-data tilgjengelig.")
        return

    df_month_top10, df_today_top10, today = compute_views(df)
    ts = st.session_state.last_updated.strftime("%Y-%m-%d %H:%M:%S")

    # Auto-refresh i bakgrunnen (ingen UI-effekt)
    if st.session_state.get("initialized") and st.session_state.get("auto_refresh_enabled"):
        st_autorefresh(
            interval=int(REFRESH_INTERVAL.total_seconds() * 1000),
            key="silent_auto_refresh",
            limit=None,
        )

    # Header med status + manuell refresh
    with st.container():
        col1, col2 = st.columns([3, 1], gap="small")
        with col1:
            st.caption(f"Sist oppdatert: {ts}")
        with col2:
            if st.button("🔄 Oppdater nå", key="manual_refresh", width="stretch"):
                st.session_state.loading = True
                existing_ids = (
                    set(df["activity_id"].unique())
                    if "activity_id" in df.columns
                    else set()
                )
                progress = st.progress(0.0)
                new_df = fetch_data(existing_ids=existing_ids, progress=progress)
                progress.empty()
                if not new_df.empty:
                    new_df = clean_bestlaps(new_df)
                    if not new_df.empty:
                        combined = pd.concat([st.session_state.df, new_df], ignore_index=True)
                        combined = combined.drop_duplicates(subset=["activity_id"], keep="last")
                        st.session_state.df = combined
                        st.session_state.last_updated = datetime.now()
                        st.session_state.next_refresh = st.session_state.last_updated + REFRESH_INTERVAL
                st.session_state.loading = False
                st.rerun()

    # ----- VIS TABELLER -----
    st.subheader("🏆 Topp 10 i måneden (raskeste per chip)")
    st.dataframe(df_month_top10, width="stretch", hide_index=True)

    st.subheader(f"🏁 Topp 10 i dag ({today})")
    st.dataframe(df_today_top10, width="stretch", hide_index=True)

    st.markdown("---")
    st.caption("🚴‍♂️ Denne siden er utviklet av Aasmund Lindtveit (Plogen fra Solemskogen).")


if __name__ == "__main__":
    main()
