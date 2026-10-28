"""
SHOZEN: vigia de stock y ofertas para modelos configurados (Jordan 4 Retro, Puma
180 / 180 Pro, Air Force 1 blancas, Puma Suede XL) en Bold, Moredrops y The Line.

Corre via GitHub Actions: cada corrida es independiente, compara contra el
estado guardado en ARCHIVO_ESTADO y avisa por Telegram solo cuando, en una
de las tallas objetivo (US hombre):
  - DISPONIBLE: la talla paso de agotada (o nunca vista) a tener stock
    (salvo en modelos con "solo_ofertas", que solo avisan en oferta).
  - OFERTA: la talla tiene stock y entro en descuento, o el precio de oferta
    bajo todavia mas desde el ultimo aviso.
Fuera del horario 8:00-23:00 (hora de Chile) no revisa nada.

Uso manual: python shozen.py
Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID para avisar (si no estan,
igual revisa y deja el log, pero no notifica).

Si Telegram rechaza el aviso, el script termina con error: asi la corrida
queda en rojo en GitHub (te llega correo) y el estado no se guarda, de modo
que la proxima corrida vuelve a intentar el mismo aviso.
"""

import html
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ============================== CONFIGURACION ==============================

# Productos de mujer o de niños: sus tallas no son US hombre aunque el numero
# coincida, asi que se descartan siempre.
FILTRO_NO_HOMBRE = re.compile(
    r"\b(mujer|wmns|junior|joven|ni[ñn]o|ni[ñn]a|ni[ñn]os|beb[ée]|infantil|"
    r"pre\s?escolar|preescolar|gs|bg|ps|td)\b",
    re.I,
)


def _tiene(patron, nombre):
    return bool(re.search(patron, nombre or "", re.I))


def es_jordan_4_retro(nombre, color):
    # "4" como numero de modelo y "retro" (excluye la linea "4 RM").
    return _tiene(r"\b4\b", nombre) and _tiene(r"\bretro\b", nombre)


def es_puma_180(nombre, color):
    # Cubre "Puma 180", "180 Pro", "PUMA-180 POP", etc.
    return _tiene(r"\bpuma\b", nombre) and _tiene(r"\b180\b", nombre)


def es_puma_suede_xl(nombre, color):
    return (_tiene(r"\bsuede\b", nombre) and _tiene(r"\bxl\b", nombre)
            and _tiene(r"zapatilla", nombre))


def es_air_force_1_blanca(nombre, color):
    if not (_tiene(r"\bair force 1\b", nombre) and _tiene(r"zapatilla", nombre)):
        return False
    if color:  # The Line trae el color como dato aparte
        return color.upper().startswith("BLANC")
    # Bold/Moredrops ponen el color al final del nombre, despues del genero
    # ("... Hombre Blanco/Negro"): el color principal debe ser blanco.
    return _tiene(r"\b(hombre|unisex)\s+blanc", nombre)


# Cada entrada: termino de busqueda en las tiendas, filtro sobre el nombre
# real (el buscador de las tiendas trae mucho ruido) y tallas US hombre.
CONFIGURACION_BUSQUEDA = [
    {
        "modelo": "Jordan 4 Retro",
        "termino": "air jordan 4 retro",
        "filtro_modelo": es_jordan_4_retro,
        "tallas_objetivo": {"8.5", "9"},
    },
    {
        "modelo": "Puma 180 / 180 Pro",
        "termino": "puma 180",
        "filtro_modelo": es_puma_180,
        "tallas_objetivo": {"10"},
    },
    {
        "modelo": "Air Force 1 blancas",
        "termino": "air force 1",
        "filtro_modelo": es_air_force_1_blanca,
        "tallas_objetivo": {"8.5", "9"},
        # Casi siempre hay stock: avisar solo cuando esten en oferta.
        "solo_ofertas": True,
    },
    {
        # Para mujer, pero en escala unisex/hombre (como Bold: "US 4.5 UNSX");
        # por eso los modelos "mujer", que usan otra escala, quedan fuera.
        "modelo": "Puma Suede XL",
        "termino": "suede xl",
        "filtro_modelo": es_puma_suede_xl,
        "tallas_objetivo": {"4.5", "5"},
        "solo_ofertas": True,
    },
]

# Bold/Moredrops: "US 9 MEN" o, en modelos unisex, "US 4.5 UNSX" (misma escala).
FILTRO_TALLA_OCC = re.compile(r"US\s+([\d.]+)\s+(?:MEN|UNSX)\b", re.I)
MAX_PAGINAS = 8  # tope de paginas de 50 resultados por busqueda

CARPETA = Path(__file__).resolve().parent
ARCHIVO_ESTADO = CARPETA / "shozen_estado.json"
ARCHIVO_LOG = CARPETA / "shozen_log.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TIMEOUT = 20

ZONA_CL = ZoneInfo("America/Santiago")
HORA_INICIO = 8
HORA_FIN = 23

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_MAX = 3800  # el limite real es 4096; se deja margen

# =============================================================================


def dentro_de_horario():
    return HORA_INICIO <= datetime.now(ZONA_CL).hour < HORA_FIN


def limpiar_nombre(nombre):
    if not nombre:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", nombre)).strip()


def a_entero(valor):
    try:
        return int(round(float(valor))) if valor is not None else None
    except (TypeError, ValueError):
        return None


def fmt_clp(valor):
    return f"${valor:,.0f}".replace(",", ".") if valor else "?"


def es_de_hombre(nombre, genero=""):
    if genero and re.search(r"mujer|ni[ñn]|infantil|beb", genero, re.I):
        return False
    return not FILTRO_NO_HOMBRE.search(nombre or "")


def buscar_occ(termino, site_id, base_url, filtro_modelo, tallas_objetivo):
    """Bold y Moredrops (SAP Commerce / ynk.cl). Devuelve un item por
    colorway con sus tallas objetivo (stock + precio actual + precio normal)."""
    q = requests.utils.quote(termino)
    productos = []
    for pagina in range(MAX_PAGINAS):
        url = (
            f"https://api-prd.ynk.cl/rest/v2/{site_id}/products/search"
            f"?query={q}&pageSize=50&currentPage={pagina}&lang=es_CL&curr=CLP"
        )
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        datos = r.json()
        productos.extend(datos.get("products", []))
        total_paginas = (datos.get("pagination") or {}).get("totalPages") or 1
        if pagina + 1 >= total_paginas:
            break

    resultado = []
    vistos = set()
    for p in productos:
        nombre = limpiar_nombre(p.get("name"))
        code = p.get("code")
        if not code or code in vistos:
            continue
        vistos.add(code)
        if not (filtro_modelo(nombre, "") and es_de_hombre(nombre)):
            continue

        link = p.get("url") or ""
        if link.startswith("/"):
            link = base_url + link

        try:
            rd = requests.get(
                f"https://api-prd.ynk.cl/rest/v2/{site_id}/products/{code}?lang=es_CL&curr=CLP",
                headers=HEADERS, timeout=TIMEOUT,
            )
            rd.raise_for_status()
            detalle = rd.json()
        except Exception as e:
            # Sin detalle no se sabe el stock: se salta este producto y su
            # estado anterior queda tal cual.
            print(f"  detalle de {code} fallo: {e}")
            continue

        precio_prod = a_entero((p.get("price") or {}).get("value"))
        normal_prod = a_entero((p.get("regularPrice") or {}).get("value")) or precio_prod

        tallas = {}
        for v in detalle.get("variantOptions", []):
            qualifiers = v.get("variantOptionQualifiers") or []
            talla_valor = qualifiers[0].get("value") if qualifiers else ""
            m = FILTRO_TALLA_OCC.match(talla_valor or "")
            if not (m and m.group(1) in tallas_objetivo):
                continue
            precio = a_entero((v.get("priceData") or {}).get("value")) or precio_prod
            normal = a_entero((v.get("regularPrice") or {}).get("value")) or normal_prod or precio
            estado_stock = (v.get("stock") or {}).get("stockLevelStatus")
            tallas[m.group(1)] = {
                # "lowStock" (pocas unidades) tambien se puede comprar.
                "en_stock": estado_stock in ("inStock", "lowStock"),
                "precio": precio,
                "precio_normal": max(normal or 0, precio or 0) or None,
            }

        resultado.append({"codigo": code, "nombre": nombre, "link": link, "tallas": tallas})
    return resultado


def buscar_theline(termino, filtro_modelo, tallas_objetivo):
    """The Line (VTEX): cada talla viene como un 'item' con su propio stock."""
    productos = []
    for pagina in range(MAX_PAGINAS):
        desde = pagina * 50
        url = (
            "https://www.theline.cl/api/catalog_system/pub/products/search"
            f"?ft={requests.utils.quote(termino)}&_from={desde}&_to={desde + 49}"
        )
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code in (206, 200):
            lote = r.json()
        else:
            r.raise_for_status()
            lote = []
        productos.extend(lote)
        if len(lote) < 50:
            break

    resultado = []
    vistos = set()
    for p in productos:
        codigo = p.get("productId")
        if not codigo or codigo in vistos:
            continue
        vistos.add(codigo)
        nombre = limpiar_nombre(p.get("productName"))
        color = (p.get("COLOR") or [""])[0]
        genero = " ".join(p.get("GENERO") or []) + " " + " ".join(p.get("EDAD") or [])
        if not (filtro_modelo(nombre, color) and es_de_hombre(nombre, genero)):
            continue

        tallas = {}
        for item in p.get("items") or []:
            talla = (item.get("TALLA") or [""])[0]
            if talla not in tallas_objetivo:
                continue
            sellers = item.get("sellers") or []
            oferta = (sellers[0].get("commertialOffer") if sellers else None) or {}
            precio = a_entero(oferta.get("Price"))
            normal = a_entero(oferta.get("ListPrice")) or a_entero(oferta.get("PriceWithoutDiscount"))
            tallas[talla] = {
                "en_stock": (oferta.get("AvailableQuantity") or 0) > 0,
                "precio": precio,
                "precio_normal": max(normal or 0, precio or 0) or None,
            }

        resultado.append({"codigo": codigo, "nombre": nombre, "link": p.get("link"), "tallas": tallas})
    return resultado


TIENDAS = [
    ("Bold", lambda t, f, ta: buscar_occ(t, "boldb2cstore", "https://www.bold.cl", f, ta)),
    ("Moredrops", lambda t, f, ta: buscar_occ(t, "dropsb2cstore", "https://www.moredrops.cl", f, ta)),
    ("The Line", lambda t, f, ta: buscar_theline(t, f, ta)),
]


def en_oferta(info):
    return bool(info.get("precio") and info.get("precio_normal") and info["precio"] < info["precio_normal"])


def cargar_estado():
    """Devuelve {clave 'tienda|codigo|talla': {en_stock, precio, precio_normal}}.
    Acepta el formato viejo (precios como texto "$94.990", claves sin talla)."""
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        return {}
    productos = datos.get("productos", datos) if isinstance(datos, dict) else {}
    estado = {}
    for clave, info in productos.items():
        if clave.count("|") != 2 or not isinstance(info, dict):
            continue  # claves antiguas sin talla: ya no sirven
        precio = info.get("precio")
        if isinstance(precio, str):
            precio = a_entero(re.sub(r"[^\d]", "", precio) or None)
        estado[clave] = {
            "en_stock": bool(info.get("en_stock")),
            "precio": precio,
            "precio_normal": info.get("precio_normal"),
            "precio_avisado": info.get("precio_avisado"),
        }
    return estado


def guardar_estado(productos):
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "productos": productos}, f, ensure_ascii=False, indent=2, sort_keys=True)


def notificar_telegram(mensajes):
    """Envia los mensajes (texto HTML). Devuelve False si alguno fallo."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Telegram] faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, no se aviso.")
        return True
    todo_ok = True
    for texto in mensajes:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"  [Telegram] error HTTP {r.status_code}: {r.text[:300]}")
                todo_ok = False
        except Exception as e:
            print(f"  [Telegram] error enviando notificacion: {e}")
            todo_ok = False
    return todo_ok


def registrar_log(lineas):
    marca = datetime.now(ZONA_CL).strftime("%Y-%m-%d %H:%M:%S")
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        for linea in lineas:
            f.write(f"[{marca}] {linea}\n")


def armar_mensajes(eventos):
    """Agrupa los eventos en mensajes de Telegram que no pasen el limite."""
    bloques = []
    for ev in eventos:
        e = html.escape
        tallas = ", ".join(
            f"{t} ({fmt_clp(i['precio'])})" for t, i in sorted(ev["tallas"].items(), key=lambda x: float(x[0]))
        )
        precio_txt = fmt_clp(ev["precio"])
        if ev["oferta"]:
            dcto = round(100 * (1 - ev["precio"] / ev["precio_normal"]))
            precio_txt = f"<b>{fmt_clp(ev['precio'])}</b> (antes {fmt_clp(ev['precio_normal'])}, -{dcto}%)"
        bloques.append(
            f"<b>{e(ev['tipo'])} · {e(ev['tienda'])}</b>\n"
            f"{e(ev['nombre'])}\n"
            f"Tallas US {e(tallas)}\n"
            f"{precio_txt}\n"
            f"{e(ev['link'] or '')}"
        )

    titulo = f"👟 <b>SHOZEN — {len(eventos)} aviso(s)</b>"
    mensajes, actual = [], titulo
    for b in bloques:
        if len(actual) + len(b) + 2 > TELEGRAM_MAX:
            mensajes.append(actual)
            actual = b
        else:
            actual += "\n\n" + b
    mensajes.append(actual)
    return mensajes


def main():
    if not dentro_de_horario():
        print(f"Fuera del horario {HORA_INICIO}:00-{HORA_FIN}:00 (hora de Chile), no se revisa esta vez.")
        return 0

    estado = cargar_estado()
    nuevo_estado = dict(estado)
    eventos = []
    busquedas_ok = busquedas_error = 0

    for config in CONFIGURACION_BUSQUEDA:
        for nombre_tienda, buscador in TIENDAS:
            try:
                productos = buscador(config["termino"], config["filtro_modelo"], config["tallas_objetivo"])
                busquedas_ok += 1
            except Exception as e:
                busquedas_error += 1
                print(f"[{nombre_tienda}] error buscando '{config['termino']}': {e}")
                continue

            for p in productos:
                tallas_aviso = {}
                tipos = set()
                for talla in config["tallas_objetivo"]:
                    clave = f"{nombre_tienda}|{p['codigo']}|{talla}"
                    # Talla que ya no aparece en el producto = agotada.
                    info = p["tallas"].get(talla) or {"en_stock": False, "precio": None, "precio_normal": None}
                    anterior = estado.get(clave)
                    # "precio_avisado" = ultimo precio de oferta que se aviso.
                    # Se compara contra ese (no contra el ultimo visto) para no
                    # avisar de nuevo si la oferta sube y luego baja un poco.
                    # Se borra cuando la talla sale de oferta o se agota, asi
                    # una oferta que vuelve despues se avisa otra vez.
                    avisado = (anterior or {}).get("precio_avisado")
                    if not (info["en_stock"] and en_oferta(info)):
                        avisado = None
                    info = dict(info, precio_avisado=avisado)
                    nuevo_estado[clave] = info
                    if not info["en_stock"]:
                        continue

                    estaba_disponible = bool(anterior and anterior["en_stock"])
                    if config.get("solo_ofertas") and not en_oferta(info):
                        continue
                    if not estaba_disponible:
                        tipos.add("DISPONIBLE")
                    elif en_oferta(info) and (avisado is None or info["precio"] < avisado):
                        tipos.add("OFERTA")
                    else:
                        continue
                    tallas_aviso[talla] = info
                    if en_oferta(info):
                        info["precio_avisado"] = info["precio"]

                if tallas_aviso:
                    ref = min(tallas_aviso.values(), key=lambda i: i["precio"] or 10**9)
                    oferta = en_oferta(ref)
                    tipo = "DISPONIBLE" if "DISPONIBLE" in tipos else "OFERTA"
                    if tipo == "DISPONIBLE" and oferta:
                        tipo = "DISPONIBLE EN OFERTA"
                    eventos.append({
                        "tipo": tipo,
                        "tienda": nombre_tienda,
                        "modelo": config["modelo"],
                        "nombre": p["nombre"],
                        "link": p["link"],
                        "tallas": tallas_aviso,
                        "precio": ref["precio"],
                        "precio_normal": ref["precio_normal"],
                        "oferta": oferta,
                    })

    if busquedas_ok == 0:
        print("Todas las busquedas fallaron: no se guarda nada en esta corrida.")
        return 1

    # Ofertas primero, despues el resto.
    eventos.sort(key=lambda ev: (not ev["oferta"], ev["modelo"], ev["tienda"]))

    if eventos:
        lineas_log = []
        for ev in eventos:
            tallas = ", ".join(sorted(ev["tallas"], key=float))
            extra = f" (antes {fmt_clp(ev['precio_normal'])})" if ev["oferta"] else ""
            lineas_log.append(
                f"{ev['tipo']} [{ev['tienda']}] {ev['nombre']} | tallas {tallas} | "
                f"{fmt_clp(ev['precio'])}{extra} | {ev['link']}"
            )
        for linea in lineas_log:
            print(linea)

        if not notificar_telegram(armar_mensajes(eventos)):
            print("No se pudo avisar por Telegram: no se guarda el estado para reintentar en la proxima corrida.")
            return 1
        registrar_log(lineas_log)
    else:
        print("Sin novedades en esta corrida.")

    guardar_estado(nuevo_estado)
    if busquedas_error:
        print(f"Aviso: {busquedas_error} busqueda(s) fallaron en esta corrida (ver arriba).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
