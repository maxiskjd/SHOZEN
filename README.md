# SHOZEN

Revisa Bold, Moredrops y The Line buscando stock y ofertas de los modelos en
`CONFIGURACION_BUSQUEDA` (dentro de `shozen.py`) y avisa por
Telegram. Corre en GitHub Actions entre 8:00 y 23:00 (hora de Chile), sin
depender de que ningun PC este prendido.

Modelos vigilados (productos de hombre o unisex, tallas US de hombre):

| Modelo | Tallas |
| --- | --- |
| Jordan 4 Retro | 8.5, 9 |
| Puma 180 / 180 Pro | 10 |
| Air Force 1 blancas (solo ofertas) | 8.5, 9 |
| Puma Suede XL, para mujer en escala unisex (solo ofertas) | 4.5, 5 |

Productos sin talla, seguidos en [Solotodo](https://www.solotodo.cl) (comparador
que revisa unas 12 tiendas: Ripley, Falabella, Paris, Lider, Mercado Libre,
MacOnline, etc.; las grandes cada ~30 min, las chicas ~1 vez al dia):

| Producto | Avisa cuando una tienda lo tiene a |
| --- | --- |
| AirPods Pro 3 | $229.990 o menos (precio normal, sin tarjeta de la tienda) |

El tope se cambia en `PRODUCTOS_SOLOTODO` dentro de `shozen.py`.

## Configuracion inicial (una sola vez)

1. En este repo, ve a **Settings > Secrets and variables > Actions > New
   repository secret** y agrega:
   - `TELEGRAM_BOT_TOKEN`: el token que te dio @BotFather.
   - `TELEGRAM_CHAT_ID`: el id del chat donde quieres recibir los avisos.

2. Verifica que las Actions esten habilitadas: pestaña **Actions** del repo.

3. (Opcional) Corre el workflow a mano una vez para probar: pestaña
   **Actions > SHOZEN > Run workflow**.

## Como funciona

- Cada corrida es independiente; el estado (stock y precio de cada talla
  objetivo) se guarda en `shozen_estado.json` y el propio workflow lo
  commitea de vuelta al repo al final de cada corrida.
- Avisa por Telegram solo sobre las tallas objetivo:
  - **DISPONIBLE**: la talla paso de agotada (o nunca vista) a tener stock
    (salvo en modelos con `"solo_ofertas": True`, como las Air Force 1).
  - **OFERTA**: la talla tiene stock y entro en descuento, o el precio de
    oferta bajo mas desde el ultimo aviso.
- Si Telegram rechaza el aviso, la corrida queda en rojo (GitHub te manda
  correo) y el estado no se guarda, asi la siguiente corrida reintenta.

## Agregar mas modelos a vigilar

Agrega una entrada a `CONFIGURACION_BUSQUEDA` en `shozen.py` (termino
de busqueda, filtro sobre el nombre y tallas), haz commit y push. La primera
corrida avisa de todo lo que ya este disponible en esas tallas.
