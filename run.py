#!/usr/bin/env python3
"""
run.py — Entrypoint del prospector IDEUSS para VPS/EasyPanel
Decodifica Google token, ejecuta prospect_generator.py
y envía resumen a Telegram directamente.
"""
import base64, json, os, subprocess, sys, ssl, urllib.request
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent

# ── SSL ───────────────────────────────────────────────────────────────────────
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode    = ssl.CERT_NONE


def decode_env(var_name: str, dest_path: Path):
    val = os.environ.get(var_name, "")
    if not val:
        print(f"⚠️  {var_name} no configurada", flush=True)
        return False
    try:
        decoded = base64.b64decode(val).decode("utf-8")
        dest_path.write_text(decoded, encoding="utf-8")
        print(f"✅ {var_name} → {dest_path.name}", flush=True)
        return True
    except Exception as e:
        print(f"❌ Error decodificando {var_name}: {e}", flush=True)
        return False


def send_telegram(message: str):
    """Envía mensaje a Telegram."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_HOME_CHANNEL", "8808084550")
    if not token:
        print("⚠️  TELEGRAM_BOT_TOKEN no configurado", flush=True)
        return
    try:
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "Markdown",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, context=CTX, timeout=10)
        print("✅ Resumen enviado a Telegram", flush=True)
    except Exception as e:
        print(f"⚠️  Telegram error: {e}", flush=True)


def build_telegram_summary(data: dict) -> str:
    """Construye el resumen ejecutivo para Telegram."""
    fecha   = data.get("fecha", datetime.now().strftime("%Y-%m-%d"))
    total   = data.get("total", 0)
    leads   = data.get("leads", [])
    resumen = data.get("resumen", {})

    con_email   = sum(1 for l in leads if l.get("email") and l["email"] != "N/A")
    borradores  = resumen.get("borradores_creados", 0)
    en_pd       = resumen.get("pipedrive_creados", 0)
    señales     = resumen.get("señales_detectadas", [])

    # Leads con email válido
    leads_con_email = [l for l in leads if l.get("email") and l["email"] != "N/A"]

    msg = f"🚀 *Prospección IDEUSS — {fecha}*\n\n"
    msg += f"📊 *Resumen*\n"
    msg += f"   • Leads generados:  {total}\n"
    msg += f"   • En Pipedrive:     {en_pd}\n"
    msg += f"   • Con email:        {con_email}\n"
    msg += f"   • Borradores Gmail: {borradores}\n"

    if señales:
        msg += f"\n🎯 *Señales detectadas:*\n"
        for s in señales[:3]:
            msg += f"   • {s[:60]}\n"

    if leads_con_email:
        msg += f"\n📧 *Leads con email ({len(leads_con_email)}):*\n"
        for l in leads_con_email[:5]:
            nombre = l.get("nombre", "—")[:25]
            email  = l.get("email", "—")
            ciudad = l.get("ciudad", "—").split(",")[0]
            msg += f"   • {nombre} ({ciudad})\n     `{email}`\n"

    # Distribución por ciudad
    ciudades = {}
    for l in leads:
        c = l.get("ciudad", "—").split(",")[0].strip()
        ciudades[c] = ciudades.get(c, 0) + 1
    if ciudades:
        msg += f"\n📍 *Por ciudad:*\n"
        for c, n in sorted(ciudades.items(), key=lambda x: -x[1]):
            msg += f"   • {c}: {n}\n"

    sheet_url = data.get("sheet_url", "")
    if sheet_url:
        msg += f"\n📊 [Ver reporte completo]({sheet_url})"

    return msg


def main():
    print("🚀 IDEUSS Prospector VPS — iniciando...", flush=True)
    print(f"   Hora: {datetime.now().strftime('%Y-%m-%d %H:%M')} (Bogotá)", flush=True)

    # Decodificar Google token
    decode_env("GOOGLE_TOKEN_B64", BASE / "google_token.json")

    # Config desde env (opcional)
    if os.environ.get("PROSPECTOR_CONFIG_B64"):
        decode_env("PROSPECTOR_CONFIG_B64", BASE / "config.json")

    # Google Sheet ID
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if sheet_id:
        (BASE / "sheet_id.txt").write_text(sheet_id)
        print(f"✅ GOOGLE_SHEET_ID configurado", flush=True)

    # Seen leads
    seen_path = BASE / "seen_leads.json"
    if not seen_path.exists():
        seen_path.write_text('{"ids":[],"names":[]}')
        print("✅ seen_leads.json inicializado", flush=True)

    # Ejecutar prospector — capturar stdout (JSON)
    print("\n▶️  Ejecutando prospect_generator.py...\n", flush=True)
    result = subprocess.run(
        [sys.executable, str(BASE / "prospect_generator.py")],
        env=os.environ.copy(),
        capture_output=False,  # stderr va a los logs del contenedor
        stdout=subprocess.PIPE,
        text=True,
    )

    # Parsear JSON de salida
    output_json = {}
    if result.stdout:
        try:
            output_json = json.loads(result.stdout)
            print(f"\n✅ JSON parseado — {output_json.get('total', 0)} leads", flush=True)
        except Exception as e:
            print(f"⚠️  Error parseando JSON: {e}", flush=True)
            print(f"   stdout preview: {result.stdout[:200]}", flush=True)

    # Enviar resumen a Telegram
    if output_json:
        summary = build_telegram_summary(output_json)
        send_telegram(summary)
    else:
        # Si no hay JSON, notificar el error
        send_telegram(
            f"⚠️ *Prospector IDEUSS* — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"El script terminó pero no generó JSON válido.\n"
            f"Revisa los logs en EasyPanel → prospector."
        )

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
