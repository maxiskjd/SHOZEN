# Vigia Jordan/Bold

Revisa Bold, Moredrops y The Line buscando restocks o lanzamientos nuevos de
los modelos en `TERMINOS_BUSQUEDA` (dentro de `vigia_jordan_bold.py`), y
avisa por Telegram. Corre en GitHub Actions cada 15 min entre 8:00 y 23:00
(hora de Chile), sin depender de que ningun PC este prendido.

## Configuracion inicial (una sola vez)

1. En este repo, ve a **Settings > Secrets and variables > Actions > New
   repository secret** y agrega:
   - `TELEGRAM_BOT_TOKEN`: el token que te dio @BotFather.
   - `TELEGRAM_CHAT_ID`: el id del chat donde quieres recibir los avisos.

2. Verifica que las Actions esten habilitadas: pestaña **Actions** del repo.

3. (Opcional) Corre el workflow a mano una vez para probar: pestaña
   **Actions > Vigia Jordan/Bold > Run workflow**.

## Como funciona

- Cada corrida es independiente; el estado (que productos ya se vieron y en
  que stock estaban) se guarda en `vigia_jordan_estado.json` y el propio
  workflow lo commitea de vuelta al repo al final de cada corrida.
- La primera vez que corre (o cuando agregas un termino nuevo a
  `TERMINOS_BUSQUEDA`), no avisa nada — solo guarda la foto inicial, para no
  spamear con productos que "ya estaban ahi".
- Despues de eso, avisa por Telegram solo cuando aparece un producto **nuevo**
  (nunca visto) que esta en stock, o un **restock** (paso de agotado a
  disponible).

## Agregar mas modelos a vigilar

Edita `TERMINOS_BUSQUEDA` en `vigia_jordan_bold.py`, haz commit y push. La
proxima corrida "bautiza" el termino nuevo en silencio y desde la que sigue
ya avisa normal.
