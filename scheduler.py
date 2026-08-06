#!/usr/bin/env python3
"""
scheduler.py — Scheduler interno del prospector IDEUSS
Corre en Contabo 24/7. Tareas:
  1. prospect_generator.py → 8:30 AM L-V hora Bogotá
  2. supabase_ping()       → cada 3 días (mantiene proyecto activo)
"""
import time
import subprocess
import sys
import os
import ssl
import logging
import urllib.request
from datetime import datetime, timedelta
import pytz

logging.basicConfig(
    level  = logging.INFO,
    format = "[%(asctime)s] %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("scheduler")

BOGOTA_TZ = pytz.timezone("America/Bogota")

# ── Configuración prospector ───────────────────────────────────────────────────
TARGET_HOUR   = 8
TARGET_MINUTE = 30
WEEKDAYS      = {0, 1, 2, 3, 4}  # Lunes=0 ... Viernes=4

# ── Configuración Supabase keepalive ──────────────────────────────────────────
SUPABASE_URL  = "https://lbzyovfyiffeuybomcyf.supabase.co"
SUPABASE_KEY  = os.environ.get("SUPABASE_SECRET_KEY", "")
PING_EVERY_DAYS = 3


def should_run_prospector(now: datetime) -> bool:
    return (
        now.weekday() in WEEKDAYS and
        now.hour   == TARGET_HOUR and
        now.minute == TARGET_MINUTE
    )


def run_prospector():
    log.info("🚀 Iniciando prospección diaria...")
    base = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, os.path.join(base, "run.py")],
        env=os.environ.copy(),
    )
    if result.returncode == 0:
        log.info("✅ Prospección completada")
    else:
        log.error(f"❌ Prospección terminó con error (exit={result.returncode})")


def supabase_ping():
    """Hace un GET al REST API de Supabase para mantener el proyecto activo."""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/",
            headers={
                "apikey":        SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
            }
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            status = r.status
        log.info(f"✅ Supabase keepalive OK (HTTP {status}) — lbzyovfyiffeuybomcyf activo")
    except Exception as e:
        log.warning(f"⚠️  Supabase ping falló: {e}")


def main():
    log.info("⏰ Scheduler IDEUSS iniciado (Contabo)")
    log.info(f"   Prospección: {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} L-V (Bogotá)")
    log.info(f"   Supabase keepalive: cada {PING_EVERY_DAYS} días")

    last_run_date   = None
    last_ping_date  = None

    # Ping inicial al arrancar
    supabase_ping()

    while True:
        now   = datetime.now(BOGOTA_TZ)
        today = now.date()

        # ── Prospección diaria ─────────────────────────────────────────────────
        if should_run_prospector(now) and last_run_date != today:
            last_run_date = today
            log.info(f"📅 Ejecutando prospección — {now.strftime('%A %d/%m/%Y %H:%M')}")
            try:
                run_prospector()
            except Exception as e:
                log.error(f"❌ Error inesperado en prospector: {e}")
            time.sleep(90)
            continue

        # ── Supabase keepalive cada 3 días ────────────────────────────────────
        if last_ping_date is None or (today - last_ping_date).days >= PING_EVERY_DAYS:
            last_ping_date = today
            supabase_ping()

        # ── Dormir hasta la próxima acción ────────────────────────────────────
        next_run = now.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
        if now >= next_run:
            next_run += timedelta(days=1)
        secs = (next_run - now).total_seconds()

        if secs > 3600:
            log.info(f"💤 Próxima prospección: {next_run.strftime('%A %d/%m %H:%M')} "
                     f"({int(secs/3600)}h {int((secs%3600)/60)}m)")
            time.sleep(min(secs - 60, 3600))
        else:
            time.sleep(30)


if __name__ == "__main__":
    main()
