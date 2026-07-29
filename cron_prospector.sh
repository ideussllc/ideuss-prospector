#!/bin/bash
# cron_prospector.sh — invocado por cron del VPS a las 8:30 AM L-V
# No necesita EasyPanel — corre directamente en el contenedor Docker

set -a
source /app/.env 2>/dev/null || true
set +a

cd /app
python3 run.py >> /var/log/ideuss_prospector.log 2>&1
