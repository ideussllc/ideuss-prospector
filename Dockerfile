FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todos los scripts
COPY . .

# Variables de entorno requeridas (configurar en EasyPanel)
ENV PIPEDRIVE_API_KEY=""
ENV TELEGRAM_BOT_TOKEN=""
ENV TELEGRAM_HOME_CHANNEL="8808084550"
ENV SERPAPI_KEY=""
ENV HUNTER_API_KEY=""
ENV APOLLO_API_KEY=""
ENV FAL_KEY=""
ENV GOOGLE_SHEET_ID="1eWonq7pQiH25rLwgXTN2iK92W3LQWKaU0YQyk1gevxA"
ENV GOOGLE_TOKEN_B64=""

# El contenedor corre una vez y termina (cron lo invoca)
CMD ["python3", "run.py"]
