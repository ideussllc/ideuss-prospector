#!/usr/bin/env python3
"""
run.py — Entrypoint del prospector IDEUSS para VPS/EasyPanel
Decodifica Google token y config desde variables de entorno,
luego ejecuta prospect_generator.py
"""
import base64, json, os, subprocess, sys
from pathlib import Path

BASE = Path(__file__).parent

def decode_env(var_name: str, dest_path: Path):
    """Decodifica una variable base64 y la escribe como archivo."""
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

def main():
    print("🚀 IDEUSS Prospector — iniciando...", flush=True)

    # Decodificar Google token desde env
    decode_env("GOOGLE_TOKEN_B64", BASE / "google_token.json")

    # Decodificar config si viene desde env (opcional — si no, usa config.json del repo)
    if os.environ.get("PROSPECTOR_CONFIG_B64"):
        decode_env("PROSPECTOR_CONFIG_B64", BASE / "config.json")

    # Google Sheet ID desde env
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if sheet_id:
        (BASE / "sheet_id.txt").write_text(sheet_id)
        print(f"✅ GOOGLE_SHEET_ID → sheet_id.txt", flush=True)

    # Seen leads — inicializar si no existe
    seen_path = BASE / "seen_leads.json"
    if not seen_path.exists():
        seen_path.write_text('{"ids":[],"names":[]}')
        print("✅ seen_leads.json inicializado", flush=True)

    # Ejecutar el prospector
    print("\n▶️  Ejecutando prospect_generator.py...\n", flush=True)
    result = subprocess.run(
        [sys.executable, str(BASE / "prospect_generator.py")],
        env=os.environ.copy(),
    )
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
