# build-hotspots

Preproceso reproducible del reto **Harmonization of MODIS and VIIRS Hot Spots**. Lee las
detecciones de fuego activo de NASA FIRMS, las filtra, calibra VIIRS respecto a MODIS y escribe
los agregados mensuales por celda que lee la web. La web no armoniza nada: solo suma celdas.

## Uso

Desde la raíz del repo:

```bash
uv run --project tools/build-hotspots build-hotspots \
  --in data/raw --out frontend/public/data --interim data/interim
```

| Argumento                     | Por defecto     | Qué hace                                                |
| ----------------------------- | --------------- | ------------------------------------------------------- |
| `--in`                        | (obligatorio)   | Carpeta con los JSON de FIRMS (se busca en subcarpetas) |
| `--out`                       | (obligatorio)   | Carpeta de los agregados publicados                     |
| `--bbox OESTE SUR ESTE NORTE` | España completa | Área en grados                                          |
| `--cell-deg` / `--cell-km`    | `0.05` (~5 km)  | Lado de la celda                                        |
| `--types`                     | `0`             | Tipos FIRMS que cuentan (0 vegetación, 1 volcán, 2, 3)  |
| `--modis-min-confidence`      | `30`            | Confianza mínima de MODIS (0-100)                       |
| `--keep-viirs-low`            | no              | Conserva las detecciones VIIRS de confianza `l`         |
| `--recent-days`               | `90`            | Días de detecciones individuales para la capa del mapa  |
| `--interim`                   | no se escribe   | Carpeta para la tabla normalizada en Parquet            |
| `--seed`                      | `20261114`      | Semilla del intervalo bootstrap de los factores         |

Con `--regions data/raw/limites` genera además `incidents-v1.json`: los incendios de los últimos
90 días por comunidad autónoma (ver «Incendios»). Los límites (`spain-communities.geojson` y
`spain-provinces.geojson`, de [click_that_hood](https://github.com/codeforamerica/click_that_hood))
se descargan a `data/raw/limites/`, que no se versiona; en la web solo aparecen los nombres.

Pruebas y lint: `uv run pytest` y `uv run ruff check .` dentro de `tools/build-hotspots/`.

## Datos de entrada

Descarga de archivo de [FIRMS](https://firms.modaps.eosdis.nasa.gov/download/) en JSON, de
**MODIS Collection 6.1** y **VIIRS S-NPP 375 m Collection 2**, con sus ficheros `fire_archive_*`
(procesado estándar) y `fire_nrt_*` (casi tiempo real). Van en `data/raw/`, que **no se
versiona**: el de VIIRS pasa de 100 MB. El sensor y la calidad se leen de los campos
`instrument` y `version` de cada registro, no del nombre del fichero.

Para ampliar la serie (por ejemplo, MODIS 2000-2011) basta con añadir los JSON a `data/raw/` y
volver a ejecutar: el año inicial sale de los datos y la web lo lee del manifiesto.

## Qué hace, en orden

1. **Valida** cada registro (campos, rango de coordenadas, fecha ISO, hora, confianza, FRP).
2. **Recorta** al área.
3. **Quita duplicados** exactos (misma posición, fecha, hora y satélite).
4. **Empalma archivo y NRT**: el NRT solo cuenta desde el día siguiente al último del archivo
   de su sensor. Los meses con NRT quedan marcados como **provisionales**.
5. **Filtra por tipo**. El NRT no trae `type`, así que se descartan sus detecciones en los
   puntos (0,01°) donde el archivo ya registró 3 o más detecciones de tipos excluidos.
6. **Filtra por confianza** con una regla común: MODIS < 30 y VIIRS `l` son "baja" en FIRMS.
7. **Agrega** por celda, mes y sensor (conteo y suma de FRP).
8. **Calibra y armoniza** (ver abajo).
9. **Escribe** el manifiesto, los binarios por año y las detecciones recientes.

Cada descarte queda contado por paso y sensor en la salida y en `registros.detalle` del
manifiesto.

## Método de armonización

VIIRS (375 m) detecta unas 3,3 veces más puntos calientes que MODIS (1 km) sobre los mismos
incendios, así que los conteos no se pueden sumar. Se usa un **estimador de razón por mes del
año**:

- Con los meses completos en que ambos sensores funcionan y el dato es estándar, se calcula
  `k = Σ MODIS / Σ VIIRS` sobre toda el área para cada mes del año (12 factores).
- El conteo armonizado se expresa en **detecciones equivalentes MODIS**:
  solo MODIS → `M`; solo VIIRS → `k·V`; ambos → `(M + k·V) / 2`.

Por qué así:

- **Estacional y no único**: la proporción de fuegos pequeños, que solo ve VIIRS, cambia entre
  el invierno (quemas agrícolas) y el verano (grandes incendios).
- **Sobre toda el área y no por celda**: a 5 km casi todas las celdas tienen muy pocas
  detecciones al mes y una razón local sería ruido.
- **Equivalentes MODIS**: MODIS es la serie larga (desde 2000); VIIRS es la que continúa.
- Un mes del año con menos de 100 detecciones VIIRS de calibración usa el factor global.

El manifiesto incluye el intervalo del 95 % de cada factor (bootstrap remuestreando años, con
semilla fija) y un diagnóstico: correlación mensual entre MODIS y `k·VIIRS`, error relativo
mediano y la razón de cada año.

### Limitaciones

- Resolución (1 km frente a 375 m) y horas de paso distintas: un fuego corto puede verlo solo
  uno de los dos.
- El factor es una media del área; en una zona concreta la razón real puede diferir.
- Los meses con NRT cambian cuando FIRMS publica el procesado estándar.
- El filtro de tipo del NRT es una aproximación por máscara.
- Quedan falsos positivos (superficies calientes, reflejos) que el filtro de confianza no quita.

## Salida (`frontend/public/data/`)

| Fichero                      | Contenido                                                        |
| ---------------------------- | ---------------------------------------------------------------- |
| `hotspots-manifest-v1.json`  | Rejilla, tiempo, método, factores, filtros, descartes, checksums |
| `hotspots-cells-v1.bin`      | `Uint32[]`: identificador global de cada celda con datos         |
| `hotspots-grid-v1-<año>.bin` | Conteos mensuales por celda de ese año                           |
| `detections-recent-v1.json`  | Detecciones individuales de los últimos 90 días (columnas)       |

Identificador de celda: `fila * columnas + columna`, con la fila 0 al sur y la columna 0 al
oeste. Cada binario anual es una estructura de arrays en little-endian, sin cabecera, con `n`
entradas (`anios[].entradas` del manifiesto):

| Array   | Tipo         | Significado                                        |
| ------- | ------------ | -------------------------------------------------- |
| `h`     | `Float32[n]` | Conteo armonizado (detecciones equivalentes MODIS) |
| `frpM`  | `Float32[n]` | Suma de FRP de MODIS (MW)                          |
| `frpV`  | `Float32[n]` | Suma de FRP de VIIRS (MW)                          |
| `cell`  | `Uint16[n]`  | Índice en `hotspots-cells-v1.bin`                  |
| `m`     | `Uint16[n]`  | Detecciones MODIS tras los filtros                 |
| `v`     | `Uint16[n]`  | Detecciones VIIRS tras los filtros                 |
| `month` | `Uint8[n]`   | Mes del año, 0-11                                  |

Ningún fichero puede pasar de 1024 KB (límite del guardián del repo); el script falla si ocurre.

## Atribución

NASA FIRMS / LANCE: MODIS Collection 6.1 (Terra y Aqua) y VIIRS S-NPP 375 m Collection 2.
Datos de acceso libre; NASA no avala este producto.

## Incendios (`incidents-v1.json`)

Agrupa las detecciones de los últimos 90 días en incendios: dos detecciones van juntas si están a
menos de 2 km y a menos de 3 días (encadenando, como un frente que avanza). Solo cuentan los grupos
de 3 o más detecciones. Para cada incendio:

- **Comunidad autónoma y provincia** de la detección más potente (si cae en el mar, la más cercana).
- **Contorno**: unión de las huellas de píxel (375 m VIIRS, 1 km MODIS) con un cierre morfológico de
  300 m, para que siga la forma del área afectada y no una rejilla. No es un perímetro oficial.
- **Actividad reciente**: detecciones en los 3 últimos días del dato. No significa «sin extinguir».
- Fechas, número de detecciones, sensores, FRP máxima y total y área estimada.

## Vías de escape de las simulaciones (`build-escape-routes`)

```bash
uv run --project tools/build-hotspots build-escape-routes \
  --scenarios frontend/src/map/scenarios.json --out frontend/public/data
```

Usa el **algoritmo de evacuación del equipo** (`backend/search/main.py`): propagación del fuego
con viento y A* espacio-temporal. Para cada simulación monta una rejilla de 100 m (~15 km de lado)
con carreteras y núcleos de OpenStreetMap (Overpass, caché en `data/raw/osm/`, no versionada) y mar
fuera de las comunidades autónomas. Busca rutas desde los núcleos amenazados (el fuego llega en
≤ 8 h) hasta refugios a ≥ 4 km donde tarda ≥ 2,5 veces más. Calibración: un turno = 12 min
(frente de ~2 km/h) y evacuación en vehículo a ~20 km/h. Escribe `escape-routes-v1.json` con
distancia, tiempo y margen frente al fuego.
La búsqueda va solo por carreteras y pistas (evacuación en vehículo) y la línea se pega después a la
geometría real de OSM dentro de un pasillo alrededor del camino elegido, así que sigue el asfalto y no
los escalones de la rejilla. La distancia y el tiempo son los de la carretera real y el tiempo extra
respecto al camino de la rejilla se resta del margen; si no cabe en ≤ 1,6× el recorrido original, se
conserva el de la rejilla. Si Overpass falla en una zona, esa simulación queda
sin rutas y las demás siguen.
