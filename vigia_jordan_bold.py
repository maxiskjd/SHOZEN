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
    "air jordan 4 retro",
]

# Los buscadores de cada tienda hacen matching bastante suelto (ej. "air
# jordan 4 retro" tambien trae Jordan 1, Jordan 3, Air Force, etc). Este
# filtro se aplica sobre el nombre real del producto y solo deja pasar los
# que de verdad son Retro 4 (tienen un "4" como numero de modelo Y la
# palabra "retro" en el nombre - asi excluye la linea "4 RM", que es un
# modelo distinto aunque comparta el numero).
FILTRO_MODELO = re.compile(r"\b4\b", re.I)
FILTRO_RETRO = re.compile(r"\bretro\b", re.I)


def es_retro_4(nombre):
    nombre = nombre or ""
    return bool(FILTRO_MODELO.search(nombre) and FILTRO_RETRO.search(nombre))


# Solo interesan estas tallas (formato numerico plano, ej. "8.5", "9")
TALLAS_OBJETIVO = {"8.5", "9"}
FILTRO_TALLA_OCC = re.compile(r"US\s+([\d.]+)\s+MEN", re.I)

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
    """Bold y Moredrops corren la misma plataforma (SAP Commerce / ynk.cl).
    Devuelve un item por CADA COLORWAY (no por talla), con la lista de
    tallas 8.5/9 y su stock adentro - asi se puede avisar de un colorway
    nuevo sin importar si esas tallas puntuales tienen stock o no."""
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
        nombre = limpiar_nombre(p.get("name"))
        code = p.get("code")
        if not code or not es_retro_4(nombre):
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
        except Exception:
            continue

        tallas = []
        for v in detalle.get("variantOptions", []):
            qualifiers = v.get("variantOptionQualifiers") or []
            talla_valor = qualifiers[0].get("value") if qualifiers else ""
            m = FILTRO_TALLA_OCC.match(talla_valor or "")
            if not (m and m.group(1) in TALLAS_OBJETIVO):
                continue
            tallas.append({
                "talla": m.group(1),
                "en_stock": (v.get("stock") or {}).get("stockLevelStatus") == "inStock",
                "precio": (v.get("priceData") or {}).get("formattedValue")
                or (p.get("price") or {}).get("formattedValue"),
            })

        resultado.append({
            "codigo": code,
            "nombre": nombre,
            "link": link,
            "precio_base": (p.get("price") or {}).get("formattedValue"),
            "tallas": tallas,
        })
    return resultado


def buscar_theline(termino):
    """VTEX ya trae cada talla como un 'item' separado con su propio stock,
    asi que se filtra directo sin llamadas extra. Se agrupa por producto
    (no por talla) por el mismo motivo que en buscar_occ."""
    url = (
        "https://www.theline.cl/api/catalog_system/pub/products/search"
        f"?ft={requests.utils.quote(termino)}&_from=0&_to=49"
    )
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    productos = r.json()
    resultado = []
    for p in productos:
        nombre_producto = limpiar_nombre(p.get("productName"))
        if not es_retro_4(nombre_producto):
            continue

        tallas = []
        precio_base = None
        for item in p.get("items") or []:
            valores_talla = item.get("TALLA") or []
            talla = valores_talla[0] if valores_talla else ""
            sellers = item.get("sellers") or []
            oferta = sellers[0].get("commertialOffer") if sellers else {}
            precio = oferta.get("Price")
            precio_fmt = f"${precio:,.0f}".replace(",", ".") if precio else None
            if precio_base is None:
                precio_base = precio_fmt
            if talla not in TALLAS_OBJETIVO:
                continue
            tallas.append({
                "talla": talla,
                "en_stock": (oferta.get("AvailableQuantity") or 0) > 0,
                "precio": precio_fmt,
            })

        resultado.append({
            "codigo": p.get("productId"),
            "nombre": nombre_producto,
            "link": p.get("link"),
            "precio_base": precio_base,
            "tallas": tallas,
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
        return {"terminos_conocidos": [], "estilos_conocidos": [], "productos": {}}

    if "productos" in datos and "terminos_conocidos" in datos:
        datos.setdefault("estilos_conocidos", [])
        return datos

    # Formato viejo (antes de agregar seguimiento por termino): todo lo que
    # habia ahi se guardo cuando el unico termino era el de Jordan.
    return {"terminos_conocidos": ["air jordan 4 retro"], "estilos_conocidos": [], "productos": datos}


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
    estilos_conocidos = set(estado["estilos_conocidos"])
    # "estilos_conocidos" es un campo nuevo: si viene vacio pero ya habia
    # productos guardados de antes, es una migracion (no un primer arranque
    # real) - hay que bautizar los estilos en silencio esta vez para no
    # disparar un "NUEVO" falso por cada colorway que ya conociamos.
    es_primera_vez_estilos = not estilos_conocidos and bool(productos_estado)
    terminos_conocidos = set(estado["terminos_conocidos"])
    terminos_nuevos_bautizados = []
    nuevos = []      # colorways nunca vistos - avisa sin importar la talla
    restocks = []    # talla 8.5/9 que paso de agotada a disponible, en colorways YA conocidos

    for termino in TERMINOS_BUSQUEDA:
        es_termino_nuevo = termino not in terminos_conocidos
        for nombre_tienda, buscador in TIENDAS:
            try:
                productos = buscador(termino)
            except Exception as e:
                print(f"[{nombre_tienda}] error buscando '{termino}': {e}")
                continue

            for p in productos:
                if not p["codigo"]:
                    continue
                clave_estilo = f"{nombre_tienda}|{p['codigo']}"
                estilo_es_nuevo = clave_estilo not in estilos_conocidos

                if not es_termino_nuevo and estilo_es_nuevo and not es_primera_vez_estilos:
                    tallas_disponibles = [t["talla"] for t in p["tallas"] if t["en_stock"]]
                    nuevos.append((nombre_tienda, {
                        "nombre": p["nombre"],
                        "link": p["link"],
                        "precio": p["precio_base"],
                        "tallas_disponibles": tallas_disponibles,
                    }))
                estilos_conocidos.add(clave_estilo)

                for t in p["tallas"]:
                    clave = f"{nombre_tienda}|{p['codigo']}|{t['talla']}"
                    anterior = productos_estado.get(clave)

                    if not es_termino_nuevo and not estilo_es_nuevo:
                        if anterior is not None and anterior["en_stock"] is False and t["en_stock"] is True:
                            restocks.append((nombre_tienda, {
                                "nombre": f"{p['nombre']} (talla {t['talla']})",
                                "link": p["link"],
                                "precio": t["precio"],
                            }))

                    productos_estado[clave] = {"en_stock": t["en_stock"], "precio": t["precio"]}

        if es_termino_nuevo:
            terminos_conocidos.add(termino)
            terminos_nuevos_bautizados.append(termino)

    estado["productos"] = productos_estado
    estado["estilos_conocidos"] = sorted(estilos_conocidos)
    estado["terminos_conocidos"] = sorted(terminos_conocidos)
    guardar_estado(estado)

    if es_primera_vez_estilos:
        print(f"Migracion: se bautizaron {len(estilos_conocidos)} colorways ya conocidos en silencio "
              "(no se avisa 'NUEVO' de ninguno esta vez).")

    if terminos_nuevos_bautizados:
        print("Termino(s) nuevo(s) agregados a TERMINOS_BUSQUEDA, se guardo su estado "
              f"inicial sin avisar nada (recien empieza el seguimiento): {terminos_nuevos_bautizados}")
        if not (TERMINOS_BUSQUEDA and set(TERMINOS_BUSQUEDA) - set(terminos_nuevos_bautizados)):
            return

    lineas_log = []
    for tienda, p in nuevos:
        tallas_txt = ", ".join(p["tallas_disponibles"]) if p["tallas_disponibles"] else "sin stock en 8.5/9 por ahora"
        lineas_log.append(f"NUEVO  [{tienda}] {p['nombre']} | {p['precio']} | tallas 8.5/9: {tallas_txt} | {p['link']}")
    for tienda, p in restocks:
        lineas_log.append(f"RESTOCK [{tienda}] {p['nombre']} | {p['precio']} | {p['link']}")

    if lineas_log:
        registrar_log(lineas_log)
        for linea in lineas_log:
            print(linea)

        cuerpos = []
        for tienda, p in restocks:
            cuerpos.append(f"RESTOCK · {tienda}\n{p['nombre']}\n{p['precio']}\n{p['link']}")
        for tienda, p in nuevos:
            tallas_txt = ", ".join(p["tallas_disponibles"]) if p["tallas_disponibles"] else "sin stock en 8.5/9 por ahora (revisa otras tallas)"
            cuerpos.append(f"NUEVO COLORWAY · {tienda}\n{p['nombre']}\nTallas 8.5/9: {tallas_txt}\n{p['precio']}\n{p['link']}")

        total_eventos = len(restocks) + len(nuevos)
        cuerpo = "\n\n".join(cuerpos[:10])
        if total_eventos > 10:
            cuerpo += f"\n\n(+{total_eventos - 10} mas, revisa el log)"
        notificar_telegram(f"👟 Vigia Jordan/Bold — {total_eventos} novedad(es)", cuerpo)
    else:
        print("Sin novedades en esta corrida.")


if __name__ == "__main__":
    main()
