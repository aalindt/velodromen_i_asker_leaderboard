import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from config_loader import load_config
from scraper import get_current_month_activities, get_bestlap_info_for_activity


# ============================================================
# 🌍 LAST KONFIG
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
    timer_start: datetime | None = None,
) -> pd.DataFrame:
    """
    Henter bestlap-data for inneværende måned.

    - Hvis existing_ids er satt:
        henter KUN nye activity_id's.
    - Hvis progress + label_placeholder er satt:
        viser ekte fremdrift basert på antall nye aktiviteter + tidtaker.
    """
    activities = get_current_month_activities()
    existing_ids = existing_ids or set()

    # Filtrer først til bare nye aktiviteter (for ekte progress)
    new_acts = []
    for act in activities:
        act_id = act.get("activity_id") or act.get("id")
        if not act_id:
            continue
        if act_id in existing_ids:
            continue
        new_acts.append(act)

    total = len(new_acts)

    if progress is not None:
        if total == 0:
            progress.progress(1.0)
            if label_placeholder is not None:
                label_placeholder.text("Ingen nye økter å hente. ⏱ 0.0s")
            return pd.DataFrame()
        progress.progress(0.0)
        if label_placeholder is not None:
            label_placeholder.text(f"Laster data... (0/{total}) ⏱ 0.0s")

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
                    "activity_id": act_id,  # kun internt
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
            frac = i / total
            progress.progress(frac)

            if label_placeholder is not None:
                if timer_start is not None:
                    elapsed = (datetime.now() - timer_start).total_seconds()
                else:
                    elapsed = 0.0
                label_placeholder.text(
                    f"Laster data... ({i}/{total}) ⏱ {elapsed:.1f}s"
                )

    if progress is not None and total > 0:
        progress.progress(1.0)
        if label_placeholder is not None:
            if timer_start is not None:
                elapsed = (datetime.now() - timer_start).total_seconds()
            else:
                elapsed = 0.0
            label_placeholder.text(f"Ferdig. ({total}/{total}) ⏱ {elapsed:.1f}s")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def clean_bestlaps(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rens bort feilaktige eller ufullstendige rader før videre analyse.

    Regler:
    - Fjern rader som har noen NaN-verdier i det hele tatt.
    - Fjern rader med Rundetid < 9.0 s.
    - Behold kun rader der (Tid første 100 + Tid siste 100) ≈ Rundetid (±0.05 s).
    """
    if df.empty:
        return df

    df = df.copy()

    for col in ["Rundetid", "Tid første 100", "Tid siste 100"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna()
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


def ensure_data_loaded():
    """
    - Første gangs innlasting:
        progress-bar + enkel timer, blokkerende.
    - Etterpå:
        inkrementell oppdatering basert på REFRESH_INTERVAL.
    """
    now = datetime.now()

    # Init states
    if "data_loaded" not in st.session_state:
        st.session_state.data_loaded = False
    if "df" not in st.session_state:
        st.session_state.df = pd.DataFrame()
    if "last_updated" not in st.session_state:
        st.session_state.last_updated = now

    # Førstegangslast
    if not st.session_state.data_loaded:
        info = st.empty()
        info.info("Initialiserer leaderboard-data...")

        progress = st.progress(0.0)
        label = st.empty()
        timer_start = datetime.now()

        new_df = fetch_data(
            existing_ids=None,
            progress=progress,
            label_placeholder=label,
            timer_start=timer_start,
        )
        clean_df = clean_bestlaps(new_df)

        progress.empty()
        label.empty()
        info.empty()

        st.session_state.df = clean_df
        st.session_state.last_updated = datetime.now()
        st.session_state.data_loaded = True
        return

    # Inkrementell refresh etter første last
    age = now - st.session_state.last_updated
    if age > REFRESH_INTERVAL:
        existing_ids = (
            set(st.session_state.df["activity_id"].unique())
            if "activity_id" in st.session_state.df.columns
            else set()
        )

        # Auto-refresh i bakgrunnen: ingen progress/timer
        new_df = fetch_data(
            existing_ids=existing_ids,
            progress=None,
            label_placeholder=None,
            timer_start=None,
        )

        if not new_df.empty:
            new_df = clean_bestlaps(new_df)
            if not new_df.empty:
                combined = pd.concat(
                    [st.session_state.df, new_df], ignore_index=True
                )
                combined = combined.drop_duplicates(
                    subset=["activity_id"], keep="last"
                )
                st.session_state.df = combined

        st.session_state.last_updated = datetime.now()


# ============================================================
# 🖥️ STREAMLIT APP
# ============================================================

def main():
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="centered",
    )

    # Først: sørg for at data er lastet (blokkerer ved første kall)
    ensure_data_loaded()

    # Auto-refresh kun når første last er ferdig
    if st.session_state.get("data_loaded", False):
        st_autorefresh(
            interval=REFRESH_INTERVAL_MINUTES * 60 * 1000,
            key="auto_refresh",
            limit=None,
        )

    st.title(PAGE_TITLE)
    st.caption(
        f"Data hentes fra Sporthive og oppdateres automatisk hver {REFRESH_INTERVAL_MINUTES} minutt(er)."
    )

    df = st.session_state.df
    if df.empty:
        st.error("Ingen gyldige bestlap-data tilgjengelig.")
        return

    df_month_top10, df_today_top10, today = compute_views(df)
    ts = st.session_state.last_updated.strftime("%Y-%m-%d %H:%M:%S")

    # Header: sist oppdatert + manuell refresh med progress + timer
    col_info, col_btn = st.columns([3, 1])
    with col_info:
        st.caption(f"Sist oppdatert: {ts}")
    with col_btn:
        if st.button("🔄 Oppdater nå", key="manual_refresh"):
            existing_ids = (
                set(df["activity_id"].unique())
                if "activity_id" in df.columns
                else set()
            )

            label = st.empty()
            progress = st.progress(0.0)
            timer_start = datetime.now()

            new_df = fetch_data(
                existing_ids=existing_ids,
                progress=progress,
                label_placeholder=label,
                timer_start=timer_start,
            )

            progress.empty()
            label.empty()

            if not new_df.empty:
                new_df = clean_bestlaps(new_df)
                if not new_df.empty:
                    combined = pd.concat(
                        [st.session_state.df, new_df],
                        ignore_index=True,
                    )
                    combined = combined.drop_duplicates(
                        subset=["activity_id"], keep="last",
                    )
                    st.session_state.df = combined
                    st.session_state.last_updated = datetime.now()

            st.rerun()

    # ----- VIS TABELLER -----
    st.subheader("🏆 Topp 10 i måneden (raskeste per chip)")
    st.dataframe(df_month_top10, width="stretch", hide_index=True)

    st.subheader(f"🏁 Topp 10 i dag ({today})")
    st.dataframe(df_today_top10, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
