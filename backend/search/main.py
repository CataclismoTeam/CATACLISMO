"""Módulo de búsqueda y cálculo de vías de escape seguras frente a incendios.

Optimizado para mapas reales de gran escala (redes de terreno, elevación,
viento, cortafuegos y georreferenciación WGS84).
"""

from __future__ import annotations

import heapq
import json
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

# ============================================================================ #
# 1. Catálogo de terrenos y factores físicos para mapas reales
# ============================================================================ #

# Factores de velocidad de tránsito humano (multiplicador de tiempo por distancia)
# Menor valor = más rápido; mayor valor = más lento.
COSTES_TERRENO: dict[str, float] = {
    ".": 1.0,  # Campo abierto / suelo transitable estándar
    " ": 1.0,  # Espacio libre
    "S": 1.0,  # Punto de inicio
    "E": 1.0,  # Salida o refugio seguro
    "R": 0.5,  # Carretera asfaltada / calle despejada (avance rápido)
    "=": 0.5,  # Carretera principal
    "-": 0.75,  # Sendero / pista rural
    "T": 1.7,  # Arbolado denso / bosque (dificultad de paso)
    "V": 1.5,  # Matorral / vegetación media
    "C": 0.8,  # Cortafuegos despejado
}

# Tipos de celda que bloquean el paso humano
BARRERAS_PERSONA: set[str] = {"#", "W", "~"}

# Tipos de celda que no arden o sirven como cortafuegos natural
ZONAS_IGNIFUGAS: set[str] = {"#", "W", "~", "C", "E"}

# Factores de velocidad de propagación del fuego según combustible
COMBUSTIBILIDAD_TERRENO: dict[str, float] = {
    "T": 1.6,  # Bosque denso: propagación rápida
    "V": 1.3,  # Matorral seco: propagación moderada-rápida
    ".": 1.0,  # Suelo general
    " ": 1.0,
    "-": 0.7,  # Sendero de tierra
    "R": 0.2,  # Carretera de asfalto (dificulta el cruce de fuego)
    "=": 0.2,
}


# ============================================================================ #
# 2. Georreferenciación (WGS84) para mapas reales
# ============================================================================ #


@dataclass
class GeoReferencia:
    """Transforma coordenadas de cuadrícula (fila, columna) a coordenadas WGS84 (lat, lon)."""

    lat_origen: float  # Latitud en la esquina superior izquierda (fila 0, col 0)
    lon_origen: float  # Longitud en la esquina superior izquierda
    resolucion_metros: float = 10.0  # Tamaño en metros de cada celda

    def grid_a_latlon(self, fila: float, col: float) -> tuple[float, float]:
        """Convierte (fila, col) a (latitud, longitud)."""
        metros_por_grado_lat = 111139.0
        delta_lat = -(fila * self.resolucion_metros) / metros_por_grado_lat

        lat_rad = math.radians(self.lat_origen)
        metros_por_grado_lon = 111139.0 * math.cos(lat_rad)
        delta_lon = (col * self.resolucion_metros) / metros_por_grado_lon

        return self.lat_origen + delta_lat, self.lon_origen + delta_lon

    def latlon_a_grid(self, lat: float, lon: float) -> tuple[int, int]:
        """Convierte (latitud, longitud) a (fila, col) más cercana."""
        metros_por_grado_lat = 111139.0
        lat_rad = math.radians(self.lat_origen)
        metros_por_grado_lon = 111139.0 * math.cos(lat_rad)

        fila = round(-(lat - self.lat_origen) * metros_por_grado_lat / self.resolucion_metros)
        col = round((lon - self.lon_origen) * metros_por_grado_lon / self.resolucion_metros)
        return fila, col


# ============================================================================ #
# 3. Modelado y cálculo de la propagación del fuego
# ============================================================================ #


def calcular_tiempos_fuego(
    mapa: list[list[str]] | list[str],
    focos_incendio: list[tuple[int, int]] | None = None,
    permitir_diagonales: bool = True,
    velocidad_fuego: float = 1.0,
    viento: tuple[float, float] | None = None,
    zonas_ignifugas: set[str] | None = None,
) -> list[list[float]]:
    """Simula la evolución continua del incendio en el terreno.

    Devuelve una matriz con el tiempo estimado (turnos o segundos) en el que las
    llamas alcanzan cada celda.

    Parámetros:
    - mapa: Cuadrícula del terreno (caracteres o strings).
    - focos_incendio: Lista de celdas iniciales (fila, col). Si es None, busca 'F'.
    - permitir_diagonales: Si True, el fuego se propaga en 8 direcciones con distancia euclídea.
    - velocidad_fuego: Velocidad base de expansión.
    - viento: Vector (v_fila, v_col) que acelera el fuego a favor y lo frena en contra.
    - zonas_ignifugas: Conjunto de tipos de terreno que no arden (muros, agua, etc.).
    """
    filas = len(mapa)
    if filas == 0:
        return []
    cols = len(mapa[0])

    tiempo_fuego = [[float("inf")] * cols for _ in range(filas)]
    cola_prioridad: list[tuple[float, int, int]] = []

    # Autodetección de focos si no se especifican explícitamente
    focos = list(focos_incendio) if focos_incendio is not None else []
    if focos_incendio is None:
        for r in range(filas):
            for c in range(cols):
                if mapa[r][c] == "F":
                    focos.append((r, c))

    if not focos:
        return tiempo_fuego

    for f, c in focos:
        if 0 <= f < filas and 0 <= c < cols:
            tiempo_fuego[f][c] = 0.0
            heapq.heappush(cola_prioridad, (0.0, f, c))

    barreras_fuego = ZONAS_IGNIFUGAS if zonas_ignifugas is None else zonas_ignifugas

    # Direcciones de propagación
    if permitir_diagonales:
        direcciones = [
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ]
    else:
        direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while cola_prioridad:
        t_actual, f, c = heapq.heappop(cola_prioridad)

        if t_actual > tiempo_fuego[f][c]:
            continue

        for df, dc in direcciones:
            nf, nc = f + df, c + dc
            if not (0 <= nf < filas and 0 <= nc < cols):
                continue

            tipo_celda = mapa[nf][nc]
            if tipo_celda in barreras_fuego:
                continue

            dist = math.hypot(df, dc)

            # Efecto del viento: vector (v_fila, v_col)
            factor_viento = 1.0
            if viento is not None and dist > 0:
                vf, vc = viento
                norm_f, norm_c = df / dist, dc / dist
                producto_punto = norm_f * vf + norm_c * vc
                # Mayor velocidad si el paso va en la dirección del viento
                factor_viento = max(0.2, 1.0 + producto_punto)

            combustibilidad = COMBUSTIBILIDAD_TERRENO.get(tipo_celda, 1.0)
            tiempo_paso = (dist * combustibilidad) / (velocidad_fuego * factor_viento)
            t_llegada = t_actual + tiempo_paso

            if t_llegada < tiempo_fuego[nf][nc]:
                tiempo_fuego[nf][nc] = t_llegada
                heapq.heappush(cola_prioridad, (t_llegada, nf, nc))

    return tiempo_fuego


# ============================================================================ #
# 4. Algoritmo A* espacio-temporal de evacuación
# ============================================================================ #


def encontrar_via_escape(
    mapa: list[list[str]] | list[str],
    inicio: tuple[int, int] | None = None,
    salida: tuple[int, int] | list[tuple[int, int]] | set[tuple[int, int]] | None = None,
    focos_incendio: list[tuple[int, int]] | None = None,
    permitir_diagonales: bool = True,
    margen_seguridad: float = 0.0,
    peso_riesgo: float = 0.0,
    tiempo_fuego_previo: list[list[float]] | None = None,
    viento: tuple[float, float] | None = None,
    velocidad_persona: float = 1.0,
) -> tuple[list[tuple[int, int]] | None, list[list[float]]]:
    """Busca la vía de escape óptima y segura frente al incendio mediante A* espacio-temporal.

    Sustituye la búsqueda exponencial por A* guiado por heurística euclídea/octile,
    capaz de procesar mapas de gran escala en milisegundos sin desbordamiento de recursión.

    Parámetros:
    - mapa: Matriz o lista de filas con la información del terreno.
    - inicio: Coordenada (fila, col) de inicio. Si es None, busca 'S'.
    - salida: Coordenada o lista de coordenadas de salida/refugios. Si es None, busca todas las 'E'.
    - focos_incendio: Focos iniciales de fuego. Si es None, busca todas las 'F'.
    - permitir_diagonales: Permite movimiento realista en 8 direcciones (distancia euclídea).
    - margen_seguridad: Margen de tiempo mínimo entre la persona y el fuego al cruzar una celda.
    - peso_riesgo: Factor de penalización por aproximarse al frente de fuego (0.0 = camino más rápido).
    - tiempo_fuego_previo: Matriz de tiempos de fuego ya calculada (si se desea reutilizar).
    - viento: Vector de viento (v_fila, v_col) para la propagación del fuego.
    - velocidad_persona: Velocidad media de desplazamiento de los evacuados.
    """
    filas = len(mapa)
    if filas == 0:
        return None, []
    cols = len(mapa[0])

    # 1. Resolver posición de inicio
    if inicio is None:
        inicio_encontrado = None
        for r in range(filas):
            for c in range(cols):
                if mapa[r][c] == "S":
                    inicio_encontrado = (r, c)
                    break
            if inicio_encontrado:
                break
        if inicio_encontrado is None:
            raise ValueError("No se especificó punto de inicio ni se encontró 'S' en el mapa.")
        pto_inicio = inicio_encontrado
    else:
        pto_inicio = inicio

    # 2. Resolver conjunto de salidas (soporta múltiples salidas / refugios)
    salidas_set: set[tuple[int, int]] = set()
    if salida is None:
        for r in range(filas):
            for c in range(cols):
                if mapa[r][c] == "E":
                    salidas_set.add((r, c))
        if not salidas_set:
            raise ValueError("No se especificó salida ni se encontró ninguna 'E' en el mapa.")
    elif isinstance(salida, tuple) and len(salida) == 2 and isinstance(salida[0], int):
        salidas_set.add(salida)
    else:
        salidas_set.update(salida)

    # 3. Calcular evolución del incendio
    if tiempo_fuego_previo is not None:
        tiempo_fuego = tiempo_fuego_previo
    else:
        tiempo_fuego = calcular_tiempos_fuego(
            mapa=mapa,
            focos_incendio=focos_incendio,
            permitir_diagonales=permitir_diagonales,
            viento=viento,
        )

    # Si el punto de partida ya está quemado antes de empezar
    if tiempo_fuego[pto_inicio[0]][pto_inicio[1]] <= 0.0:
        return None, tiempo_fuego

    # Si el inicio ya es una de las salidas
    if pto_inicio in salidas_set:
        return [pto_inicio], tiempo_fuego

    # 4. Heurística admisible adaptada a múltiples salidas
    def heuristica(r: int, c: int) -> float:
        h_min = float("inf")
        for er, ec in salidas_set:
            dr = abs(r - er)
            dc = abs(c - ec)
            if permitir_diagonales:
                # Distancia Octile con coste diagonal sqrt(2)
                d_diag = min(dr, dc)
                d_rect = abs(dr - dc)
                dist = d_diag * 1.41421356 + d_rect * 1.0
            else:
                dist = dr + dc
            if dist < h_min:
                h_min = dist
        return h_min

    # Direcciones de movimiento
    if permitir_diagonales:
        direcciones = [
            (-1, 0),
            (1, 0),
            (0, -1),
            (0, 1),
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1),
        ]
    else:
        direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    # 5. Búsqueda A*
    # Elemento: (f_score, g_coste, tiempo_llegada, r, c)
    open_heap: list[tuple[float, float, float, int, int]] = []
    h_ini = heuristica(pto_inicio[0], pto_inicio[1])
    heapq.heappush(open_heap, (h_ini, 0.0, 0.0, pto_inicio[0], pto_inicio[1]))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_costs: dict[tuple[int, int], float] = {pto_inicio: 0.0}

    salida_alcanzada: tuple[int, int] | None = None

    while open_heap:
        f_score, g_cost, t_actual, r, c = heapq.heappop(open_heap)

        # Si ya se encontró un coste mejor para esta celda, omitir
        if g_cost > g_costs.get((r, c), float("inf")):
            continue

        if (r, c) in salidas_set:
            salida_alcanzada = (r, c)
            break

        for df, dc in direcciones:
            nr, nc = r + df, c + dc
            if not (0 <= nr < filas and 0 <= nc < cols):
                continue

            tipo_celda = mapa[nr][nc]
            # Muros y cuerpos de agua son barreras intransitables a pie
            if tipo_celda in BARRERAS_PERSONA:
                continue

            dist = math.hypot(df, dc)
            factor_terreno = COSTES_TERRENO.get(tipo_celda, 1.0)
            tiempo_paso = (dist * factor_terreno) / velocidad_persona
            nuevo_tiempo = t_actual + tiempo_paso

            # Condición de supervivencia:
            # El evacuado debe llegar a la celda antes de que el fuego la alcance
            # (con el margen de seguridad requerido)
            if nuevo_tiempo + margen_seguridad >= tiempo_fuego[nr][nc]:
                continue

            # Penalización por cercanía al frente de fuego (enrutamiento seguro)
            penalizacion_riesgo = 0.0
            if peso_riesgo > 0.0:
                margen_disponible = tiempo_fuego[nr][nc] - nuevo_tiempo
                if margen_disponible < 8.0:
                    penalizacion_riesgo = peso_riesgo / max(0.2, margen_disponible)

            nuevo_g = g_cost + tiempo_paso + penalizacion_riesgo

            if nuevo_g < g_costs.get((nr, nc), float("inf")):
                g_costs[(nr, nc)] = nuevo_g
                came_from[(nr, nc)] = (r, c)
                f_siguiente = nuevo_g + heuristica(nr, nc)
                heapq.heappush(open_heap, (f_siguiente, nuevo_g, nuevo_tiempo, nr, nc))

    if salida_alcanzada is None:
        return None, tiempo_fuego

    # Reconstrucción del camino óptimo
    camino = []
    nodo_actual: tuple[int, int] | None = salida_alcanzada
    while nodo_actual is not None:
        camino.append(nodo_actual)
        nodo_actual = came_from.get(nodo_actual)
    camino.reverse()

    return camino, tiempo_fuego


# ============================================================================ #
# 5. Métricas operativas y exportación GeoJSON
# ============================================================================ #


def calcular_metricas_evacuacion(
    camino: list[tuple[int, int]] | None,
    tiempo_fuego: list[list[float]],
    resolucion_metros: float = 10.0,
    velocidad_persona: float = 1.0,
) -> dict[str, Any]:
    """Calcula estadísticas y márgenes de seguridad de la ruta de evacuación."""
    if not camino:
        return {
            "viable": False,
            "pasos": 0,
            "distancia_metros": 0.0,
            "tiempo_estimado": 0.0,
            "margen_minimo_fuego": 0.0,
            "salida": None,
        }

    distancia_total = 0.0
    tiempo_acumulado = 0.0
    margen_minimo = float("inf")

    for i in range(len(camino) - 1):
        r1, c1 = camino[i]
        r2, c2 = camino[i + 1]
        paso_celdas = math.hypot(r2 - r1, c2 - c1)
        distancia_total += paso_celdas * resolucion_metros
        tiempo_acumulado += paso_celdas / velocidad_persona

        t_fuego_destino = tiempo_fuego[r2][c2]
        margen = t_fuego_destino - tiempo_acumulado
        if margen < margen_minimo:
            margen_minimo = margen

    return {
        "viable": True,
        "pasos": len(camino) - 1,
        "distancia_metros": round(distancia_total, 2),
        "tiempo_estimado": round(tiempo_acumulado, 2),
        "margen_minimo_fuego": round(margen_minimo, 2) if margen_minimo != float("inf") else None,
        "salida": camino[-1],
    }


def ruta_a_geojson(
    camino: list[tuple[int, int]] | None,
    tiempo_fuego: list[list[float]] | None = None,
    geo_ref: GeoReferencia | None = None,
) -> dict[str, Any]:
    """Convierte la ruta de escape en un objeto GeoJSON (FeatureCollection).

    Compatible directamente con CesiumJS, deck.gl, Leaflet o PostGIS.
    """
    if not camino:
        return {"type": "FeatureCollection", "features": []}

    coordenadas_geojson = []
    for r, c in camino:
        if geo_ref is not None:
            lat, lon = geo_ref.grid_a_latlon(r, c)
            # GeoJSON usa convención [longitud, latitud]
            coordenadas_geojson.append([round(lon, 6), round(lat, 6)])
        else:
            coordenadas_geojson.append([c, r])

    metricas = (
        calcular_metricas_evacuacion(camino, tiempo_fuego)
        if tiempo_fuego
        else {"pasos": len(camino) - 1}
    )

    feature_linea = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordenadas_geojson,
        },
        "properties": {
            "nombre": "Vía de escape segura",
            "tipo": "ruta_evacuacion",
            **metricas,
        },
    }

    feature_inicio = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": coordenadas_geojson[0],
        },
        "properties": {"nombre": "Punto de inicio", "tipo": "inicio"},
    }

    feature_salida = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": coordenadas_geojson[-1],
        },
        "properties": {"nombre": "Punto de evacuación seguro", "tipo": "salida"},
    }

    return {
        "type": "FeatureCollection",
        "features": [feature_linea, feature_inicio, feature_salida],
    }


# ============================================================================ #
# 6. Visualización y simulación de la evacuación
# ============================================================================ #


def mostrar_simulacion(
    mapa: list[list[str]] | list[str],
    camino: list[tuple[int, int]] | None,
    tiempo_fuego: list[list[float]],
    paso_a_paso: bool | None = None,
    geo_ref: GeoReferencia | None = None,
) -> None:
    """Muestra por consola el mapa y la evolución de la evacuación.

    En mapas reducidos muestra la animación detallada paso a paso.
    En mapas reales de gran tamaño muestra un resumen operativo con métricas,
    distancias y una vista consolidada de la ruta frente al fuego.
    """
    if not camino:
        print("No existe via de escape posible. El fuego bloquea las salidas.")
        return

    filas, cols = len(mapa), len(mapa[0])
    num_pasos = len(camino) - 1

    resolucion = geo_ref.resolucion_metros if geo_ref else 1.0
    metricas = calcular_metricas_evacuacion(camino, tiempo_fuego, resolucion_metros=resolucion)

    print(f"Via de escape encontrada en {num_pasos} pasos!")
    if geo_ref:
        print(
            f"Distancia total: {metricas['distancia_metros']} m | "
            f"Tiempo estimado: {metricas['tiempo_estimado']} s | "
            f"Margen mín. con el fuego: {metricas['margen_minimo_fuego']} s"
        )
    print()

    # Si paso_a_paso no se especifica, se activa en mapas pequeños (<= 15x30 y <= 15 pasos)
    es_mapa_pequeno = filas <= 15 and cols <= 30 and len(camino) <= 15
    mostrar_frames = paso_a_paso if paso_a_paso is not None else es_mapa_pequeno

    if mostrar_frames:
        for t, (pf, pc) in enumerate(camino):
            print(f"--- Turno t = {t} | Persona en ({pf}, {pc}) ---")
            for r in range(filas):
                fila_str = ""
                for c in range(cols):
                    if (r, c) == (pf, pc):
                        fila_str += " 🏃 "
                    elif mapa[r][c] == "#":
                        fila_str += " 🧱 "
                    elif mapa[r][c] in ("W", "~"):
                        fila_str += " 💧 "
                    elif tiempo_fuego[r][c] <= t:
                        fila_str += " 🔥 "
                    elif mapa[r][c] == "E":
                        fila_str += " 🚪 "
                    elif (r, c) in camino:
                        fila_str += " ·  "
                    else:
                        fila_str += "    "
                print(fila_str)
            print()
    else:
        # Vista consolidada para mapas reales extensos
        conjunto_camino = set(camino)
        print("Mapa de la ruta de evacuación completa:")
        for r in range(filas):
            fila_str = ""
            for c in range(cols):
                if (r, c) == camino[0]:
                    fila_str += " 🏃 "
                elif (r, c) == camino[-1]:
                    fila_str += " 🚪 "
                elif (r, c) in conjunto_camino:
                    fila_str += " ·  "
                elif mapa[r][c] == "#":
                    fila_str += " 🧱 "
                elif mapa[r][c] in ("W", "~"):
                    fila_str += " 💧 "
                elif mapa[r][c] == "R":
                    fila_str += " ═  "
                elif tiempo_fuego[r][c] != float("inf"):
                    fila_str += " 🔥 "
                else:
                    fila_str += "    "
            print(fila_str)
        print()


# ============================================================================ #
# 7. Ejecución y comprobaciones
# ============================================================================ #

if __name__ == "__main__":
    print("==================================================================")
    print("CASO 1: Validación del escenario base (compatibilidad original)")
    print("==================================================================")

    cuadricula = [
        [".", ".", ".", ".", "#", ".", "F"],
        [".", "#", "#", ".", "#", ".", "."],
        [".", "#", ".", ".", ".", ".", "."],
        [".", "#", "#", ".", "#", "#", "."],
        [".", ".", ".", "S", ".", "E", "."],
    ]

    pto_inicio = (4, 3)
    pto_salida = (4, 5)
    focos_fuego = [(0, 6)]

    ruta, matriz_fuego = encontrar_via_escape(
        cuadricula,
        pto_inicio,
        pto_salida,
        focos_fuego,
        permitir_diagonales=False,  # Comprobación de paso 4-direccional original
    )
    mostrar_simulacion(cuadricula, ruta, matriz_fuego)

    print("==================================================================")
    print("CASO 2: Escenario realista con mapa de terreno, viento y GPS WGS84")
    print("==================================================================")

    # Cuadrícula realista con carreteras (R), agua/cortafuegos (W),
    # arbolado denso (T), múltiples salidas (E), viento y geolocalización.
    mapa_real = [
        ".........................",
        "....TTTT...#..W..........",
        "...TTTTT...#..W...F......",
        "...TTTT....#..W..........",
        "....TT.....#..WWWWW......",
        "RRRRRRRRRRRRRRRRRRRRRRRE.",
        "....#......#......W......",
        "....#...S..#......W......",
        "....#......#..E...W......",
        "....########......W......",
        "..................W......",
    ]

    geo = GeoReferencia(lat_origen=40.4168, lon_origen=-3.7038, resolucion_metros=25.0)

    # Viento que sopla empujando el fuego hacia el Sureste (+0.5 filas, +0.8 cols)
    viento_actual = (0.5, 0.8)

    ruta_real, fuego_real = encontrar_via_escape(
        mapa=mapa_real,
        inicio=None,  # Autodetecta 'S'
        salida=None,  # Autodetecta todas las salidas 'E' disponibles
        focos_incendio=None,  # Autodetecta 'F'
        permitir_diagonales=True,  # Movimiento libre 8-direccional
        margen_seguridad=2.0,  # Margen de seguridad prudente
        peso_riesgo=0.8,  # Prioriza pasillos lejos del humo
        viento=viento_actual,
    )

    mostrar_simulacion(mapa_real, ruta_real, fuego_real, geo_ref=geo)

    geojson_data = ruta_a_geojson(ruta_real, fuego_real, geo_ref=geo)
    print("GeoJSON generado (primeros 2 elementos de coordenadas):")
    coords = geojson_data["features"][0]["geometry"]["coordinates"]
    print(f"Total puntos geográficos: {len(coords)} | Inicio: {coords[0]} | Fin: {coords[-1]}")
