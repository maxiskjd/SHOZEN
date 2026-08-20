"""
Vigia de restocks / lanzamientos nuevos para modelos Jordan en Bold, Moredrops
y The Line.

Pensado para correr seguido (cada 1-2 min) via GitHub Actions (o el
Programador de tareas de Windows si se corre local): cada corrida es
independiente, compara contra el estado guardado en ARCHIVO_ESTADO y solo
avisa por Telegram cuando hay algo NUEVO (producto que no se habia visto
antes) o un RESTOCK (un producto que antes estaba agotado y ahora tiene
stock). Fuera del horario 8:00-23:00 (hora de Chile) no revisa nada, para
no generar trafico de madrugada.

Uso manual: python vigia_jordan_bold.py
Requiere las variables de entorno TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
para poder avisar (si no estan, igual revisa y deja el log, pero no notifica).
"""

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ============================== CONFIGURACION ==============================

# Terminos de busqueda a vigilar. Agrega mas lineas para otros modelos.
TERMINOS_BUSQUEDA = [
    "air jordan 4 retro", "air force 1"
]

CARPETA = Path(__file__).resolve().parent
ARCHIVO_ESTADO = CARPETA / "vigia_jordan_estado.json"
ARCHIVO_LOG = CARPETA / "vigia_jordan_log.txt"

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

# =============================================================================


def dentro_de_horario():
    ahora = datetime.now(ZONA_CL)
    return HORA_INICIO <= ahora.hour < HORA_FIN


def limpiar_nombre(nombre):
    if not nombre:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", nombre)).strip()


def buscar_occ(termino, site_id, base_url):
    """Bold y Moredrops corren la misma plataforma (SAP Commerce / ynk.cl)."""
    q = requests.utils.quote(termino)
    url = (
        f"https://api-prd.ynk.cl/rest/v2/{site_id}/products/search"
        f"?query={q}&pageSize=50&lang=es_CL&curr=CLP"
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    productos = r.json().get("products", [])
    resultado = []
    for p in productos:
        link = p.get("url") or ""
        if link.startswith("/"):
            link = base_url + link
        resultado.append({
            "sku": p.get("code"),
            "nombre": limpiar_nombre(p.get("name")),
            "en_stock": (p.get("stock") or {}).get("stockLevelStatus") == "inStock",
            "precio": (p.get("price") or {}).get("formattedValue"),
            "link": link,
        })
    return resultado


def buscar_theline(termino):
    url = (
        "https://www.theline.cl/api/catalog_system/pub/products/search"
        f"?ft={requests.utils.quote(termino)}&_from=0&_to=49"
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    productos = r.json()
    resultado = []
    for p in productos:
        items = p.get("items") or []
        if not items:
            continue
        item = items[0]
        sellers = item.get("sellers") or []
        oferta = sellers[0].get("commertialOffer") if sellers else {}
        precio = oferta.get("Price")
        resultado.append({
            "sku": item.get("itemId") or p.get("productId"),
            "nombre": limpiar_nombre(p.get("productName")),
            "en_stock": (oferta.get("AvailableQuantity") or 0) > 0,
            "precio": f"${precio:,.0f}".replace(",", ".") if precio else None,
            "link": p.get("link"),
        })
    return resultado


TIENDAS = [
    ("Bold", lambda t: buscar_occ(t, "boldb2cstore", "https://www.bold.cl")),
    ("Moredrops", lambda t: buscar_occ(t, "dropsb2cstore", "https://www.moredrops.cl")),
    ("The Line", buscar_theline),
]


def cargar_estado():
    try:
        with open(ARCHIVO_ESTADO, "r", encoding="utf-8") as f:
            datos = json.load(f)
    except FileNotFoundError:
        return {"terminos_conocidos": [], "productos": {}}

    if "productos" in datos and "terminos_conocidos" in datos:
        return datos

    # Formato viejo (antes de agregar seguimiento por termino): todo lo que
    # habia ahi se guardo cuando el unico termino era el de Jordan.
    return {"terminos_conocidos": ["air jordan 4 retro"], "productos": datos}


def guardar_estado(estado):
    with open(ARCHIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def notificar_telegram(titulo, mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [Telegram] faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, no se pudo avisar.")
        return
    texto = f"*{titulo}*\n{mensaje}"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "Markdown"},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  [Telegram] error HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  [Telegram] error enviando notificacion: {e}")


def registrar_log(lineas):
    with open(ARCHIVO_LOG, "a", encoding="utf-8") as f:
        from datetime import datetime
        marca = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for linea in lineas:
            f.write(f"[{marca}] {linea}\n")


def main():
    if not dentro_de_horario():
        print(f"Fuera del horario {HORA_INICIO}:00-{HORA_FIN}:00 (hora de Chile), no se revisa esta vez.")
        return

    estado = cargar_estado()
    productos_estado = estado["productos"]
    terminos_conocidos = set(estado["terminos_conocidos"])
    terminos_nuevos_bautizados = []
    nuevos = []
    restocks = []

    for termino in TERMINOS_BUSQUEDA:
        es_termino_nuevo = termino not in terminos_conocidos
        for nombre_tienda, buscador in TIENDAS:
            try:
                productos = buscador(termino)
            except Exception as e:
                print(f"[{nombre_tienda}] error buscando '{termino}': {e}")
                continue

            for p in productos:
                if not p["sku"]:
                    continue
                clave = f"{nombre_tienda}|{p['sku']}"
                anterior = productos_estado.get(clave)

                if not es_termino_nuevo:
                    if anterior is None:
                        if p["en_stock"]:
                            nuevos.append((nombre_tienda, p))
                    elif anterior["en_stock"] is False and p["en_stock"] is True:
                        restocks.append((nombre_tienda, p))

                productos_estado[clave] = {
                    "en_stock": p["en_stock"],
                    "nombre": p["nombre"],
                    "precio": p["precio"],
                }

        if es_termino_nuevo:
            terminos_conocidos.add(termino)
            terminos_nuevos_bautizados.append(termino)

    estado["productos"] = productos_estado
    estado["terminos_conocidos"] = sorted(terminos_conocidos)
    guardar_estado(estado)

    if terminos_nuevos_bautizados:
        print("Termino(s) nuevo(s) agregados a TERMINOS_BUSQUEDA, se guardo su estado "
              f"inicial sin avisar nada (recien empieza el seguimiento): {terminos_nuevos_bautizados}")
        if not (TERMINOS_BUSQUEDA and set(TERMINOS_BUSQUEDA) - set(terminos_nuevos_bautizados)):
            return

    lineas_log = []
    for tienda, p in nuevos:
        lineas_log.append(f"NUEVO  [{tienda}] {p['nombre']} | {p['precio']} | {p['link']}")
    for tienda, p in restocks:
        lineas_log.append(f"RESTOCK [{tienda}] {p['nombre']} | {p['precio']} | {p['link']}")

    if lineas_log:
        registrar_log(lineas_log)
        for linea in lineas_log:
            print(linea)

        eventos = [("RESTOCK", t, p) for t, p in restocks] + [("NUEVO", t, p) for t, p in nuevos]
        cuerpo = "\n\n".join(
            f"{etiqueta} · {tienda}\n{p['nombre']}\n{p['precio']}\n{p['link']}"
            for etiqueta, tienda, p in eventos[:10]
        )
        if len(eventos) > 10:
            cuerpo += f"\n\n(+{len(eventos) - 10} mas, revisa el log)"
        notificar_telegram(f"👟 Vigia Jordan/Bold — {len(eventos)} novedad(es)", cuerpo)
    else:
        print("Sin novedades en esta corrida.")


if __name__ == "__main__":
    main()
