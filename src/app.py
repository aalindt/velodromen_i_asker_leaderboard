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
# Versjons- og runtime-kompatibilitet
# ============================================================

# Sørg for at vi har st.rerun tilgjengelig
if not hasattr(st, "rerun") and hasattr(st, "experimental_rerun"):
    st.rerun = st.experimental_rerun


# ============================================================
# Konfig
# ============================================================

_cfg = load_config()

REFRESH_INTERVAL_MINUTES = _cfg["app"]["refresh_minutes"]
REFRESH_INTERVAL = timedelta(minutes=REFRESH_INTERVAL_MINUTES)

PAGE_TITLE = _cfg["app"].get("page_title", "Velodromen i Asker – Leaderboard")
PAGE_ICON = _cfg["app"].get("page_icon", "🚴")

# Hardkodet passord for manuell "Oppdater nå"
REFRESH_PASSWORD = "oppdater123"

# Parquet-cache på serverside (per instans)
CACHE_PATH = Path(".cache") / "bestlaps.parquet"
CACHE_TTL = REFRESH_INTERVAL


# ============================================================
# Hjelpefunksjoner: scraping og transformasjon
# ============================================================

def fetch_data(
    existing_ids: set | None = None,
    force_refresh_ids: set | None = None,
    progress=None,
    label_placeholder=None,
) -> pd.DataFrame:
    """
    Henter bestlap-data for inneværende måned.

    - Hvis existing_ids er satt:
        henter KUN nye activity_id's som ikke finnes der.
    - Hvis force_refresh_ids er satt:
        henter/oppdaterer ALL bestlaps for disse activity_id's (inkludert ongoing).
    - Hvis progress/label_placeholder er satt:
        brukes til UI-feedback ved eksplisitt/førstegangs last.
    """
    activities = get_current_month_activities()
    existing_ids = existing_ids or set()
    force_refresh_ids = force_refresh_ids or set()

    new_acts = []
    for act in activities:
        act_id = act.get("activity_id") or act.get("id")
        if not act_id:
            continue
        # Include activity if: (1) it's new, OR (2) it's marked for forced refresh
        if act_id not in existing_ids or act_id in force_refresh_ids:
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
    """Rens bort åpenbart feilaktige eller ufullstendige rader."""
    if df.empty:
        return df

    df = df.copy()

    for col in ["Rundetid", "Tid første 100", "Tid siste 100"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Rundetid", "Tid første 100", "Tid siste 100"])
    if df.empty:
        return df

    # Fjern urimelig raske tider
    df = df[df["Rundetid"] >= 9.0]
    if df.empty:
        return df

    # Konsistenssjekk: første 100 + siste 100 ≈ rundetid
    tol = 0.05
    diff = (df["Tid første 100"] + df["Tid siste 100"] - df["Rundetid"]).abs()
    df = df[diff <= tol]

    return df.reset_index(drop=True)


def compute_views(df: pd.DataFrame):
    """Returnerer topp-10 for måned og dag, uten interne felt."""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), None

    # Beste per navn for måneden
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
# Hjelpefunksjoner: cache + parquet
# ============================================================

def mark_generated(df: pd.DataFrame, ts: datetime) -> pd.DataFrame:
    df = df.copy()
    df.attrs["generated_at"] = ts.isoformat()
    return df


def write_cache(df: pd.DataFrame):
    """Skriv DataFrame til parquet (best effort, atomisk)."""
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
        # Disk-feil skal ikke krasje appen
        pass


# ============================================================
# Server-side cache med inkrementell oppdatering
# ============================================================

@st.cache_data(ttl=int(REFRESH_INTERVAL.total_seconds()))
def load_bestlaps_cached() -> pd.DataFrame:
    """
    Leser (og ved behov oppdaterer) bestlap-data for inneværende måned.

    - Hvis parquet-cache finnes og er fresh: returneres direkte.
    - Hvis parquet-cache finnes men er stale:
        - stale data returneres umiddelbart,
        - bakgrunnstråd henter kun nye activity_id's og oppdaterer filen.
    - Hvis ingen cache: full fetch + skriv fil (fallback, normalt håndteres i ensure_data_loaded).
    """

    def background_refresh(existing_df: pd.DataFrame):
        """
        Smart auto-refresh: 
        - Fetch new activities (never seen before).
        - Re-fetch ongoing activities (< 6 hours old) to catch updated times.
        - Skip old activities (already finalized).
        """
        try:
            if "activity_id" in existing_df.columns:
                existing_ids = set(existing_df["activity_id"].unique())
            else:
                existing_ids = set()

            # Identifiser pågående aktiviteter (< 6 timer gamle) for re-fetch
            ongoing_activity_ids = set()
            if "Dato" in existing_df.columns:
                cutoff = datetime.now() - timedelta(hours=6)
                try:
                    # Konverter Dato til datetime for sammenligning
                    date_col = existing_df["Dato"]
                    mask = date_col.apply(
                        lambda d: datetime.combine(d, datetime.min.time()) > cutoff
                        if isinstance(d, pd.Timestamp) or hasattr(d, "date")
                        else False
                    )
                    ongoing_activity_ids = set(existing_df.loc[mask, "activity_id"].unique())
                except Exception:
                    pass

            # Hent: nye activities + oppdater pågående
            new_raw = fetch_data(
                existing_ids=existing_ids,
                force_refresh_ids=ongoing_activity_ids
            )
            if new_raw.empty:
                updated = mark_generated(existing_df, datetime.now())
                write_cache(updated)
                try:
                    load_bestlaps_cached.clear()
                except Exception:
                    pass
                return

            # Unngå FutureWarning ved tomme eller all-NA DataFrames
            frames = []
            for df in [existing_df, new_raw]:
                if df is not None and not df.empty:
                    # Fjern helt tomme/all-NA kolonner
                    df = df.dropna(axis=1, how="all")
                    frames.append(df)

            if frames:
                combined = pd.concat(frames, ignore_index=True)
            else:
                combined = pd.DataFrame()


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
            # Feil i bakgrunnsrefresh skal ikke påvirke eksisterende visning
            return

    # Forsøk å bruke eksisterende parquet-cache
    if CACHE_PATH.exists():
        try:
            mtime = datetime.fromtimestamp(CACHE_PATH.stat().st_mtime)
            age = datetime.now() - mtime

            try:
                df_cached = pd.read_parquet(CACHE_PATH)
            except Exception:
                df_cached = None

            if df_cached is not None and not df_cached.empty:
                # Bruk filens mtime som generated_at hvis attrs mangler
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
            # Ved feil: fall-through til full fetch
            pass

    # Ingen gyldig cache → blocking fetch (fallback)
    raw_df = fetch_data(existing_ids=None)
    clean_df = clean_bestlaps(raw_df)
    if not clean_df.empty and "activity_id" in clean_df.columns:
        clean_df = clean_df.drop_duplicates(subset=["activity_id"], keep="last")

    ts = datetime.now()
    clean_df = mark_generated(clean_df, ts)
    write_cache(clean_df)
    return clean_df


# ============================================================
# Per-session bootstrap
# ============================================================

def ensure_data_loaded(status_ph=None):
    """
    Per-session bootstrap:

    - Første gang i denne sessionen:
        - Hvis ingen parquet-cache finnes:
            vis progress-bar og hent alt.
        - Hvis parquet-cache finnes:
            bruk load_bestlaps_cached() (rask, delt cache).
    - Senere i samme session:
        - bruk load_bestlaps_cached() og oppdater last_updated fra generated_at.
    """
    st.session_state.setdefault("initialized", False)
    st.session_state.setdefault("df", pd.DataFrame())
    st.session_state.setdefault("last_updated", None)

    # Første gang i denne session
    if not st.session_state.initialized:
        if status_ph is None:
            status_ph = st.empty()

        # Førstegangs lasting på instans uten cache-fil → vis progress bar
        if not CACHE_PATH.exists():
            status_ph.info("Førstegangs lasting av leaderboard-data...")
            progress = st.progress(0.0)
            label = st.empty()

            raw_df = fetch_data(existing_ids=None, progress=progress, label_placeholder=label)
            clean_df = clean_bestlaps(raw_df)
            if not clean_df.empty and "activity_id" in clean_df.columns:
                clean_df = clean_df.drop_duplicates(subset=["activity_id"], keep="last")

            ts = datetime.now()
            clean_df = mark_generated(clean_df, ts)
            write_cache(clean_df)

            try:
                load_bestlaps_cached.clear()
            except Exception:
                pass

            progress.empty()
            label.empty()
            status_ph.empty()

            df = clean_df
            last_updated = ts

        else:
            # Cache-fil finnes → bruk den cachede funksjonen
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

    # Senere i samme session
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

    # Auto-refresh: trigger rerun, men ny scraping styres av cache TTL / clear()
    st_autorefresh(
        interval=int(REFRESH_INTERVAL.total_seconds() * 1000),
        key="silent_auto_refresh",
        limit=None,
    )

    # --------------------------------------------------------
    # "Sist oppdatert" + passordbeskyttet manuelt oppdateringspanel
    # --------------------------------------------------------

    st.session_state.setdefault("show_refresh_prompt", False)

    with st.container():
        col1, col2 = st.columns([3, 1], gap="small")

        with col1:
            st.caption(f"Sist oppdatert (data): {ts_str}")

        with col2:
            if st.button("🔄 Oppdater nå", key="open_refresh_prompt"):
                st.session_state.show_refresh_prompt = True
                st.rerun()

    # "Popup"/prompt for manuell oppdatering (bruker expander som visuell dialog)
    if st.session_state.show_refresh_prompt:
        with st.expander("🔐 Bekreft manuell oppdatering", expanded=True):
            st.write("Denne handlingen oppdaterer leaderboard-data manuelt for alle brukere.")
            pw = st.text_input("Passord", type="password", key="refresh_pw")

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Avbryt", key="cancel_refresh"):
                    st.session_state.show_refresh_prompt = False
                    st.rerun()

            with col_b:
                if st.button("Bekreft oppdatering", key="confirm_refresh"):
                    if pw.strip() != REFRESH_PASSWORD:
                        st.error("Feil passord. Oppdatering avvist.")
                    else:
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
                        st.session_state.show_refresh_prompt = False
                        st.success("Leaderboard-data oppdatert!")
                        st.rerun()

    # --------------------------------------------------------
    # Tabeller
    # --------------------------------------------------------

    st.subheader("🏆 Topp 10 i måneden (raskeste per chip)")
    st.dataframe(df_month_top10, hide_index=True)

    st.subheader(f"🏁 Topp 10 i dag ({today})")
    st.dataframe(df_today_top10, hide_index=True)

    st.markdown("---")
    st.caption("🚴‍♂️ Denne siden er utviklet av Aasmund Lindtveit (Plogen fra Solemskogen).")


if __name__ == "__main__":
    main()
