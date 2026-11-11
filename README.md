# SHOZEN

Revisa Bold, Moredrops y The Line buscando stock y ofertas de los modelos en
`CONFIGURACION_BUSQUEDA` (dentro de `shozen.py`) y avisa por
Telegram. Corre en GitHub Actions cada 5 minutos entre 8:00 y 22:55 (hora
de Chile), activado por [cron-job.org](https://cron-job.org), sin depender de
que ningun PC este prendido (ver "Cuando corre").

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

| Producto | Solotodo | Avisa cuando una tienda lo tiene a |
| --- | --- | --- |
| AirPods Pro 3 | 355272 | menos de $299.990 (precio Apple) |
| AirPods 5 (estuche USB-C) | 406262 | menos de $159.990 (precio Apple) |
| AirPods 5 (carga inalambrica) | 406261 | menos de $179.990 (precio Apple) |

Siempre se compara el precio normal, sin tarjeta de la tienda, contra
`precio_referencia` (el precio oficial de Apple Chile) en `PRODUCTOS_SOLOTODO`,
dentro de `shozen.py`. El aviso muestra el % de descuento y, si existe, el
precio con tarjeta de la tienda. Avisa de nuevo si el precio baja mas. Si un
producto sale de oferta y vuelve al mismo precio dentro de 24 horas, no
repite el aviso (`MEMORIA_AVISO`).

Opcional, `filtro_nombre`: ignora publicaciones cuyo nombre no calce. Lo usa
la version inalambrica de AirPods 5 porque Solotodo mezcla ahi publicaciones
de la version normal, que darian ofertas falsas.

## Configuracion inicial (una sola vez)

1. En este repo, ve a **Settings > Secrets and variables > Actions > New
   repository secret** y agrega:
   - `TELEGRAM_BOT_TOKEN`: el token que te dio @BotFather.
   - `TELEGRAM_CHAT_ID`: el id del chat donde quieres recibir los avisos.

2. Verifica que las Actions esten habilitadas: pestaña **Actions** del repo.

3. (Opcional) Corre el workflow a mano una vez para probar: pestaña
   **Actions > SHOZEN > Run workflow**.

4. Configura cron-job.org (ver "Cuando corre").

## Cuando corre

El workflow (`.github/workflows/shozen.yml`) **no tiene horario propio**: solo
se ejecuta con `workflow_dispatch`. Antes usaba `schedule` de GitHub Actions,
pero GitHub se saltaba ejecuciones y pasaban horas sin correr.

Ahora lo activa una tarea en cron-job.org:

- **URL:** `https://api.github.com/repos/maxiskjd/SHOZEN/actions/workflows/shozen.yml/dispatches`
- **Horario:** cada 5 minutos, de las 8 a las 22, zona horaria
  `America/Santiago` (sigue solo el cambio de horario de verano).
- **Metodo:** `POST`, con body `{"ref":"main"}`.
- **Headers:**
  - `Authorization: Bearer <token>`
  - `Accept: application/vnd.github+json`
  - `X-GitHub-Api-Version: 2022-11-28`
- Una prueba correcta responde **204**. Un 401 es token mal puesto; un 404,
  token sin acceso al repo o sin permiso de Actions.

El token es un fine-grained personal access token de GitHub con acceso solo a
este repo y el permiso **Actions: Read and write** (nada mas). Vence al año:
cuando venza el bot deja de correr; hay que regenerarlo en
https://github.com/settings/personal-access-tokens y pegar el nuevo en
cron-job.org. Nunca lo subas a este repo.

El script igual revisa la hora de Chile y no hace nada fuera de 8:00-23:00,
asi que una corrida a mano fuera de horario no avisa.

Costo: el repo es publico, asi que GitHub Actions no tiene limite de minutos
(siendo privado eran 2.000 min/mes y no alcanzaba para correr cada 5 min).
No conviene bajar de ~2 minutos: las tiendas podrian bloquear al bot.

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
