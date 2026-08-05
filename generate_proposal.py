#!/usr/bin/env python3
"""
generate_proposal.py  v2.0
Genera la propuesta comercial completa post-brief usando las condiciones
oficiales de Fábrica de Sitios Web IDEUSS (Planes_Fabrica_Web_IDEUSS.pdf).

Regla comercial:
  - SIEMPRE recomendar plan Scale como opción principal
  - Growth y Starter aparecen como alternativas de negociación
  - Extras (tienda, idiomas, voz) se calculan sobre el plan Scale
"""

from datetime import datetime, timedelta

# ── Condiciones comerciales oficiales ─────────────────────────────────────────
PAQUETES = {
    "starter": {
        "nombre":    "Starter",
        "emoji":     "🌱",
        "setup":     400,
        "mensual":   59,
        "sitio":     "Landing 1 página",
        "crm":       "No incluido (formulario → correo)",
        "agente_ia": "WhatsApp por reglas",
        "hosting":   "Compartido",
        "color":     "#2e7d32",
        "ideal":     "Para empezar con presencia digital sólida",
    },
    "growth": {
        "nombre":    "Growth",
        "emoji":     "📈",
        "setup":     1050,
        "mensual":   179,
        "sitio":     "Multi-página",
        "crm":       "Twenty CRM en servidor propio",
        "agente_ia": "WhatsApp IA generativa",
        "hosting":   "Servidor dedicado",
        "color":     "#1a73e8",
        "ideal":     "Sitio, CRM y agente que conversa de verdad",
    },
    "scale": {
        "nombre":    "Scale",
        "emoji":     "🚀",
        "setup":     2100,
        "mensual":   299,
        "sitio":     "Multi-página + multicanal",
        "crm":       "Twenty CRM en servidor propio",
        "agente_ia": "WhatsApp IA + chat web IA",
        "hosting":   "Servidor dedicado de mayor capacidad",
        "color":     "#c62828",
        "ideal":     "Máximo alcance: sitio, CRM, WhatsApp y chat web",
    },
}

EXTRAS_TIENDA = [
    {"max": 25,  "label": "Tienda en línea hasta 25 productos",  "precio": 400},
    {"max": 50,  "label": "Tienda en línea 25–50 productos",     "precio": 800},
    {"max": 100, "label": "Tienda en línea 50–100 productos",    "precio": 1200},
    {"max": None,"label": "Tienda en línea +100 productos",      "precio": None},  # cotizar
]

CANAL_VOZ = {
    "setup":    150,
    "mensual":  59,
    "minutos":  150,
    "nota":     "Solo disponible como complemento del plan Scale.",
}

DIRECCION = "IDEUSS LLC | 791 SW 191 St. Ave Pembroke Pines, FL 33028 USA"
TEL_USA   = "+1 (786) 579 0043"
SITIOS    = "www.IDEUSS.com | www.GradientCore.com"


def calcular_extras(brief: dict) -> list[dict]:
    """Calcula los extras según las respuestas del brief."""
    extras = []

    # Tienda en línea
    if brief.get("tieneEcommerce") == "Sí":
        num_str = str(brief.get("numProductos", "")).lower()
        if "más de 100" in num_str or "100+" in num_str:
            extras.append({**EXTRAS_TIENDA[3], "cotizar": True})
        elif "50" in num_str or "100" in num_str:
            extras.append(EXTRAS_TIENDA[2])
        elif "25" in num_str or "50" in num_str:
            extras.append(EXTRAS_TIENDA[1])
        else:
            extras.append(EXTRAS_TIENDA[0])

    # Idiomas adicionales
    idiomas = brief.get("idiomas", "Solo español")
    if idiomas and "adicional" in idiomas.lower():
        n = 3 if "3 o más" in idiomas else (2 if "2 idiomas" in idiomas else 1)
        recargo = int(PAQUETES["scale"]["setup"] * 0.30 * n)
        extras.append({
            "label":  f"Idioma(s) adicional(es) ×{n} (+30% del setup por idioma)",
            "precio": recargo,
            "nota":   "El cliente debe entregar los textos ya traducidos."
        })

    # Canal de voz (opcional)
    if brief.get("quiereVoz") == "Sí":
        extras.append({
            "label":  "Canal de voz (complemento Scale)",
            "precio": CANAL_VOZ["setup"],
            "mensual_extra": CANAL_VOZ["mensual"],
            "nota":   f"Incluye {CANAL_VOZ['minutos']} minutos/mes. Minutos adicionales se facturan aparte."
        })

    return extras


def calcular_precio(extras: list[dict]) -> tuple[int, int]:
    """Retorna (setup_total, mensual_extra)."""
    setup_scale   = PAQUETES["scale"]["setup"]
    mensual_scale = PAQUETES["scale"]["mensual"]
    setup_extra   = sum(e["precio"] for e in extras if e.get("precio") and not e.get("cotizar"))
    mensual_extra = sum(e.get("mensual_extra", 0) for e in extras)
    return setup_scale + setup_extra, mensual_scale + mensual_extra


def build_proposal_email(
    nombre_empresa:  str,
    nombre_contacto: str,
    email:           str,
    brief:           dict,
    mockup_url:      str = "",
    sender_name:     str = "Alejandro Torres",
    agency_name:     str = "IDEUSS — Agencia IA y Automatización",
    sender_email:    str = "ventas@ideuss.com",
    sender_phone:    str = "(57)(315)8451170",
    booking_url:     str = "https://www.ideuss.com/agendar-reuniones/",
    maria_url:       str = "https://wa.me/573052211369",
) -> dict:
    """
    Construye el email de propuesta oficial post-brief.
    Siempre recomienda Scale. Growth y Starter como alternativas.
    """
    extras          = calcular_extras(brief)
    setup_total, mensual_total = calcular_precio(extras)
    hay_cotizar     = any(e.get("cotizar") for e in extras)
    vigencia        = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
    pkg_scale       = PAQUETES["scale"]

    subject = f"Propuesta Fábrica Web IDEUSS para {nombre_empresa}"

    # ── Mockup ──────────────────────────────────────────────────────────────────
    mockup_block = ""
    if mockup_url:
        mockup_block = f"""
<div style="text-align:center;margin:28px 0">
<p style="font-weight:bold;font-size:16px;margin:0 0 12px;color:#333">
  🖥️ Así podría verse el nuevo sitio de <strong>{nombre_empresa}</strong>
</p>
<img src="{mockup_url}" alt="Mockup {nombre_empresa}"
     style="width:100%;max-width:580px;border-radius:12px;
            box-shadow:0 8px 32px rgba(0,0,0,0.18);border:1px solid #ddd"/>
<p style="font-size:12px;color:#999;margin:10px 0 0;font-style:italic">
  Diseño conceptual — se personaliza con sus fotos, textos y colores de marca.
  Hasta 3 rondas de ajustes incluidas.
</p>
</div>"""

    # ── Extras block ────────────────────────────────────────────────────────────
    extras_rows = ""
    for e in extras:
        if e.get("cotizar"):
            precio_str = "<em>A cotizar en reunión</em>"
        else:
            precio_str = f"+${e['precio']:,} USD setup"
            if e.get("mensual_extra"):
                precio_str += f" + ${e['mensual_extra']}/mes"
        nota_str = f"<br><span style='font-size:11px;color:#888'>{e['nota']}</span>" if e.get("nota") else ""
        extras_rows += f"""
<tr>
  <td style="padding:10px 12px;border-bottom:1px solid #f0e8d0">➕ {e['label']}{nota_str}</td>
  <td style="padding:10px 12px;border-bottom:1px solid #f0e8d0;text-align:right;font-weight:bold">{precio_str}</td>
</tr>"""

    extras_block = ""
    if extras:
        extras_block = f"""
<div style="background:#fffbf0;border:1px solid #f0a500;border-radius:8px;margin:20px 0;overflow:hidden">
<div style="background:#f0a500;color:#fff;padding:10px 16px;font-weight:bold">
  ➕ Extras detectados en su brief
</div>
<table style="width:100%;border-collapse:collapse">
  {extras_rows}
</table>
{'<p style="padding:8px 16px 12px;font-size:12px;color:#888;margin:0">* Los ítems "a cotizar" se definen en la reunión aclaratoria según volumen y requerimientos específicos.</p>' if hay_cotizar else ''}
</div>"""

    # ── Precio recomendado ──────────────────────────────────────────────────────
    precio_str = f"${setup_total:,} USD setup (único)" + (
        f" + cotización adicional" if hay_cotizar else ""
    ) + f" + ${mensual_total}/mes"

    precio_block = f"""
<div style="background:{pkg_scale['color']};color:#fff;padding:22px 28px;border-radius:10px;margin:24px 0;text-align:center">
  <p style="margin:0 0 6px;font-size:13px;opacity:0.85;text-transform:uppercase;letter-spacing:1px">
    Plan recomendado para {nombre_empresa}
  </p>
  <p style="margin:0 0 4px;font-size:32px;font-weight:bold">
    {pkg_scale['emoji']} Scale
  </p>
  <p style="margin:0 0 12px;font-size:20px;font-weight:bold">
    {precio_str}
  </p>
  <p style="margin:0;font-size:12px;opacity:0.8">
    💳 Facturación en COP al TRM del día · Precios no incluyen IVA<br>
    Propuesta válida por 30 días hasta el {vigencia}
  </p>
</div>"""

    # ── Tabla comparativa 3 planes ──────────────────────────────────────────────
    def plan_row(key):
        p   = PAQUETES[key]
        rec = key == "scale"
        bg  = f"background:{p['color']}12;" if rec else ""
        brd = f"border-left:3px solid {p['color']};" if rec else ""
        tag = f" &nbsp;<span style='background:{p['color']};color:#fff;font-size:10px;padding:2px 6px;border-radius:10px'>RECOMENDADO</span>" if rec else \
              " &nbsp;<span style='background:#999;color:#fff;font-size:10px;padding:2px 6px;border-radius:10px'>alternativa</span>"
        return f"""<tr style="{bg}{brd}">
  <td style="padding:12px">{p['emoji']} <strong>{p['nombre']}</strong>{tag}<br>
    <span style="font-size:12px;color:#666">{p['ideal']}</span></td>
  <td style="padding:12px;text-align:center"><strong>${p['setup']:,}</strong></td>
  <td style="padding:12px;text-align:center">${p['mensual']}</td>
  <td style="padding:12px;font-size:12px;color:#555">{p['sitio']}<br>{p['agente_ia']}</td>
</tr>"""

    tabla_planes = f"""
<h3 style="color:#333;margin:28px 0 12px">📊 Opciones disponibles</h3>
<p style="font-size:13px;color:#666;margin:0 0 12px">
  Scale es la opción que más se ajusta a las necesidades de <strong>{nombre_empresa}</strong>.
  Growth y Starter están disponibles como alternativas en caso de ajuste de presupuesto.
</p>
<table style="width:100%;border-collapse:collapse;font-size:13px">
<tr style="background:#333;color:#fff">
  <th style="padding:10px;text-align:left">Plan</th>
  <th style="padding:10px;text-align:center">Setup USD</th>
  <th style="padding:10px;text-align:center">Mensual USD</th>
  <th style="padding:10px;text-align:left">Incluye</th>
</tr>
{plan_row('scale')}
{plan_row('growth')}
{plan_row('starter')}
</table>"""

    # ── Responsabilidades ───────────────────────────────────────────────────────
    resp_block = """
<div style="background:#f5f5f5;padding:14px 18px;border-radius:6px;margin:20px 0;font-size:13px">
<p style="margin:0 0 8px;font-weight:bold">📌 Responsabilidades del cliente</p>
<ul style="margin:0;padding-left:20px;color:#555;line-height:1.8">
  <li>Dominio propio — el cliente lo adquiere si no lo tiene</li>
  <li>Logo, fotos e imagen corporativa — las suministra el cliente</li>
  <li>Si el material no llega a tiempo, IDEUSS genera imágenes con IA y entrega en el plazo pactado</li>
  <li>Idiomas adicionales — el cliente entrega los textos ya traducidos</li>
  <li>Secciones fuera del brief estándar o páginas adicionales se cotizan aparte</li>
</ul>
</div>"""

    # ── Proceso ─────────────────────────────────────────────────────────────────
    proceso_block = """
<h3 style="color:#333;margin:24px 0 10px">🔄 Cómo funciona</h3>
<ol style="font-size:13px;color:#555;line-height:2;margin:0;padding-left:20px">
  <li><strong>Mockup gratis</strong> — generado con base en su brief, hasta 3 rondas de ajustes</li>
  <li><strong>Reunión breve</strong> — afinamos alcance y confirmamos precio final</li>
  <li><strong>Orden de pedido</strong> — se envía con opciones de pago; producción inicia al confirmar pago</li>
  <li><strong>Entrega</strong> — sitio, CRM y agente IA conectados según el plan contratado</li>
</ol>"""

    body_html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:640px;margin:0 auto;padding:0 16px">

<p>Estimada/o <strong>{nombre_contacto}</strong>,</p>

<p>Gracias por completar el brief de <strong>{nombre_empresa}</strong>.
Analizamos sus respuestas y preparamos la siguiente propuesta:</p>

{mockup_block}

{precio_block}

{extras_block}

{tabla_planes}

{resp_block}

{proceso_block}

<p style="margin:28px 0 8px">¿Tiene 30 minutos esta semana para revisar el mockup y afinar el alcance?</p>

<p>Consulte con nuestra agente <strong>MarIA</strong>:<br>
👉 <a href="{maria_url}" style="color:{pkg_scale['color']}">{maria_url}</a></p>

<p style="margin:28px 0;text-align:center">
<a href="{booking_url}"
   style="background:{pkg_scale['color']};color:#fff;padding:16px 40px;border-radius:8px;
          text-decoration:none;font-weight:bold;display:inline-block;font-size:16px">
   📅 Agendar reunión de propuesta (30 min)
</a>
</p>

<hr style="border:none;border-top:1px solid #eee;margin:28px 0">

<p style="font-size:12px;color:#888;text-align:center">
  Propuesta válida por 30 días · Precios en USD sin IVA · Facturación en COP al TRM del día<br>
  Valores sujetos a ajuste si el alcance real supera el brief diligenciado.
</p>

<hr style="border:none;border-top:1px solid #eee;margin:16px 0">

<p style="font-size:13px;color:#555;line-height:1.9">
<strong>{sender_name}</strong> | Director General<br>
<strong>{agency_name}</strong><br>
📱 {sender_phone} | 🇺🇸 {TEL_USA}<br>
✉️ {sender_email}<br>
📍 {DIRECCION}<br>
🌐 {SITIOS}
</p>

</body></html>"""

    return {
        "subject":     subject,
        "body_html":   body_html,
        "paquete":     "Scale",
        "setup_usd":   setup_total,
        "mensual_usd": mensual_total,
        "extras":      extras,
        "vigencia":    vigencia,
        "hay_cotizar": hay_cotizar,
    }


if __name__ == "__main__":
    # Test ABC Cocinas
    brief_test = {
        "tipoSolicitud":  "Renovación",
        "tieneEcommerce": "Sí",
        "numProductos":   "hasta 25",
        "vendeWhatsapp":  "Sí",
        "tieneCrm":       "No",
        "tieneChatbot":   "No",
        "idiomas":        "Solo español",
        "secciones":      ["Inicio","Nosotros","Servicios/Productos","Contacto","Tienda en línea"],
        "quiereVoz":      "No",
    }
    r = build_proposal_email(
        nombre_empresa  = "ABC Cocinas",
        nombre_contacto = "Soraya Sarmiento",
        email           = "gventas@abccocinas.com",
        brief           = brief_test,
        mockup_url      = "https://v3b.fal.media/files/b/0aa50290/mG93sMfzbC2ZRJjcmAvaY_XYkRm3ye.png",
    )
    print(f"✅ Plan recomendado: {r['paquete']}")
    print(f"   Setup:   ${r['setup_usd']:,} USD")
    print(f"   Mensual: ${r['mensual_usd']}/mes")
    print(f"   Extras:  {[e['label'] for e in r['extras']]}")
    print(f"   Vigencia: {r['vigencia']}")
    print(f"   Asunto:  {r['subject']}")
