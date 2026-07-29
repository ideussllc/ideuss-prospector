FROM python:3.11-slim

WORKDIR /app

# Instalar cron
RUN apt-get update && apt-get install -y cron tzdata && \
    ln -sf /usr/share/zoneinfo/America/Bogota /etc/localtime && \
    echo "America/Bogota" > /etc/timezone && \
    rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar scripts
COPY . .

# Variables de entorno (configurar en EasyPanel)
ENV PIPEDRIVE_API_KEY=""
ENV TELEGRAM_BOT_TOKEN=""
ENV TELEGRAM_HOME_CHANNEL="8808084550"
ENV SERPAPI_KEY=""
ENV HUNTER_API_KEY=""
ENV APOLLO_API_KEY=""
ENV FAL_KEY=""
ENV GOOGLE_SHEET_ID="1eWonq7pQiH25rLwgXTN2iK92W3LQWKaU0YQyk1gevxA"
ENV GOOGLE_TOKEN_B64=""
ENV TZ="America/Bogota"

# Script que corre el cron — vuelca las env vars y ejecuta run.py
RUN echo '#!/bin/bash\n\
# Cargar variables de entorno del contenedor\n\
export $(cat /proc/1/environ | tr "\\0" "\\n" | grep -E "PIPEDRIVE|TELEGRAM|SERPAPI|HUNTER|APOLLO|FAL|GOOGLE|TZ") 2>/dev/null\n\
cd /app\n\
python3 run.py >> /var/log/prospector.log 2>&1' > /app/cron_run.sh && \
    chmod +x /app/cron_run.sh

# Crontab: 8:30 AM lunes a viernes (hora Bogotá)
RUN echo "30 8 * * 1-5 root /app/cron_run.sh" > /etc/cron.d/prospector && \
    chmod 0644 /etc/cron.d/prospector && \
    crontab /etc/cron.d/prospector

# Crear archivo de log
RUN touch /var/log/prospector.log

# Mantener el contenedor vivo con cron en foreground
CMD ["bash", "-c", "printenv > /etc/environment && cron -f"]
