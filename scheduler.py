#!/usr/bin/env python3
"""
scheduler.py — Scheduler interno del prospector IDEUSS
Reemplaza cron del SO para evitar problemas con variables de entorno en Docker.
Corre prospect_generator.py a las 8:30 AM hora Bogotá, lunes a viernes.
"""
import time
import subprocess
import sys
import os
import logging
from datetime import datetime
import pytz

logging.basicConfig(
    level  = logging.INFO,
    format = "[%(asctime)s] %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("scheduler")

BOGOTA_TZ = pytz.timezone("America/Bogota")
TARGET_HOUR   = 8
TARGET_MINUTE = 30
WEEKDAYS      = {0, 1, 2, 3, 4}  # Lunes=0 ... Viernes=4

def should_run_now(now: datetime) -> bool:
    """¿Es hora de correr el prospector?"""
    return (
        now.weekday() in WEEKDAYS and
        now.hour   == TARGET_HOUR and
        now.minute == TARGET_MINUTE
    )

def run_prospector():
    """Ejecuta run.py (que decodifica tokens y corre el prospector)."""
    log.info("🚀 Iniciando prospección diaria...")
    base = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, os.path.join(base, "run.py")],
        env=os.environ.copy(),
    )
    if result.returncode == 0:
        log.info("✅ Prospección completada exitosamente")
    else:
        log.error(f"❌ Prospección terminó con error (exit={result.returncode})")

def main():
    log.info("⏰ Scheduler IDEUSS iniciado")
    log.info(f"   Zona horaria: America/Bogota")
    log.info(f"   Horario: {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} L-V")

    last_run_date = None  # Evitar doble ejecución el mismo día

    while True:
        now = datetime.now(BOGOTA_TZ)

        if should_run_now(now):
            today = now.date()
            if last_run_date != today:
                last_run_date = today
                log.info(f"📅 Ejecutando prospección — {now.strftime('%A %d/%m/%Y %H:%M')}")
                try:
                    run_prospector()
                except Exception as e:
                    log.error(f"❌ Error inesperado: {e}")
            # Esperar 90s para no re-ejecutar en el mismo minuto
            time.sleep(90)
        else:
            # Calcular segundos hasta las 8:30
            next_run = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
            if now >= next_run:
                from datetime import timedelta
                next_run += timedelta(days=1)
            secs = (next_run - now).total_seconds()
            if secs > 3600:
                log.info(f"💤 Próxima ejecución: {next_run.strftime('%A %d/%m %H:%M')} ({int(secs/3600)}h {int((secs%3600)/60)}m)")
                time.sleep(min(secs - 60, 3600))  # Despertar 1 min antes o cada hora
            else:
                time.sleep(30)  # Polling cada 30s cuando falta menos de 1h

if __name__ == "__main__":
    main()
