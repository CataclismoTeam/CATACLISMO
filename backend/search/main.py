from collections import deque


def calcular_tiempos_fuego(mapa, focos_incendio):
    """Simula la evolucion del incendio paso a paso.

    Devuelve una matriz con el turno en el que el fuego llega a cada celda.
    """
    filas, cols = len(mapa), len(mapa[0])
    tiempo_fuego = [[float("inf")] * cols for _ in range(filas)]
    cola = deque()

    for f, c in focos_incendio:
        tiempo_fuego[f][c] = 0
        cola.append((f, c, 0))

    direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while cola:
        f, c, t = cola.popleft()
        for df, dc in direcciones:
            nf, nc = f + df, c + dc
            if 0 <= nf < filas and 0 <= nc < cols:
                if (
                    mapa[nf][nc] not in ("#", "E")
                    and tiempo_fuego[nf][nc] == float("inf")
                ):
                    tiempo_fuego[nf][nc] = t + 1
                    cola.append((nf, nc, t + 1))

    return tiempo_fuego


def encontrar_via_escape(mapa, inicio, salida, focos_incendio):
    """Busca la via de escape mas segura y corta utilizando Backtracking."""
    filas, cols = len(mapa), len(mapa[0])
    tiempo_fuego = calcular_tiempos_fuego(mapa, focos_incendio)

    visitado = [[False] * cols for _ in range(filas)]
    camino_actual = []
    mejor_camino = None

    def backtracking(f, c, t):
        nonlocal mejor_camino

        if mejor_camino is not None and len(camino_actual) >= len(mejor_camino):
            return

        if (f, c) == salida:
            mejor_camino = list(camino_actual)
            return

        direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        direcciones.sort(
            key=lambda d: abs((f + d[0]) - salida[0]) + abs((c + d[1]) - salida[1])
        )

        for df, dc in direcciones:
            nf, nc = f + df, c + dc
            nuevo_tiempo = t + 1

            if 0 <= nf < filas and 0 <= nc < cols and mapa[nf][nc] != "#":
                if not visitado[nf][nc] and nuevo_tiempo < tiempo_fuego[nf][nc]:
                    visitado[nf][nc] = True
                    camino_actual.append((nf, nc))

                    backtracking(nf, nc, nuevo_tiempo)

                    camino_actual.pop()
                    visitado[nf][nc] = False

    f_ini, c_ini = inicio
    visitado[f_ini][c_ini] = True
    camino_actual.append(inicio)

    backtracking(f_ini, c_ini, 0)

    return mejor_camino, tiempo_fuego


def mostrar_simulacion(mapa, camino, tiempo_fuego):
    """Muestra por consola el mapa final y el paso a paso de la evacuacion."""
    if not camino:
        print("No existe via de escape posible. El fuego bloquea las salidas.")
        return

    print(f"Via de escape encontrada en {len(camino) - 1} pasos!\n")

    filas, cols = len(mapa), len(mapa[0])
    for t, (pf, pc) in enumerate(camino):
        print(f"--- Turno t = {t} | Persona en ({pf}, {pc}) ---")
        for r in range(filas):
            fila_str = ""
            for c in range(cols):
                if (r, c) == (pf, pc):
                    fila_str += " 🏃 "
                elif mapa[r][c] == "#":
                    fila_str += " 🧱 "
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


if __name__ == "__main__":
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
        cuadricula, pto_inicio, pto_salida, focos_fuego
    )
    mostrar_simulacion(cuadricula, ruta, matriz_fuego)