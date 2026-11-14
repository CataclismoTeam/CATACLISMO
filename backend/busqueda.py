from collections import deque

def calcular_tiempos_fuego(mapa, focos_incendio):
    """
    Simula la evolución del incendio paso a paso.
    Devuelve una matriz con el turno (tiempo) en el que el fuego llega a cada celda.
    """
    filas, cols = len(mapa), len(mapa[0])
    # Inicializamos con infinito: si el fuego nunca llega, el tiempo es infinito
    tiempo_fuego = [[float('inf')] * cols for _ in range(filas)]
    cola = deque()

    # Ponemos los focos iniciales en el instante t = 0
    for f, c in focos_incendio:
        tiempo_fuego[f][c] = 0
        cola.append((f, c, 0))

    direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while cola:
        f, c, t = cola.popleft()
        for df, dc in direcciones:
            nf, nc = f + df, c + dc
            # El fuego se propaga a celdas libres ('.') o de inicio ('S'), pero no a paredes ('#')
            # Asumimos que la salida ('E') es un punto seguro o cortafuegos
            if 0 <= nf < filas and 0 <= nc < cols:
                if mapa[nf][nc] not in ('#', 'E') and tiempo_fuego[nf][nc] == float('inf'):
                    tiempo_fuego[nf][nc] = t + 1
                    cola.append((nf, nc, t + 1))

    return tiempo_fuego


def encontrar_via_escape(mapa, inicio, salida, focos_incendio):
    """
    Busca la vía de escape más segura y corta utilizando Backtracking.
    """
    filas, cols = len(mapa), len(mapa[0])
    tiempo_fuego = calcular_tiempos_fuego(mapa, focos_incendio)
    
    visitado = [[False] * cols for _ in range(filas)]
    camino_actual = []
    mejor_camino = None

    def backtracking(f, c, t):
        nonlocal mejor_camino

        # Poda: Si el camino actual ya es igual o más largo que el mejor encontrado, no seguimos
        if mejor_camino is not None and len(camino_actual) >= len(mejor_camino):
            return

        # Caso base: Hemos llegado a la salida ('E')
        if (f, c) == salida:
            mejor_camino = list(camino_actual)
            return

        # Ordenar movimientos (opcional: priorizar acercarse a la salida acelera la poda)
        direcciones = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        direcciones.sort(key=lambda d: abs((f + d[0]) - salida[0]) + abs((c + d[1]) - salida[1]))

        for df, dc in direcciones:
            nf, nc = f + df, c + dc
            nuevo_tiempo = t + 1

            # 1. Comprobar límites del mapa y que no sea pared
            if 0 <= nf < filas and 0 <= nc < cols and mapa[nf][nc] != '#':
                # 2. Comprobar que no hayamos pasado por aquí en esta misma ruta
                if not visitado[nf][nc]:
                    # 3. CONDICIÓN CLAVE: El fuego debe llegar DESPUÉS que nosotros
                    if nuevo_tiempo < tiempo_fuego[nf][nc]:
                        
                        # --- HACER MOVIMIENTO ---
                        visitado[nf][nc] = True
                        camino_actual.append((nf, nc))

                        # --- LLAMADA RECURSIVA ---
                        backtracking(nf, nc, nuevo_tiempo)

                        # --- BACKTRACK (DESHACER MOVIMIENTO) ---
                        camino_actual.pop()
                        visitado[nf][nc] = False

    # Iniciar búsqueda desde la posición inicial en t = 0
    f_ini, c_ini = inicio
    visitado[f_ini][c_ini] = True
    camino_actual.append(inicio)
    
    backtracking(f_ini, c_ini, 0)

    return mejor_camino, tiempo_fuego


def mostrar_simulacion(mapa, camino, tiempo_fuego):
    """Muestra por consola el mapa final y el paso a paso de la evacuación."""
    if not camino:
        print("❌ No existe vía de escape posible. El fuego bloquea todas las salidas.")
        return

    print(f"✅ ¡Vía de escape encontrada en {len(camino) - 1} pasos!\n")
    
    # Mostrar paso a paso cómo evoluciona el fuego mientras la persona escapa
    filas, cols = len(mapa), len(mapa[0])
    for t, (pf, pc) in enumerate(camino):
        print(f"--- Turno t = {t} | Persona en ({pf}, {pc}) ---")
        for r in range(filas):
            fila_str = ""
            for c in range(cols):
                if (r, c) == (pf, pc):
                    fila_str += " 🏃 " # Persona
                elif mapa[r][c] == '#':
                    fila_str += " 🧱 " # Pared
                elif tiempo_fuego[r][c] <= t:
                    fila_str += " 🔥 " # Fuego activo en este turno
                elif mapa[r][c] == 'E':
                    fila_str += " 🚪 " # Salida
                elif (r, c) in camino:
                    fila_str += " ·  " # Ruta trazada
                else:
                    fila_str += "    " # Espacio libre
            print(fila_str)
        print()


# ==========================================
# EJEMPLO DE USO
# ==========================================
if __name__ == "__main__":
    # Leyenda:
    # 'S': Inicio (Start)
    # 'E': Salida (Exit)
    # '#': Pared
    # '.': Pasillo libre
    # 'F': Foco inicial del incendio
    
    cuadricula = [
        ['.', '.', '.', '.', '#', '.', 'F'],
        ['.', '#', '#', '.', '#', '.', '.'],
        ['.', '#', '.', '.', '.', '.', '.'],
        ['.', '#', '#', '.', '.', '#', '.'],
        ['S', '.', '.', '.', '.', 'E', '.']
    ]

    inicio = (4, 0)
    salida = (4, 5)
    focos_fuego = [(0, 6)] # Puedes añadir varios focos, ej: [(2, 2), (0, 6)]

    ruta, matriz_fuego = encontrar_via_escape(cuadricula, inicio, salida, focos_fuego)
    mostrar_simulacion(cuadricula, ruta, matriz_fuego)
