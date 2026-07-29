# IDEUSS Prospector

Sistema de prospección automática diaria — busca leads por nicho en OpenStreetMap,
los enriquece y los registra en Pipedrive + Gmail + Google Sheets + Telegram.

## Variables de entorno requeridas en EasyPanel

```
PIPEDRIVE_API_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_HOME_CHANNEL=8808084550
SERPAPI_KEY=...
HUNTER_API_KEY=...
APOLLO_API_KEY=...
FAL_KEY=...
GOOGLE_SHEET_ID=1eWonq7pQiH25rLwgXTN2iK92W3LQWKaU0YQyk1gevxA
GOOGLE_TOKEN_B64=<base64 del google_token.json>
```

## Generar GOOGLE_TOKEN_B64

```bash
base64 -i ~/.hermes/google_token.json | tr -d '\n'
```

## Correr manualmente

```bash
python3 run.py
```

## Estructura

```
├── run.py                  ← Entrypoint (decodifica token y corre)
├── prospect_generator.py   ← Script principal
├── maps_client.py          ← Cliente OpenStreetMap
├── google_api.py           ← Cliente Google Workspace
├── config.json             ← Configuración de segmentos y ciudades
├── requirements.txt
└── Dockerfile
```
