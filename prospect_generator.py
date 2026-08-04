#!/usr/bin/env python3
"""
prospect_generator.py  v2.0
IDEUSS — Sistema de Prospección Automática
─────────────────────────────────────────────────────────────────────────────
1. Busca negocios en Cali y Bogotá via OpenStreetMap (maps_client)
2. Deduplica contra leads ya procesados (archivo local JSON)
3. Enriquece cada lead:
   - Busca email de contacto en su sitio web
   - Detecta UNA señal de dolor concreta (metodología Donald Miller / StoryBrand)
4. Crea Organización + Lead en Pipedrive con nota de señal de dolor
5. Crea actividad de seguimiento en Pipedrive (llamada en 2 días)
6. Envía email de prospección personalizado desde ventas@ideuss.com via Gmail
7. Guarda reporte diario en Google Sheets
8. Devuelve JSON estructurado para que el agente lo resuma y envíe a Telegram
"""

import base64
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── SSL (macOS self-signed certs) ─────────────────────────────────────────────
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# ── Rutas ─────────────────────────────────────────────────────────────────────
MAPS_CLIENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps_client.py")
GAPI        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_api.py")
SEEN_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_leads.json")
SHEET_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sheet_id.txt")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ── Cargar configuración dinámica ─────────────────────────────────────────────
def load_config() -> dict:
    """Carga la configuración desde el archivo JSON externo."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            print(f"✅ Config cargada: {len(cfg.get('segmentos_activos',[]))} segmentos | {len(cfg.get('ciudades',[]))} ciudades", file=sys.stderr)
            return cfg
        except Exception as e:
            print(f"⚠️  Error leyendo config: {e} — usando defaults", file=sys.stderr)
    return {}

CFG = load_config()

# ── Configuración (desde archivo o defaults) ──────────────────────────────────
CITIES          = CFG.get("ciudades",          ["Cali, Colombia", "Bogota, Colombia"])
MAX_LEADS_TOTAL = CFG.get("leads_por_dia",     10)
SEARCH_RADIUS_M = CFG.get("radio_busqueda_m",  8000)
LEADS_PER_QUERY = CFG.get("leads_por_consulta",8)
MAPS_TIMEOUT_S  = CFG.get("timeout_maps_s",    90)

# Construir NICHES desde los segmentos activos del catálogo
_catalogo = CFG.get("catalogo_segmentos", {})
_activos  = CFG.get("segmentos_activos",  ["clinicas_dentales","clinicas_veterinarias","centros_estetica"])
NICHES = {
    _catalogo[s]["nombre"]: _catalogo[s]["categorias_osm"]
    for s in _activos if s in _catalogo
} if _catalogo else {
    "Clínicas Dentales":     ["dentist"],
    "Clínicas Veterinarias": ["veterinary"],
    "Centros de Estética":   ["gym"],
}

# Email config desde archivo
_email_cfg      = CFG.get("email", {})
BOOKING_URL     = _email_cfg.get("booking_url",   "https://www.ideuss.com/agendar-reuniones/")
BRIEF_WEB_URL   = _email_cfg.get("brief_web_url", "https://www.ideuss.com/brief-sitio-web/")
MARIA_WA_URL    = _email_cfg.get("maria_whatsapp","https://wa.me/573052211369")
SENDER_NAME     = _email_cfg.get("firma_nombre",  "Alejandro Torres")
SENDER_TITLE    = _email_cfg.get("firma_titulo",  "Director General")
AGENCY_NAME     = _email_cfg.get("firma_agencia", "IDEUSS")
AGENCY_MOTO     = _email_cfg.get("firma_moto",    "Agencia IA y Automatización que mejoran la rentabilidad de las empresas de manera fácil y rápida")
SENDER_MOBILE   = _email_cfg.get("firma_movil",   "(57)(315)8451170")
SENDER_USA      = _email_cfg.get("firma_usa",     "+1(786)579 0043")
SENDER_EMAIL    = _email_cfg.get("firma_email",   "ventas@ideuss.com")
ADDR_BOGOTA     = _email_cfg.get("firma_bogota",  "Cra 51 # 69-40 Piso 2 CP111221 Bogotá, Colombia")
ADDR_CALI       = _email_cfg.get("firma_cali",    "Cll 11 # 87-30 AP3-106 CP760032 Cali, Colombia")
WEB_1           = _email_cfg.get("firma_web1",    "www.IDEUSS.com")
WEB_2           = _email_cfg.get("firma_web2",    "www.AutoPrint365.com")

# ── Señales de dolor StoryBrand / Donald Miller ───────────────────────────────
# Para cada nicho, qué buscar y cómo interpretarlo
PAIN_SIGNALS = [
    {
        "name": "sin_cita_online",
        "description": "No ofrece reserva de citas online",
        "check": lambda soup, url, tags: not any(
            w in (soup or "") for w in ["agenda", "reserva", "cita online", "book", "turnos", "calendar", "appointment"]
        ),
        "message": "Su sitio web no permite reservar citas online. Los pacientes modernos esperan poder agendar en 30 segundos desde el móvil — sin llamar, sin esperar."
    },
    {
        "name": "whatsapp_manual",
        "description": "Usa WhatsApp manual como único canal digital",
        "check": lambda soup, url, tags: (
            "whatsapp" in (soup or "").lower() and
            not any(w in (soup or "").lower() for w in ["chatbot", "bot", "automatico", "automático", "24/7"])
        ),
        "message": "Usan WhatsApp como canal principal, pero de forma manual. Cada mensaje que llega fuera de horario es un cliente potencial perdido. Un chatbot IA atiende 24/7 sin costo adicional."
    },
    {
        "name": "web_desactualizada",
        "description": "Sitio web desactualizado o sin propuesta de valor clara (StoryBrand)",
        "check": lambda soup, url, tags: (
            soup is not None and
            len(soup) < 3000 and
            not any(w in (soup or "") for w in ["resultado", "beneficio", "transformación", "garantía", "testimonios", "reseñas"])
        ),
        "message": "Su sitio web no comunica claramente qué problema resuelve ni por qué elegirlos (metodología StoryBrand). Los visitantes se van en 8 segundos si no ven su propuesta de valor de forma inmediata."
    },
    {
        "name": "sin_web",
        "description": "No tiene sitio web propio",
        "check": lambda soup, url, tags: soup is None and not url,
        "message": "No encontramos sitio web propio. En 2025, el 87% de los pacientes buscan servicios de salud online antes de llamar. Sin web, son invisibles para la mayoría de sus clientes potenciales."
    },
    {
        "name": "sin_reseñas_gestionadas",
        "description": "Sin sistema de gestión de reseñas online",
        "check": lambda soup, url, tags: not any(
            w in (soup or "").lower() for w in ["google", "reseña", "opinión", "valoración", "review", "calificación"]
        ),
        "message": "No gestionan activamente sus reseñas online. El 93% de los consumidores lee reseñas antes de elegir un proveedor de salud o estética. Un sistema automático de solicitud de reseñas puede duplicar su calificación en 60 días."
    },
]

# ── Credenciales ──────────────────────────────────────────────────────────────
PIPEDRIVE_API_KEY       = os.environ.get("PIPEDRIVE_API_KEY", "")
HUNTER_API_KEY          = os.environ.get("HUNTER_API_KEY", "")
GOOGLE_SEARCH_API_KEY   = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_SEARCH_ENGINE_ID = os.environ.get("GOOGLE_SEARCH_ENGINE_ID", "963150806bcdc4590")
SERPAPI_KEY             = os.environ.get("SERPAPI_KEY", "")
APOLLO_API_KEY          = os.environ.get("APOLLO_API_KEY", "")

BOOKING_URL  = "https://www.ideuss.com/agendar-reuniones/"
BRIEF_WEB_URL = "https://www.ideuss.com/brief-sitio-web/"

# Señales de dolor que activan el bloque del brief de sitio web
WEB_PAIN_SIGNALS_BRIEF = {
    "sin_web", "web_desactualizada", "sin_cita_online", "sin_reseñas_gestionadas"
}
SENDER_NAME   = "Alejandro Torres"
SENDER_TITLE  = "Director General"
AGENCY_NAME   = "IDEUSS"
AGENCY_MOTO   = "Agencia IA y Automatización que mejoran la rentabilidad de las empresas de manera fácil y rápida"
SENDER_MOBILE = "(57)(315)8451170"
SENDER_USA    = "+1(786)579 0043"
SENDER_EMAIL  = "ventas@ideuss.com"
ADDR_BOGOTA   = "Cra 51 # 69-40 Piso 2 CP111221 Bogotá, Colombia"
ADDR_CALI     = "Cll 11 # 87-30 AP3-106 CP760032 Cali, Colombia"
WEB_1         = "www.IDEUSS.com"
WEB_2         = "www.AutoPrint365.com"


# ═════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ═════════════════════════════════════════════════════════════════════════════

def log(msg):
    print(msg, file=sys.stderr)

def load_seen() -> dict:
    """Carga OSM IDs y nombres ya procesados para evitar duplicados."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE) as f:
                data = json.load(f)
                # Soporta formato antiguo (lista) y nuevo (dict)
                if isinstance(data, list):
                    return {"ids": set(data), "names": set()}
                return {"ids": set(data.get("ids", [])), "names": set(data.get("names", []))}
        except Exception:
            pass
    return {"ids": set(), "names": set()}

def save_seen(seen: dict):
    with open(SEEN_FILE, "w") as f:
        json.dump({"ids": list(seen["ids"]), "names": list(seen["names"])}, f)

def pipedrive_post(endpoint: str, payload: dict):
    """POST a Pipedrive API v1. Devuelve el ID del recurso o None."""
    if not PIPEDRIVE_API_KEY:
        return None
    url  = f"https://api.pipedrive.com/v1/{endpoint}?api_token={PIPEDRIVE_API_KEY}"
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            data = json.loads(r.read())
            if data.get("success"):
                return data["data"].get("id")
            log(f"  ❌ Pipedrive [{endpoint}]: {data.get('error')}")
    except urllib.error.HTTPError as e:
        log(f"  ❌ Pipedrive [{endpoint}] HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        log(f"  ❌ Pipedrive [{endpoint}]: {e}")
    return None

def pipedrive_put(endpoint: str, payload: dict):
    """PUT a Pipedrive API v1."""
    if not PIPEDRIVE_API_KEY:
        return None
    url  = f"https://api.pipedrive.com/v1/{endpoint}?api_token={PIPEDRIVE_API_KEY}"
    body = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"},
                                  method="PUT")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            data = json.loads(r.read())
            return data.get("success", False)
    except Exception as e:
        log(f"  ❌ Pipedrive PUT [{endpoint}]: {e}")
    return False

def run_gapi(*args, timeout=30) -> dict | None:
    """Ejecuta google_api.py con los argumentos dados. Devuelve JSON o None."""
    cmd = [sys.executable, GAPI] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return json.loads(r.stdout)
        log(f"  ⚠️  gapi error: {r.stderr.strip()[:200]}")
    except Exception as e:
        log(f"  ❌ gapi excepción: {e}")
    return None


# ═════════════════════════════════════════════════════════════════════════════
# FASE 1 — OBTENER LEADS DE MAPS
# ═════════════════════════════════════════════════════════════════════════════

def get_leads_from_maps(city: str, category: str, limit: int, radius: int) -> list:
    cmd = [sys.executable, MAPS_CLIENT, "nearby",
           "--near", city, "--category", category,
           "--limit", str(limit), "--radius", str(radius)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=MAPS_TIMEOUT_S)
        if r.returncode != 0:
            log(f"  ⚠️  maps error [{category}@{city}]: {r.stderr.strip()[:100]}")
            return []
        data  = json.loads(r.stdout)
        items = data.get("results", [])
        log(f"  ✅ {len(items)} resultados [{category}] en {city}")
        return items
    except subprocess.TimeoutExpired:
        log(f"  ⏱️  Timeout [{category}@{city}] — omitido")
        return []
    except Exception as e:
        log(f"  ❌ maps excepción [{category}@{city}]: {e}")
        return []


# ═════════════════════════════════════════════════════════════════════════════
# FASE 2 — ENRIQUECIMIENTO WEB
# ═════════════════════════════════════════════════════════════════════════════

def fetch_page_text(url: str, timeout=10) -> str | None:
    """Descarga una página web y devuelve el texto plano (sin HTML)."""
    if not url:
        return None
    try:
        if not url.startswith("http"):
            url = "https://" + url
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; IDEUSSBot/1.0)"
        })
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as r:
            raw = r.read(50000).decode("utf-8", errors="ignore")
            # Extraer texto: quitar tags HTML básicos
            text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>",  " ", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).lower()
            return text
    except Exception:
        return None

def find_email_in_text(text: str) -> str | None:
    """Extrae el primer email encontrado en el texto."""
    if not text:
        return None
    emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    # Filtrar emails de plataformas genéricas o imágenes
    blacklist = {"example.com", "sentry.io", "w3.org", "schema.org",
                 "google.com", "facebook.com", "instagram.com", "wixpress.com",
                 "squarespace.com", "godaddy.com", "moovitapp.com", "rappi.com",
                 "mercadolibre.com", "yandex.ru", "superprof.co", "wordpress.com",
                 "hotmail.com", "gmail.com", "yahoo.com", "outlook.com",
                 "duckduckgo.com", "bing.com", "apple.com", "microsoft.com",
                 # Directorios y plataformas de reservas — no son el negocio
                 "agendapro.com", "nexdu.com", "mapy.com", "dateas.com",
                 "archivo.biz", "dondeseria.com", "actualidadoral.com",
                 "topdoctors.com.co", "okvet.co", "lcsc.edu",
                 # Hospitales públicos y gobierno — fuera del segmento PYME
                 "gov.co", "edu.co", "org.co",
                 # Hosting y constructores
                 "wix.com", "hostinger.com", "bluehost.com",
                 # Empleo
                 "indeed.com", "glassdoor.com", "bumeran.com",
                 # Viajes y mapas
                 "agoda.com", "booking.com", "trivago.com",
                 "mapcarta.com", "iherb.com"}
    for e in emails:
        domain = e.split("@")[-1].lower()
        if domain not in blacklist and not domain.endswith(".png"):
            return e
    return None


def search_email_google_maps(business_name: str, city: str, maps_url: str = "") -> str | None:
    """
    Extrae email, teléfono y website desde Google Maps via SerpApi.
    Mejor fuente para negocios pequeños colombianos.
    Devuelve email si lo encuentra, y enriquece el lead con web y teléfono.
    """
    if not SERPAPI_KEY:
        return None

    query = f"{business_name} {city} Colombia"
    url   = (f"https://serpapi.com/search.json"
             f"?api_key={SERPAPI_KEY}"
             f"&engine=google_maps"
             f"&q={urllib.parse.quote(query)}"
             f"&gl=co&hl=es")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IDEUSSBot/1.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            data    = json.loads(r.read())
            results = data.get("local_results", [])
            for place in results[:3]:
                # 1. Email directo (raro pero posible)
                email = place.get("email", "")
                if email:
                    log(f"    📧 Email Google Maps: {email}")
                    return email

                # 2. Guardar teléfono si lo encontramos (enriquecimiento extra)
                phone = place.get("phone", "")
                if phone:
                    log(f"    📱 Teléfono Maps: {phone}")
                    # Lo guardamos para uso posterior en el lead
                    search_email_google_maps._last_phone = normalize_phone(phone)

                # 3. Website del lugar → scrapear para email
                website = place.get("website", "")
                if website:
                    log(f"    🌐 Web Maps: {website[:50]}")
                    search_email_google_maps._last_website = website
                    page = fetch_page_text(website, timeout=8)
                    if page:
                        email = find_email_in_text(page)
                        if email:
                            log(f"    📧 Email web (Maps): {email}")
                            return email
    except Exception as e:
        log(f"    ⚠️  Google Maps SerpApi error: {e}")
    return None


def search_email_apollo(business_name: str, city: str) -> str | None:
    """
    Busca email via Apollo.io People + Organization Search.
    Plan gratuito: 50 créditos/mes. Ideal para empresas colombianas.

    Estrategia:
    1. Organization Search → email genérico de la empresa
    2. People Search → email del contacto principal (dueño/gerente)
    """
    if not APOLLO_API_KEY:
        return None

    headers = {
        "Content-Type":  "application/json",
        "X-Api-Key":     APOLLO_API_KEY,
        "Cache-Control": "no-cache",
    }

    # 1️⃣ Organization Search — busca la empresa por nombre y ciudad
    org_payload = json.dumps({
        "q_organization_name": business_name,
        "organization_locations": [city, "Colombia"],
        "page":     1,
        "per_page": 3,
    }).encode()

    try:
        req = urllib.request.Request(
            "https://api.apollo.io/v1/mixed_companies/search",
            data=org_payload, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=12) as r:
            data  = json.loads(r.read())
            orgs  = data.get("organizations", [])
            if orgs:
                org = orgs[0]
                # Email genérico de la organización
                org_email = org.get("sanitized_phone","") or ""
                # Apollo a veces devuelve el email en primary_email
                for key in ["primary_email","email","contact_email"]:
                    if org.get(key):
                        log(f"    📧 Apollo org email: {org[key]}")
                        return org[key]
                # También revisar los contactos asociados
                org_id = org.get("id","")
                if org_id:
                    # 2️⃣ People Search dentro de la organización
                    people_payload = json.dumps({
                        "organization_ids": [org_id],
                        "person_titles":    ["director", "gerente", "propietario",
                                            "dueño", "administrador", "founder",
                                            "owner", "manager"],
                        "page":     1,
                        "per_page": 5,
                    }).encode()
                    req2 = urllib.request.Request(
                        "https://api.apollo.io/v1/mixed_people/api_search",
                        data=people_payload, headers=headers, method="POST"
                    )
                    with urllib.request.urlopen(req2, context=SSL_CTX, timeout=12) as r2:
                        pdata   = json.loads(r2.read())
                        people  = pdata.get("people", [])
                        for person in people:
                            email = person.get("email","")
                            if email and "?" not in email:
                                log(f"    📧 Apollo people: {email} ({person.get('title','')})")
                                return email
    except Exception as e:
        log(f"    ⚠️  Apollo org search error: {e}")

    # 3️⃣ People Search directo por nombre del negocio como empresa
    try:
        people_payload2 = json.dumps({
            "q_organization_name": business_name,
            "person_locations":    [city, "Colombia"],
            "page":     1,
            "per_page": 5,
        }).encode()
        req3 = urllib.request.Request(
            "https://api.apollo.io/v1/mixed_people/api_search",
            data=people_payload2, headers=headers, method="POST"
        )
        with urllib.request.urlopen(req3, context=SSL_CTX, timeout=12) as r3:
            pdata3  = json.loads(r3.read())
            people3 = pdata3.get("people", [])
            for person in people3:
                email = person.get("email","")
                if email and "?" not in email:
                    log(f"    📧 Apollo direct people: {email} ({person.get('title','')})")
                    return email
    except Exception as e:
        log(f"    ⚠️  Apollo people search error: {e}")

    return None


def search_email_hunter(business_name: str, website: str) -> str | None:
    """
    Busca email via Hunter.io (plan gratuito: 25 búsquedas/mes).
    Estrategia 1: Domain Search — devuelve todos los emails conocidos del dominio.
    Estrategia 2: Email Finder — intenta construir el email del contacto principal.
    """
    if not HUNTER_API_KEY:
        return None

    # Extraer dominio del website
    domain = ""
    if website:
        domain = re.sub(r"https?://", "", website.strip()).split("/")[0].strip()
        domain = re.sub(r"^www\.", "", domain)

    # Estrategia 1: Domain Search (más potente — devuelve emails reales del dominio)
    if domain:
        url = (f"https://api.hunter.io/v2/domain-search"
               f"?domain={urllib.parse.quote(domain)}"
               f"&api_key={HUNTER_API_KEY}"
               f"&limit=5")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IDEUSSBot/1.0"})
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as r:
                data    = json.loads(r.read())
                emails  = data.get("data", {}).get("emails", [])
                # Preferir emails de tipo "generic" (info@, contacto@) o el primero disponible
                generic = [e["value"] for e in emails if e.get("type") == "generic"]
                if generic:
                    log(f"    📧 Hunter domain-search (generic): {generic[0]}")
                    return generic[0]
                if emails:
                    log(f"    📧 Hunter domain-search: {emails[0]['value']}")
                    return emails[0]["value"]
        except Exception as e:
            log(f"    ⚠️  Hunter domain-search error: {e}")

    # Estrategia 2: Email Finder por nombre del negocio + dominio
    if domain:
        # Separar nombre del negocio en palabras para first_name / last_name
        words = business_name.strip().split()
        first = urllib.parse.quote(words[0]) if words else ""
        last  = urllib.parse.quote(words[1]) if len(words) > 1 else ""
        if first and last:
            url2 = (f"https://api.hunter.io/v2/email-finder"
                    f"?domain={urllib.parse.quote(domain)}"
                    f"&first_name={first}&last_name={last}"
                    f"&api_key={HUNTER_API_KEY}")
            try:
                req2 = urllib.request.Request(url2, headers={"User-Agent": "IDEUSSBot/1.0"})
                with urllib.request.urlopen(req2, context=SSL_CTX, timeout=10) as r2:
                    data2  = json.loads(r2.read())
                    email2 = data2.get("data", {}).get("email", "")
                    score  = data2.get("data", {}).get("score", 0)
                    if email2 and score >= 50:
                        log(f"    📧 Hunter email-finder (score={score}): {email2}")
                        return email2
            except Exception as e:
                log(f"    ⚠️  Hunter email-finder error: {e}")

    return None


def find_website_serpapi(business_name: str, city: str) -> str | None:
    """
    Busca el sitio web del negocio via SerpApi (Google Search).
    Plan gratuito: 100 búsquedas/mes sin tarjeta.
    """
    if not SERPAPI_KEY:
        return None

    SKIP = {"facebook.com", "instagram.com", "twitter.com", "youtube.com",
            "linkedin.com", "tiktok.com", "google.com", "yelp.com",
            "tripadvisor.com", "paginas-amarillas.com.co", "cylex.com.co",
            "waze.com", "foursquare.com", "maps.apple.com", "bing.com",
            "elempleo.com", "computrabajo.com", "duckduckgo.com",
            "mapcarta.com", "doctoralia.co", "doctoralia.com",
            "directorio.com.co", "paginasamarillas.com", "infobel.com",
            "cylex.com", "whereis.com", "n49.com", "hotfrog.com.co",
            "encontacto.com", "guiaslocales.com", "empresite.com.co",
            # Hoteles, viajes y reservas — frecuentes en búsquedas ambiguas
            "agoda.com", "booking.com", "trivago.com", "hotels.com",
            "expedia.com", "airbnb.com", "hostelworld.com",
            # Hosting y constructores web — no son el negocio
            "dominioestudio.com", "wix.com", "squarespace.com",
            "godaddy.com", "hostinger.com", "bluehost.com",
            # Empleo
            "indeed.com", "glassdoor.com", "bumeran.com"}

    query = f'"{business_name}" {city} Colombia'
    url   = (f"https://serpapi.com/search.json"
             f"?api_key={SERPAPI_KEY}"
             f"&engine=google"
             f"&q={urllib.parse.quote(query)}"
             f"&gl=co&hl=es&num=5")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IDEUSSBot/1.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as r:
            data    = json.loads(r.read())
            results = data.get("organic_results", [])
            for item in results:
                link   = item.get("link", "")
                domain = re.sub(r"https?://", "", link).split("/")[0].lower()
                domain = re.sub(r"^www\.", "", domain)
                if not any(s in domain for s in SKIP) and "." in domain:
                    log(f"    🌐 Web encontrada (SerpApi): {link[:60]}")
                    return link.split("?")[0]
    except Exception as e:
        log(f"    ⚠️  SerpApi error: {e}")
    return None


def find_website_google(business_name: str, city: str) -> str | None:
    """
    Busca el sitio web del negocio.
    Cascada: SerpApi (primario) → Google Custom Search API (fallback).
    """
    # 1️⃣ SerpApi — más fácil de configurar, 100/mes gratis sin tarjeta
    if SERPAPI_KEY:
        result = find_website_serpapi(business_name, city)
        if result:
            return result

    # 2️⃣ Google Custom Search API — 100/día gratis (requiere billing activo)
    if not GOOGLE_SEARCH_API_KEY:
        return None

    SKIP = {"facebook.com", "instagram.com", "twitter.com", "youtube.com",
            "linkedin.com", "tiktok.com", "google.com", "yelp.com",
            "tripadvisor.com", "paginas-amarillas.com.co", "cylex.com.co",
            "waze.com", "foursquare.com", "maps.apple.com", "bing.com",
            "elempleo.com", "computrabajo.com"}

    query = f'"{business_name}" {city} Colombia'
    url   = (f"https://www.googleapis.com/customsearch/v1"
             f"?key={GOOGLE_SEARCH_API_KEY}"
             f"&cx={GOOGLE_SEARCH_ENGINE_ID}"
             f"&num=5&gl=co&hl=es"
             f"&q={urllib.parse.quote(query)}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IDEUSSBot/1.0"})
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as r:
            data  = json.loads(r.read())
            items = data.get("items", [])
            for item in items:
                link   = item.get("link", "")
                domain = re.sub(r"https?://", "", link).split("/")[0].lower()
                domain = re.sub(r"^www\.", "", domain)
                if not any(s in domain for s in SKIP) and "." in domain:
                    log(f"    🌐 Web encontrada (Google CSE): {link[:60]}")
                    return link.split("?")[0]
    except Exception as e:
        log(f"    ⚠️  Google CSE error: {e}")
    return None


def search_email_web(business_name: str, city: str, website: str) -> str | None:
    """
    Enriquecimiento de email en cascada (sin API keys):
    1. Subpáginas de contacto del sitio propio (/contacto /contact /nosotros)
    2. DuckDuckGo HTML scraping con nombre + ciudad
    3. Búsqueda site:dominio en DuckDuckGo
    """
    # Estrategia 1: subpáginas del sitio propio
    if website:
        base = website.rstrip("/")
        if not base.startswith("http"):
            base = "https://" + base
        for path in ["/contacto", "/contact", "/nosotros", "/about", "/quienes-somos", "/contactenos"]:
            text = fetch_page_text(base + path, timeout=8)
            if text:
                email = find_email_in_text(text)
                if email:
                    log(f"    📧 Email en {path}: {email}")
                    return email

    # Estrategia 2: DuckDuckGo HTML scraping
    query   = f'"{business_name}" {city} email contacto'
    encoded = urllib.parse.quote(query)
    ddg_url = f"https://html.duckduckgo.com/html/?q={encoded}"
    try:
        req = urllib.request.Request(ddg_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=12) as r:
            html  = r.read(100000).decode("utf-8", errors="ignore")
            email = find_email_in_text(html)
            if email:
                log(f"    📧 Email vía DuckDuckGo: {email}")
                return email
    except Exception:
        pass

    # Estrategia 3: site:dominio en DuckDuckGo
    if website:
        domain   = re.sub(r"https?://", "", website).split("/")[0]
        query2   = f"site:{domain} email contacto"
        enc2     = urllib.parse.quote(query2)
        ddg_url2 = f"https://html.duckduckgo.com/html/?q={enc2}"
        try:
            req2 = urllib.request.Request(ddg_url2, headers={
                "User-Agent": "Mozilla/5.0 (compatible; IDEUSSBot/1.0)"
            })
            with urllib.request.urlopen(req2, context=SSL_CTX, timeout=12) as r2:
                html2  = r2.read(80000).decode("utf-8", errors="ignore")
                email2 = find_email_in_text(html2)
                if email2:
                    log(f"    📧 Email vía site-search: {email2}")
                    return email2
        except Exception:
            pass

    return None


def extract_phone(page_text: str | None, tags: dict) -> str:
    """
    Extrae número de teléfono/WhatsApp del texto de la página o de los tags OSM.
    Normaliza al formato internacional colombiano +57XXXXXXXXXX.
    """
    # 1️⃣ Tags OSM (más confiable)
    phone = (tags.get("phone","") or tags.get("contact:phone","") or
             tags.get("contact:mobile","") or tags.get("mobile",""))
    if phone:
        return normalize_phone(phone)

    # 2️⃣ Texto de la página web
    if page_text:
        # Patrones colombianos: 300-123-4567, +57 300 1234567, (601) 234 5678, etc.
        patterns = [
            r'\+57[\s\-]?(?:3\d{2})[\s\-]?\d{3}[\s\-]?\d{4}',   # celular intl
            r'\b3\d{2}[\s\-]?\d{3}[\s\-]?\d{4}\b',               # celular local
            r'\+57[\s\-]?\(?\d{1,3}\)?[\s\-]?\d{3}[\s\-]?\d{4}', # fijo intl
            r'\(60[1-9]\)[\s\-]?\d{3}[\s\-]?\d{4}',              # fijo Bogotá/Cali
            r'\b(?:601|602|604|605|606|607|608)[\s\-]?\d{3}[\s\-]?\d{4}\b', # fijos
        ]
        for pattern in patterns:
            match = re.search(pattern, page_text)
            if match:
                return normalize_phone(match.group())
    return ""


def normalize_phone(phone: str) -> str:
    """Normaliza teléfono al formato +57XXXXXXXXXX para WhatsApp."""
    # Quitar todo excepto dígitos y +
    digits = re.sub(r"[^\d]", "", phone)
    if digits.startswith("57") and len(digits) >= 11:
        return f"+{digits}"
    if digits.startswith("3") and len(digits) == 10:  # celular colombiano
        return f"+57{digits}"
    if len(digits) == 7:  # fijo sin indicativo de ciudad
        return digits  # dejar como está, sin normalizar
    if digits and not digits.startswith("57"):
        return f"+57{digits}" if len(digits) == 10 else digits
    return phone.strip()


def whatsapp_link(phone: str, message: str = "") -> str:
    """Genera link directo de WhatsApp."""
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", phone)
    if not digits.startswith("57"):
        digits = f"57{digits}"
    msg_enc = urllib.parse.quote(message) if message else ""
    return f"https://wa.me/{digits}{'?text=' + msg_enc if msg_enc else ''}"


def detect_pain_signal(page_text: str | None, website: str, tags: dict) -> dict:
    """
    Detecta UNA señal de dolor concreta y verdadera según metodología
    StoryBrand / Donald Miller. Devuelve la señal más relevante.
    """
    for signal in PAIN_SIGNALS:
        try:
            if signal["check"](page_text, website, tags):
                return {
                    "name":        signal["name"],
                    "description": signal["description"],
                    "message":     signal["message"],
                }
        except Exception:
            continue
    # Fallback genérico
    return {
        "name":        "procesos_manuales",
        "description": "Procesos operativos no automatizados",
        "message":     "Identificamos que sus procesos de atención, seguimiento y marketing aún dependen de tareas manuales que consumen tiempo de su equipo y generan errores. La automatización IA puede recuperar 15+ horas semanales."
    }

def enrich_lead(lead: dict) -> dict:
    """
    Enriquece un lead:
    - Descarga su web y extrae email
    - Detecta señal de dolor
    """
    website  = lead.get("website", "") or ""
    tags     = lead.get("tags", {})
    phone    = lead.get("phone", "") or tags.get("phone", "") or tags.get("contact:phone", "")
    email    = lead.get("email", "") or tags.get("email", "") or tags.get("contact:email", "")

    # Obtener texto de la página
    page_text = None
    if website:
        log(f"    🌐 Analizando web: {website}")
        page_text = fetch_page_text(website)
        if not email and page_text:
            email = find_email_in_text(page_text)
            if email:
                log(f"    📧 Email en web: {email}")

    # Extraer teléfono si no vino de OSM
    if not phone:
        phone = extract_phone(page_text, tags)
        if phone:
            log(f"    📱 Teléfono extraído: {phone}")

    # Si no hay email → cascada de enriquecimiento
    if not email:
        name = (lead.get("name") or "").strip()
        city = lead.get("_source_city", "").split(",")[0].strip()

        # 0️⃣ Si no hay website, buscarlo primero con Google (permite usar Hunter después)
        if not website:
            log(f"    🔍 Buscando website con Google: {name}...")
            found_web = find_website_google(name, city)
            if found_web:
                website = found_web
                lead["_website"] = website
                # Intentar extraer email directo de la web encontrada
                page_text = fetch_page_text(website)
                if page_text:
                    email = find_email_in_text(page_text) or ""
                    if email:
                        log(f"    📧 Email en web encontrada: {email}")

        # 1️⃣ Google Maps via SerpApi — mejor fuente para negocios pequeños CO
        if not email:
            log(f"    🗺️  Buscando en Google Maps: {name}...")
            search_email_google_maps._last_phone   = ""
            search_email_google_maps._last_website = ""
            email = search_email_google_maps(name, city, lead.get("maps_url","")) or ""
            # Aprovechar teléfono y web que Maps encontró aunque no haya email
            if not phone and getattr(search_email_google_maps, "_last_phone", ""):
                phone = search_email_google_maps._last_phone
                lead["_phone"] = phone
                log(f"    📱 Teléfono enriquecido desde Maps: {phone}")
            if not website and getattr(search_email_google_maps, "_last_website", ""):
                website = search_email_google_maps._last_website
                lead["_website"] = website
                log(f"    🌐 Website enriquecido desde Maps: {website[:50]}")

        # 2️⃣ Apollo.io — busca por nombre + ciudad
        if not email:
            log(f"    🚀 Buscando en Apollo.io: {name}...")
            email = search_email_apollo(name, city) or ""

        # 3️⃣ Hunter.io — solo si hay dominio
        if not email and website:
            log(f"    🎯 Buscando email con Hunter.io...")
            email = search_email_hunter(name, website) or ""

        # 4️⃣ Scraping de subpáginas (gratis, sin límite)
        if not email:
            log(f"    🔎 Scraping web para: {name}...")
            email = search_email_web(name, city, website) or ""

        if not email:
            log(f"    📋 Email no encontrado — quedará para búsqueda manual")

    # Detectar señal de dolor
    pain = detect_pain_signal(page_text, website, tags)
    log(f"    🎯 Señal de dolor: [{pain['name']}] {pain['description']}")

    lead["_email"]   = email or ""
    lead["_phone"]   = phone or ""
    lead["_pain"]    = pain
    lead["_website"] = website
    return lead


# ═════════════════════════════════════════════════════════════════════════════
# FASE 3 — PIPEDRIVE
# ═════════════════════════════════════════════════════════════════════════════

def create_pipedrive_entries(lead: dict, niche: str) -> dict:
    """Crea Organización, Lead y Actividad en Pipedrive. Devuelve IDs."""
    name     = lead.get("name", "Sin nombre")
    address  = lead.get("address", "")
    website  = lead.get("_website", "")
    phone    = lead.get("_phone", "")
    email    = lead.get("_email", "")
    pain     = lead.get("_pain", {})
    maps_url = lead.get("maps_url", "")
    city     = lead.get("_source_city", "").split(",")[0].strip()

    # 1️⃣ Organización
    org_id = pipedrive_post("organizations", {"name": name})
    if org_id:
        log(f"  🏢 Org creada (id={org_id}): {name}")

    # 2️⃣ Persona de contacto
    person_payload = {"name": f"Contacto — {name}"}
    if org_id:
        person_payload["org_id"] = org_id
    if phone:
        person_payload["phone"] = [{"value": phone, "label": "work", "primary": True}]
    if email:
        person_payload["email"] = [{"value": email, "label": "work", "primary": True}]
    person_id = pipedrive_post("persons", person_payload)

    # 3️⃣ Lead en buzón de prospectos
    lead_payload = {"title": f"{name} | {niche}"}
    if org_id:    lead_payload["organization_id"] = org_id
    if person_id: lead_payload["person_id"]       = person_id
    lead_id = pipedrive_post("leads", lead_payload)
    if lead_id:
        log(f"  📌 Lead creado (id={lead_id})")

    # 4️⃣ Nota enriquecida con señal de dolor
    if lead_id or org_id:
        wa_link  = whatsapp_link(phone, f"Hola {name}, soy Alejandro Torres de IDEUSS...")
        wa_html  = f'<a href="{wa_link}">💬 Abrir WhatsApp</a>' if wa_link else "No disponible"
        nota_html = f"""
<b>🎯 SEÑAL DE DOLOR DETECTADA:</b><br>
<b>{pain.get('description','')}</b><br>
{pain.get('message','')}<br><br>
<b>📍 Datos del negocio:</b><br>
<b>Nicho:</b> {niche}<br>
<b>Ciudad:</b> {city}<br>
<b>Dirección:</b> {address}<br>
<b>Teléfono:</b> {phone or 'No disponible'}<br>
<b>WhatsApp:</b> {wa_html}<br>
<b>Email:</b> {email or 'No encontrado'}<br>
<b>Sitio Web:</b> {website or 'Sin web'}<br>
<b>Google Maps:</b> <a href="{maps_url}">{maps_url}</a><br><br>
<i>Lead generado automáticamente por IDEUSS Prospecting Engine</i>
"""
        note_payload = {"content": nota_html}
        if lead_id:   note_payload["lead_id"]   = lead_id
        elif org_id:  note_payload["org_id"]     = org_id
        note_id = pipedrive_post("notes", note_payload)
        if note_id:
            log(f"  📝 Nota de dolor añadida (note_id={note_id})")

    # 5️⃣ Actividad de seguimiento (llamada en 2 días hábiles)
    due_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    activity_payload = {
        "subject":   f"Llamada de prospección — {name}",
        "type":      "call",
        "due_date":  due_date,
        "due_time":  "10:00",
        "duration":  "00:15",
        "note":      f"Señal detectada: {pain.get('description','')}. {pain.get('message','')}",
        "done":      0,
    }
    if person_id: activity_payload["person_id"] = person_id
    if org_id:    activity_payload["org_id"]    = org_id
    act_id = pipedrive_post("activities", activity_payload)
    if act_id:
        log(f"  📅 Actividad creada para {due_date} (id={act_id})")

    return {
        "org_id":    org_id,
        "person_id": person_id,
        "lead_id":   lead_id,
        "act_id":    act_id,
    }


# ═════════════════════════════════════════════════════════════════════════════
# FASE 4 — EMAIL
# ═════════════════════════════════════════════════════════════════════════════

def generate_fal_mockup(name: str, niche: str, city: str) -> str | None:
    """
    Genera un mockup de sitio web con FAL.ai para incluir en el email.
    Retorna la URL pública de la imagen o None si falla.
    """
    import os, urllib.request, json, ssl as _ssl

    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        log("  ⚠️  FAL_KEY no configurada — sin mockup")
        return None

    # Paleta y hero según nicho
    niche_lower = niche.lower()
    if "dental" in niche_lower:
        paleta = "white and medical blue (#1a73e8)"
        hero_img = "smiling patient in dental chair with confident doctor"
        headline = f"Tu Clínica Dental de Confianza en {city}"
    elif "veterinari" in niche_lower:
        paleta = "warm green (#2e7d32) and white"
        hero_img = "happy pet owner with dog and friendly veterinarian"
        headline = f"Cuidamos a tu Mascota en {city}"
    elif "estética" in niche_lower or "gym" in niche_lower or "fitness" in niche_lower:
        paleta = "rose gold (#c2185b) and white"
        hero_img = "fit person in modern gym with trainer"
        headline = f"Tu Centro de Bienestar en {city}"
    elif "spa" in niche_lower or "bienestar" in niche_lower:
        paleta = "soft gold (#f9a825) and white"
        hero_img = "relaxed woman in luxury spa treatment"
        headline = f"Tu Spa y Centro de Bienestar en {city}"
    elif "óptica" in niche_lower or "optometría" in niche_lower:
        paleta = "light blue (#0288d1) and grey"
        hero_img = "person trying modern glasses in bright optical store"
        headline = f"Tu Óptica de Confianza en {city}"
    elif "médic" in niche_lower or "clínica" in niche_lower:
        paleta = "medical blue (#1565c0) and white"
        hero_img = "professional doctor with patient in modern clinic"
        headline = f"Tu Consulta Médica en {city}"
    else:
        paleta = "professional blue and white"
        hero_img = "professional business team in modern office"
        headline = f"{name} — Tu Empresa en {city}"

    prompt = (
        f"Professional modern website mockup screenshot for '{name}' business in {city} Colombia. "
        f"Color scheme: {paleta}. Clean professional design. "
        f"Header: logo placeholder left, navigation center, 'RESERVAR CITA' CTA button right. "
        f"Hero section: {hero_img}, headline '{headline}', subtitle about quality service. "
        f"Trust bar: 4.9 Google stars, number of clients, WhatsApp button, Online booking. "
        f"3 service cards with icons. Testimonials section with client photos. "
        f"WhatsApp floating button. Professional footer with contact info. "
        f"Realistic website screenshot, high quality, no watermarks."
    )

    ctx = _ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE

    try:
        # FAL queue submit
        payload = json.dumps({
            "prompt":      prompt,
            "image_size":  "portrait_4_3",
            "num_images":  1,
            "enable_safety_checker": False,
        }).encode()

        req = urllib.request.Request(
            "https://fal.run/fal-ai/flux/schnell",
            data=payload,
            headers={
                "Authorization": f"Key {fal_key}",
                "Content-Type":  "application/json",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            result = json.loads(r.read())

        images = result.get("images", [])
        if images:
            url = images[0].get("url", "")
            if url:
                log(f"  🎨 Mockup FAL generado: {url[:60]}...")
                return url
    except Exception as e:
        log(f"  ⚠️  FAL error: {e}")
    return None


def generate_email(lead: dict, niche: str) -> dict:
    """Genera asunto y cuerpo HTML personalizado con la señal de dolor."""
    name     = lead.get("name", "Estimado equipo")
    city     = lead.get("_source_city", "su ciudad").split(",")[0].strip()
    pain     = lead.get("_pain", {})
    pain_msg = pain.get("message", "sus procesos operativos pueden optimizarse con IA")
    pain_name = pain.get("name", "")

    subject = f"{name}: detectamos algo en su negocio que le puede estar costando clientes"

    # Bloque de brief web — solo cuando la señal está relacionada con presencia digital
    brief_block = ""
    if pain_name in WEB_PAIN_SIGNALS_BRIEF:
        brief_block = f"""
<div style="background:#f0f7ff;border-left:4px solid #1a73e8;padding:16px 20px;
border-radius:4px;margin:20px 0">
<p style="margin:0 0 8px"><strong>🎁 Diagnóstico gratuito de su presencia digital</strong></p>
<p style="margin:0 0 12px;color:#555;font-size:14px">
Completando este breve formulario (2 minutos) recibirá una propuesta personalizada 
de sitio web automatizado con <strong>CRM, WhatsApp y ChatBot con IA</strong> 
— sin costo ni compromiso.
</p>
<p style="margin:0">
<a href="{BRIEF_WEB_URL}" 
   style="background:#1a73e8;color:#fff;padding:10px 24px;border-radius:6px;
          text-decoration:none;font-weight:bold;display:inline-block">
   📋 Solicitar diagnóstico gratuito
</a>
</p>
<p style="margin:8px 0 0;font-size:12px;color:#888">
{BRIEF_WEB_URL}
</p>
</div>"""

    # Generar mockup FAL si tiene señal de presencia web
    mockup_url = None
    if pain_name in WEB_PAIN_SIGNALS_BRIEF:
        log(f"  🎨 Generando mockup web con FAL.ai para {name}...")
        mockup_url = generate_fal_mockup(name, niche, city)

    # Bloque imagen mockup
    mockup_block = ""
    if mockup_url:
        mockup_block = f"""
<div style="margin:24px 0;text-align:center">
<p style="margin:0 0 12px;font-weight:bold;color:#333">
  🖥️ Así podría verse el sitio web de <strong>{name}</strong>:
</p>
<img src="{mockup_url}"
     alt="Mockup sitio web {name}"
     style="width:100%;max-width:560px;border-radius:8px;
            box-shadow:0 4px 16px rgba(0,0,0,0.15);border:1px solid #e0e0e0"/>
<p style="margin:8px 0 0;font-size:12px;color:#888;font-style:italic">
  Diseño conceptual generado por IDEUSS — personalizable según su identidad.
</p>
</div>"""

    body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px">

<p>Cordial saludo,</p>

<p>Mi nombre es <strong>{SENDER_NAME}</strong>, Director General de
<strong>{AGENCY_NAME}</strong> — agencia especializada en Automatización
Inteligente para empresas en Colombia.</p>

<p>Antes de escribirle, revisamos su negocio <strong>{name}</strong>
en {city} y encontramos algo concreto:</p>

<blockquote style="border-left:4px solid #f0a500;padding:12px 20px;
background:#fffbf0;margin:16px 0;border-radius:4px">
🎯 <strong>{pain.get('description','').upper()}</strong><br><br>
{pain_msg}
</blockquote>

<p>En <strong>{AGENCY_NAME}</strong> trabajamos con tres paquetes según tu alcance:</p>

<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px">
<tr style="background:#1a73e8;color:#fff">
  <th style="padding:10px;text-align:left">Paquete</th>
  <th style="padding:10px;text-align:center">Setup</th>
  <th style="padding:10px;text-align:center">Mensual</th>
</tr>
<tr style="background:#f8f9ff">
  <td style="padding:10px;border-bottom:1px solid #eee"><strong>Starter</strong> — Landing 1 página + WhatsApp</td>
  <td style="padding:10px;text-align:center;border-bottom:1px solid #eee"><strong>desde $400 USD</strong></td>
  <td style="padding:10px;text-align:center;border-bottom:1px solid #eee">$59 USD/mes</td>
</tr>
<tr>
  <td style="padding:10px;border-bottom:1px solid #eee"><strong>Growth</strong> — Multi-página + CRM + WhatsApp IA</td>
  <td style="padding:10px;text-align:center;border-bottom:1px solid #eee"><strong>$1.050 USD</strong></td>
  <td style="padding:10px;text-align:center;border-bottom:1px solid #eee">$179 USD/mes</td>
</tr>
<tr style="background:#f8f9ff">
  <td style="padding:10px"><strong>Scale</strong> — Multi-canal + Voz + Chat web IA</td>
  <td style="padding:10px;text-align:center"><strong>$2.100 USD</strong></td>
  <td style="padding:10px;text-align:center">$299 USD/mes</td>
</tr>
</table>

<p style="font-size:13px;color:#666">
💳 Facturación en COP al TRM del día para clientes en Colombia.<br>
El precio final se define en una reunión de 30 minutos según el alcance real de tu proyecto.
</p>

{mockup_block}
{brief_block}

<p>Consulta con nuestra agente <strong>MarIA</strong> experta en Automatización:<br>
👉 <a href="{MARIA_WA_URL}">{MARIA_WA_URL}</a></p>

<p>¿Le gustaría ver en <strong>20 minutos</strong> cómo aplicaría esto exactamente a <em>{name}</em>? Sin costo ni compromiso.</p>

<p>👉 <a href="{BOOKING_URL}">{BOOKING_URL}</a></p>

<p>Quedo atento a su respuesta.</p>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:13px;color:#555">
<strong>{SENDER_NAME}</strong> | {SENDER_TITLE}<br>
<strong>{AGENCY_NAME}</strong> — {AGENCY_MOTO}<br><br>
📱 {SENDER_MOBILE} &nbsp;|&nbsp; 🇺🇸 {SENDER_USA}<br>
✉️ {SENDER_EMAIL}<br>
📍 {ADDR_BOGOTA}<br>
📍 {ADDR_CALI}<br>
🌐 {WEB_1} &nbsp;|&nbsp; {WEB_2}
</p>

</body></html>"""

    return {"subject": subject, "body_html": body_html}


def create_gmail_draft(recipient: str, email_content: dict, lead_name: str,
                       pipedrive_lead_id: str = "", pipedrive_person_id: str = "",
                       pipedrive_org_id: str = "") -> bool:
    """
    Crea un BORRADOR en Gmail para revisión humana Y registra actividad
    de email en Pipedrive asociada al Lead (no solo a la Persona).
    """
    if not recipient:
        return False

    import base64 as _b64
    from email.mime.multipart import MIMEMultipart as _MMP
    from email.mime.text import MIMEText as _MMT

    draft_id = None
    try:
        import google.oauth2.credentials
        import googleapiclient.discovery

        token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_token.json")
        with open(token_path) as tf:
            td = json.load(tf)

        creds = google.oauth2.credentials.Credentials(
            token         = td.get("token"),
            refresh_token = td.get("refresh_token"),
            token_uri     = "https://oauth2.googleapis.com/token",
            client_id     = td.get("client_id"),
            client_secret = td.get("client_secret"),
        )
        svc = googleapiclient.discovery.build("gmail", "v1", credentials=creds)

        msg = _MMP("alternative")
        msg["To"]      = recipient
        msg["From"]    = '"Alejandro Torres — IDEUSS" <ventas@ideuss.com>'
        msg["Subject"] = email_content["subject"]
        msg.attach(_MMT(email_content["body_html"], "html", "utf-8"))

        raw   = _b64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        draft_id = draft.get("id","")
        log(f"  📝 Borrador creado (id={draft_id}) para {recipient}")

    except Exception as e:
        log(f"  ⚠️  Error creando borrador: {e}")
        return False

    # Registrar actividad de email en Pipedrive asociada al LEAD
    if PIPEDRIVE_API_KEY:
        from datetime import datetime
        activity_payload = {
            "subject":   f"Email enviado — {lead_name}",
            "type":      "email",
            "done":      0,
            "due_date":  datetime.now().strftime("%Y-%m-%d"),
            "due_time":  datetime.now().strftime("%H:%M"),
            "note":      (
                f"Borrador preparado para: {recipient}\n"
                f"Asunto: {email_content['subject']}\n"
                f"Gmail Draft ID: {draft_id}\n"
                f"Estado: Pendiente revisión y envío manual"
            ),
        }
        if pipedrive_lead_id:   activity_payload["lead_id"]   = pipedrive_lead_id
        if pipedrive_person_id: activity_payload["person_id"] = pipedrive_person_id
        if pipedrive_org_id:    activity_payload["org_id"]    = pipedrive_org_id

        act_id = pipedrive_post("activities", activity_payload)
        if act_id:
            log(f"  📨 Actividad email registrada en Pipedrive (lead_id={pipedrive_lead_id}, act_id={act_id})")

    return True


# ═════════════════════════════════════════════════════════════════════════════
# FASE 5 — GOOGLE SHEETS
# ═════════════════════════════════════════════════════════════════════════════

def get_or_create_sheet() -> str:
    """Devuelve el ID del Sheet de reporte, creándolo si no existe."""
    if os.path.exists(SHEET_FILE):
        with open(SHEET_FILE) as f:
            sid = f.read().strip()
            if sid:
                return sid

    log("  📊 Creando Google Sheet de reporte...")
    result = run_gapi("sheets", "create",
                      "--title", "IDEUSS — Reporte de Prospección Diaria")
    if not result:
        return ""

    sid = result.get("spreadsheetId", "")
    if not sid:
        return ""

    with open(SHEET_FILE, "w") as f:
        f.write(sid)

    # Encabezados
    headers = [[
        "Fecha", "Nombre", "Nicho", "Ciudad", "Dirección",
        "Teléfono", "WhatsApp", "Email", "Website", "Google Maps",
        "Señal de Dolor", "Pipedrive", "Borrador Gmail", "Asunto"
    ]]
    run_gapi("sheets", "update", sid, "Hoja 1!A1:N1",
             "--values", json.dumps(headers))
    log(f"  ✅ Sheet creado: https://docs.google.com/spreadsheets/d/{sid}")
    return sid


def save_to_sheets(report: list, sheet_id: str):
    """Añade las filas del reporte al Google Sheet."""
    if not sheet_id:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    rows  = []
    for r in report:
        rows.append([
            today,
            r["nombre"],
            r["nicho"],
            r["ciudad"],
            r["direccion"],
            r["telefono"],
            r.get("whatsapp", ""),
            r["email"],
            r["website"],
            r["maps_url"],
            r["señal_dolor"],
            "✅" if r["pipedrive_ok"] else "⚠️",
            "📝 Borrador" if r.get("draft_created") else "📋 Sin email",
            r["email_asunto"],
        ])

    result = run_gapi("sheets", "append", sheet_id, "Hoja 1!A:N",
                      "--values", json.dumps(rows))
    if result:
        log(f"  ✅ {len(rows)} filas guardadas en Google Sheets")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    today     = datetime.now().strftime("%Y-%m-%d")
    seen      = load_seen()
    sheet_id  = get_or_create_sheet()
    report    = []
    processed = 0

    log("=" * 60)
    log(f"🚀 IDEUSS Prospecting Engine — {today}")
    log(f"   Leads ya vistos: {len(seen)}")
    log("=" * 60)

    # ── FASE 1: Recolectar leads ──────────────────────────────────────────────
    all_leads = []
    for city in CITIES:
        for niche, categories in NICHES.items():
            for cat in categories:
                log(f"\n🔍 [{niche}] ({cat}) en {city}...")
                items = get_leads_from_maps(city, cat, LEADS_PER_QUERY, SEARCH_RADIUS_M)
                for item in items:
                    item["_niche"]       = niche
                    item["_source_city"] = city
                    all_leads.append(item)
                time.sleep(1.1)  # Respetar rate limit Nominatim

    log(f"\n📊 Leads encontrados: {len(all_leads)} | Ya vistos: {len(seen)}")

    # ── FASE 2–5: Enriquecer, Pipedrive, Email, Sheets ───────────────────────
    for lead in all_leads:
        if processed >= MAX_LEADS_TOTAL:
            break

        name = (lead.get("name") or "").strip()
        if not name:
            continue

        # Deduplicar por OSM ID Y por nombre normalizado (evita cadenas repetidas tipo Bodytech)
        osm_key  = f"{lead.get('osm_type','')}:{lead.get('osm_id','')}"
        name_key = re.sub(r"\s+", " ", name.lower().strip())
        if osm_key in seen["ids"] or name_key in seen["names"]:
            log(f"  ⏭️  Duplicado omitido: {name}")
            continue

        niche = lead["_niche"]
        city  = lead["_source_city"].split(",")[0].strip()
        log(f"\n{'─'*50}")
        log(f"🏷️  Lead {processed+1}: {name} [{niche}] — {city}")

        # Enriquecer
        lead = enrich_lead(lead)

        # Pipedrive
        pd_ids      = create_pipedrive_entries(lead, niche)
        pipedrive_ok = bool(pd_ids.get("lead_id"))

        # Borrador de email para revisión humana (NO se envía automáticamente)
        email_content  = generate_email(lead, niche)
        draft_created  = False
        recipient      = lead.get("_email", "")
        if recipient:
            draft_created = create_gmail_draft(
                recipient, email_content, name,
                pipedrive_lead_id   = pd_ids.get("lead_id", ""),
                pipedrive_person_id = pd_ids.get("person_id", ""),
                pipedrive_org_id    = pd_ids.get("org_id", ""),
            )
        else:
            log(f"  📋 Sin email — creando actividad de llamada en Pipedrive")
            # Crear actividad: llamar para solicitar email de contacto
            if pd_ids.get("lead_id") or pd_ids.get("org_id"):
                phone    = lead.get("_phone", "")
                due_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                call_payload = {
                    "subject":  f"📞 Llamar a {name} — solicitar email de contacto",
                    "type":     "call",
                    "due_date": due_date,
                    "due_time": "10:00",
                    "duration": "00:10",
                    "done":     0,
                    "note":     (
                        f"No encontramos email de contacto para {name} ({niche} en {city}).\n"
                        f"Llamar para solicitar un email de contacto y enviar propuesta.\n"
                        f"Teléfono registrado: {phone or 'No disponible'}\n"
                        f"Señal detectada: {lead.get('_pain', {}).get('description', '')}"
                    ),
                }
                if pd_ids.get("lead_id"):   call_payload["lead_id"]   = pd_ids["lead_id"]
                if pd_ids.get("person_id"): call_payload["person_id"] = pd_ids["person_id"]
                if pd_ids.get("org_id"):    call_payload["org_id"]    = pd_ids["org_id"]
                call_id = pipedrive_post("activities", call_payload)
                log(f"  📞 Actividad de llamada creada (id={call_id})")

        # Registrar en seen (OSM ID + nombre normalizado)
        seen["ids"].add(osm_key)
        seen["names"].add(name_key)

        # Acumular reporte
        pain = lead.get("_pain", {})

        # Flag para agente de propuesta web:
        # aplica cuando no tienen web propia O la web está desactualizada
        WEB_PAIN_SIGNALS = {"web_desactualizada", "sin_web", "sin_cita_online", "sin_reseñas_gestionadas"}
        needs_web_proposal = (
            pain.get("name", "") in WEB_PAIN_SIGNALS or
            not lead.get("_website", "")
        )

        report.append({
            "numero":              processed + 1,
            "nombre":              name,
            "nicho":               niche,
            "ciudad":              city,
            "direccion":           lead.get("address", "N/A"),
            "telefono":            lead.get("_phone", "N/A"),
            "whatsapp":            whatsapp_link(lead.get("_phone","")),
            "email":               recipient or "N/A",
            "website":             lead.get("_website", "") or "",
            "maps_url":            lead.get("maps_url", ""),
            "señal_dolor":         pain.get("description", "N/A"),
            "señal_nombre":        pain.get("name", ""),
            "señal_mensaje":       pain.get("message", ""),
            "needs_web_proposal":  needs_web_proposal,
            "pipedrive_ok":        pipedrive_ok,
            "draft_created":       draft_created,
            "email_sent":          False,
            "email_asunto":        email_content["subject"],
            "lead_id":             pd_ids.get("lead_id", ""),
            "org_id":              pd_ids.get("org_id", ""),
        })

        processed += 1

    # Guardar seen actualizado
    save_seen(seen)

    # Google Sheets
    save_to_sheets(report, sheet_id)
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else ""

    # ── OUTPUT JSON (para el agente de Hermes → Telegram) ────────────────────
    output = {
        "fecha":       today,
        "total":       processed,
        "sheet_url":   sheet_url,
        "leads":       report,
        "resumen": {
            "pipedrive_creados":      sum(1 for r in report if r["pipedrive_ok"]),
            "borradores_creados":     sum(1 for r in report if r.get("draft_created")),
            "sin_email":              sum(1 for r in report if not r.get("draft_created")),
            "propuestas_web_needed":  sum(1 for r in report if r.get("needs_web_proposal")),
            "leads_propuesta_web":    [
                r for r in report if r.get("needs_web_proposal")
            ],
            "señales_detectadas":     list({r["señal_dolor"] for r in report}),
        }
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
