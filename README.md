# Velodromen i Asker - Leaderboard

En Streamlit-applikasjon som viser månedlige og daglige toppresultater fra Velodromen i Asker.

## Funksjonalitet

- Henter data fra Sporthive API
- Viser topp 10 tider per måned (beste tid per chip)
- Viser topp 10 tider for dagen
- Automatisk oppdatering hvert minutt
- Manuell oppdatering tilgjengelig

## Prosjektstruktur

```
velodromen_i_asker_leaderboard/
├── src/                    # Kildekode
│   ├── __init__.py
│   ├── app.py             # Hovedapplikasjon (Streamlit)
│   ├── scraper.py         # API-integrasjon mot Sporthive
│   └── utils/
│       ├── __init__.py
│       ├── config.py      # Konfigurasjonshåndtering
│       └── helpers.py     # Hjelpefunksjoner
├── tests/                 # Tester
│   └── __init__.py
├── app.py                 # Applikasjons-launcher
├── config.yaml           # Konfigurasjonsfil
├── requirements.txt      # Python-avhengigheter
├── runtime.txt          # Python-versjon
└── README.md
```

## Oppsett

1. Opprett et virtuelt miljø:
```bash
python -m venv .venv
```

2. Aktiver miljøet:
```bash
# Windows
.\.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate
```

3. Installer avhengigheter:
```bash
pip install -r requirements.txt
```

## Kjøring

Start applikasjonen med:
```bash
streamlit run app.py
```

## Run locally

From the project root you can start the Streamlit app with the launcher:

```powershell
streamlit run app.py
```

Alternatively you can run the app module directly (this will also work):

```powershell
streamlit run src/app.py
```

If you prefer a plain Python import check (smoke test):

```powershell
python -c "from src.app import main; print('import ok' if callable(main) else 'main missing')"
```

Note: run these commands from the repository root.

Applikasjonen vil være tilgjengelig på http://localhost:8501

## Utvikling

### Installere utviklingsverktøy

```bash
pip install black isort ruff pytest mypy pytest-cov
```

### Kjøre tester

```bash
pytest tests/
```

### Formatering og linting

```bash
# Formatering
black .
isort .

# Linting
ruff check .

# Type-sjekking
mypy .
```

## Konfigurasjon

Alle konfigurasjonsmuligheter finnes i `config.yaml`:

- `location_id`: ID for Velodromen i Asker
- `urls`: API-endepunkter
- `http`: Timeout og retry-innstillinger
- `app`: Streamlit-spesifikke innstillinger

## Lisens

MIT
