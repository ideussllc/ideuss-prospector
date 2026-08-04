#!/usr/bin/env python3
"""
generate_proposal.py
Genera la propuesta comercial completa después de que el prospecto
diligencia el brief. Usa las respuestas para recomendar el paquete
correcto y calcular el precio ajustado.
"""

# ── Condiciones comerciales Fábrica Webs v2 ───────────────────────────────────
PAQUETES = {
    "starter": {
        "nombre":     "Starter",
        "setup":      400,
        "mensual":    59,
        "sitio":      "Landing 1 página",
        "crm":        "No (formulario → email)",
        "agente_ia":  "WhatsApp por reglas",
        "hosting":    "Compartido",
        "color":      "#2e7d32",
    },
    "growth": {
        "nombre":     "Growth",
        "setup":      1050,
        "mensual":    179,
        "sitio":      "Multi-página",
        "crm":        "Twenty CRM en VPS propio",
        "agente_ia":  "WhatsApp IA generativo",
        "hosting":    "VPS dedicado (2 vCPU / 8 GB)",
        "color":      "#1a73e8",
    },
    "scale": {
        "nombre":     "Scale",
        "setup":      2100,
        "mensual":    299,
        "sitio":      "Multi-página + multicanal",
        "crm":        "Twenty CRM en VPS propio",
        "agente_ia":  "WhatsApp + Voz + Chat web IA",
        "hosting":    "VPS dedicado (4 vCPU / 16 GB)",
        "color":      "#c62828",
    },
}

EXTRAS = {
    "tienda_hasta_25":    {"label": "Tienda en línea hasta 25 productos",    "precio": 400},
    "tienda_25_50":       {"label": "Tienda en línea 25–50 productos",       "precio": 800},
    "tienda_50_100":      {"label": "Tienda en línea 50–100 productos",      "precio": 1200},
    "tienda_mas_100":     {"label": "Tienda en línea +100 productos",        "precio": None},  # cotizar
    "idioma_adicional":   {"label": "Idioma adicional (textos por cliente)", "precio_pct": 30},
}


def recomendar_paquete(brief: dict) -> tuple[str, list[dict], int]:
    """
    Analiza las respuestas del brief y recomienda el paquete más adecuado.
    Retorna: (paquete_key, extras_aplicables, precio_setup_total)
    """
    extras_aplicados = []
    setup_extra      = 0

    tiene_crm        = brief.get("tieneCrm") == "Sí"
    tiene_whatsapp   = brief.get("vendeWhatsapp") == "Sí"
    tiene_chatbot    = brief.get("tieneChatbot") == "Sí"
    tiene_tienda     = brief.get("tieneEcommerce") == "Sí"
    idiomas          = brief.get("idiomas", "Solo español")
    paginas          = brief.get("secciones", [])
    num_paginas      = len(paginas) if isinstance(paginas, list) else 1

    # Lógica de recomendación
    if tiene_chatbot or (tiene_crm and tiene_whatsapp):
        paquete_key = "scale"
    elif tiene_crm or tiene_whatsapp or num_paginas > 2:
        paquete_key = "growth"
    else:
        paquete_key = "starter"

    # Extras: tienda en línea
    if tiene_tienda:
        num_productos = brief.get("numProductos", "")
        if "más de 100" in str(num_productos).lower():
            extras_aplicados.append({**EXTRAS["tienda_mas_100"], "cotizar": True})
        elif "50" in str(num_productos) or "100" in str(num_productos):
            extras_aplicados.append(EXTRAS["tienda_50_100"])
            setup_extra += EXTRAS["tienda_50_100"]["precio"]
        elif "25" in str(num_productos):
            extras_aplicados.append(EXTRAS["tienda_25_50"])
            setup_extra += EXTRAS["tienda_25_50"]["precio"]
        else:
            extras_aplicados.append(EXTRAS["tienda_hasta_25"])
            setup_extra += EXTRAS["tienda_hasta_25"]["precio"]

    # Extras: idiomas adicionales
    if idiomas and "adicional" in idiomas.lower():
        n_idiomas = 1
        if "2 idiomas" in idiomas: n_idiomas = 2
        if "3 o más"  in idiomas: n_idiomas = 3
        base = PAQUETES[paquete_key]["setup"] + setup_extra
        recargo = int(base * 0.30 * n_idiomas)
        extras_aplicados.append({
            "label":  f"Idioma(s) adicional(es) x{n_idiomas} (+30% c/u)",
            "precio": recargo
        })
        setup_extra += recargo

    setup_total = PAQUETES[paquete_key]["setup"] + setup_extra
    return paquete_key, extras_aplicados, setup_total


def build_proposal_email(
    nombre_empresa: str,
    nombre_contacto: str,
    email: str,
    brief: dict,
    mockup_url: str = "",
    sender_name:  str = "Alejandro Torres",
    agency_name:  str = "IDEUSS — Agencia IA y Automatización",
    sender_email: str = "ventas@ideuss.com",
    sender_phone: str = "(57)(315)8451170",
    booking_url:  str = "https://www.ideuss.com/agendar-reuniones/",
    maria_url:    str = "https://wa.me/573052211369",
) -> dict:
    """
    Construye el email de propuesta completa post-brief.
    Retorna dict con 'subject' y 'body_html'.
    """
    paquete_key, extras, setup_total = recomendar_paquete(brief)
    pkg = PAQUETES[paquete_key]

    tipo_solicitud = brief.get("tipoSolicitud", "Sitio nuevo")
    ciudad         = brief.get("ciudadPais", "Colombia")

    subject = f"Propuesta IDEUSS para {nombre_empresa} — Paquete {pkg['nombre']} recomendado"

    # Tabla de los 3 paquetes
    def row(key, highlight=False):
        p = PAQUETES[key]
        bg = f"background:{p['color']}15;" if highlight else ""
        borde = f"border:2px solid {p['color']};" if highlight else "border:1px solid #eee;"
        check = "✅ " if highlight else ""
        return f"""<tr style="{bg}{borde}">
  <td style="padding:12px"><strong>{check}{p['nombre']}</strong>
    {'<br><span style="font-size:11px;color:' + p['color'] + '">⭐ Recomendado para ' + nombre_empresa + '</span>' if highlight else ''}
  </td>
  <td style="padding:12px;text-align:center"><strong>${p['setup']:,} USD</strong></td>
  <td style="padding:12px;text-align:center">${p['mensual']} USD/mes</td>
  <td style="padding:12px;font-size:13px">{p['sitio']}<br>{p['agente_ia']}<br><span style="color:#888">{p['hosting']}</span></td>
</tr>"""

    # Bloque de extras
    extras_block = ""
    hay_cotizar = any(e.get("cotizar") for e in extras)
    if extras:
        extras_items = ""
        for e in extras:
            if e.get("cotizar"):
                extras_items += f"<li>➕ {e['label']} — <strong>precio a cotizar aparte</strong></li>"
            else:
                extras_items += f"<li>➕ {e['label']} — <strong>+${e['precio']:,} USD</strong> (setup único)</li>"
        extras_block = f"""
<div style="background:#fff8e8;border-left:4px solid #f0a500;padding:14px 18px;border-radius:4px;margin:20px 0">
<p style="margin:0 0 8px;font-weight:bold">➕ Extras detectados según su brief:</p>
<ul style="margin:0;padding-left:20px">{extras_items}</ul>
{('<p style="margin:8px 0 0;font-size:13px;color:#666">Los ítems marcados como "precio a cotizar" se definen en la reunión según volumen y requerimientos específicos.</p>' if hay_cotizar else '')}
</div>"""

    # Precio total estimado
    precio_total_block = f"""
<div style="background:{pkg['color']};color:#fff;padding:18px 24px;border-radius:8px;margin:20px 0;text-align:center">
  <p style="margin:0 0 4px;font-size:14px;opacity:0.9">Inversión estimada para {nombre_empresa}</p>
  <p style="margin:0;font-size:28px;font-weight:bold">
    Paquete {pkg['nombre']}: ${setup_total:,} USD setup + ${pkg['mensual']} USD/mes
  </p>
  <p style="margin:8px 0 0;font-size:12px;opacity:0.85">
    💳 Facturación en COP al TRM del día · Precio definitivo se confirma en reunión aclaratoria
  </p>
</div>"""

    # Mockup
    mockup_block = ""
    if mockup_url:
        mockup_block = f"""
<div style="text-align:center;margin:24px 0">
<p style="font-weight:bold;margin:0 0 12px">🖥️ Así podría verse el nuevo sitio de <strong>{nombre_empresa}</strong>:</p>
<img src="{mockup_url}" alt="Mockup {nombre_empresa}"
     style="width:100%;max-width:580px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,0.15)"/>
<p style="font-size:12px;color:#999;margin:8px 0 0;font-style:italic">
Diseño conceptual — se personaliza con sus fotos, textos y colores de marca.
</p>
</div>"""

    body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:620px;margin:0 auto">

<p>Estimada/o <strong>{nombre_contacto}</strong>,</p>

<p>Gracias por completar el brief de <strong>{nombre_empresa}</strong>.
Con base en sus respuestas preparamos la siguiente propuesta:</p>

{mockup_block}

<h2 style="color:#333;border-bottom:2px solid {pkg['color']};padding-bottom:8px">
📦 Paquetes disponibles
</h2>

<table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:13px">
<tr style="background:#333;color:#fff">
  <th style="padding:10px;text-align:left">Paquete</th>
  <th style="padding:10px;text-align:center">Setup</th>
  <th style="padding:10px;text-align:center">Mensual</th>
  <th style="padding:10px;text-align:left">Incluye</th>
</tr>
{row('starter', paquete_key=='starter')}
{row('growth',  paquete_key=='growth')}
{row('scale',   paquete_key=='scale')}
</table>

{extras_block}

{precio_total_block}

<div style="background:#f5f5f5;padding:14px 18px;border-radius:6px;margin:20px 0;font-size:13px">
<p style="margin:0 0 6px;font-weight:bold">📌 Responsabilidades del cliente:</p>
<ul style="margin:0;padding-left:20px;color:#555">
  <li>Dominio propio a cargo del cliente</li>
  <li>Logo, fotos e imagen corporativa los suministra el cliente</li>
  <li>Si contrata idiomas adicionales, entrega los textos traducidos</li>
  <li>El proyecto incluye <strong>hasta 3 rondas de ajustes</strong> en el mockup</li>
  <li>Secciones o páginas fuera del alcance acordado se cotizan aparte</li>
</ul>
</div>

<p>¿Tiene 30 minutos esta semana para revisar la propuesta y confirmar el alcance?</p>

<p>Consulte con nuestra agente <strong>MarIA</strong>:<br>
👉 <a href="{maria_url}">{maria_url}</a></p>

<p style="margin:28px 0;text-align:center">
<a href="{booking_url}"
   style="background:{pkg['color']};color:#fff;padding:14px 36px;border-radius:8px;
          text-decoration:none;font-weight:bold;display:inline-block;font-size:16px">
   📅 Agendar reunión de propuesta (30 min)
</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="font-size:13px;color:#555;line-height:1.8">
<strong>{sender_name}</strong> | Director General<br>
<strong>{agency_name}</strong><br>
📱 {sender_phone} | 🇺🇸 +1(786)579 0043<br>
✉️ {sender_email}<br>
📍 Cra 51 # 69-40 Piso 2 Bogotá | Cll 11 # 87-30 Cali<br>
🌐 <a href="https://www.IDEUSS.com">www.IDEUSS.com</a> |
<a href="https://www.AutoPrint365.com">www.AutoPrint365.com</a>
</p>
</body></html>"""

    return {
        "subject":    subject,
        "body_html":  body_html,
        "paquete":    pkg["nombre"],
        "setup_usd":  setup_total,
        "mensual_usd": pkg["mensual"],
        "extras":     extras,
    }


if __name__ == "__main__":
    # Test con datos de ABC Cocinas
    brief_test = {
        "tipoSolicitud":  "Renovación",
        "tieneEcommerce": "Sí",
        "numProductos":   "hasta 25",
        "vendeWhatsapp":  "Sí",
        "tieneCrm":       "No",
        "tieneChatbot":   "No",
        "idiomas":        "Solo español",
        "secciones":      ["Inicio","Nosotros","Servicios/Productos","Contacto","Tienda en línea"],
    }
    result = build_proposal_email(
        nombre_empresa  = "ABC Cocinas",
        nombre_contacto = "Soraya Sarmiento",
        email           = "gventas@abccocinas.com",
        brief           = brief_test,
        mockup_url      = "https://v3b.fal.media/files/b/0aa50290/mG93sMfzbC2ZRJjcmAvaY_XYkRm3ye.png",
    )
    print(f"✅ Propuesta generada:")
    print(f"   Paquete recomendado: {result['paquete']}")
    print(f"   Setup:    ${result['setup_usd']:,} USD")
    print(f"   Mensual:  ${result['mensual_usd']} USD/mes")
    print(f"   Extras:   {len(result['extras'])}")
    print(f"   Asunto:   {result['subject']}")
