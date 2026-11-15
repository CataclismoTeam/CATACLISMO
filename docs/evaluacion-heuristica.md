# Evaluación heurística del front v2

Revisión de la interfaz con las 10 heurísticas de usabilidad de Nielsen, hecha el 15 de noviembre
de 2026 sobre el build de producción, en escritorio (1440 × 900) y en móvil (320 y 412 px), en
español y en inglés.

## Método

- Cada hallazgo lleva una **gravedad** de 0 a 4 (escala de Nielsen):
  0 no es un problema · 1 cosmético · 2 menor · 3 mayor · 4 catástrofe.
- Se arreglan los de gravedad 2 o más con coste bajo. Cada arreglo tiene su test e2e en
  `tests/e2e/heuristica.spec.ts`, salvo donde se indica otro fichero.
- Lo que queda pendiente se apunta al final con su motivo.

## Hallazgos

| #   | Heurística                      | Hallazgo                                                                                                                 | Gravedad | Estado                                                                  |
| --- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | :------: | ----------------------------------------------------------------------- |
| 1   | 1. Visibilidad del estado       | Un fallo al descargar incendios o rutas se quedaba en «Cargando…» y decía «no hay núcleos amenazados» (falso).           |    3     | Arreglado: tres estados y «Reintentar» (`demo.spec.ts`)                 |
| 2   | 1. Visibilidad del estado       | No se veía qué es real y qué simulado en pantallas normales; tampoco la antigüedad del dato (13 días).                   |    3     | Arreglado: chip de procedencia y «última detección» (`demo.spec.ts`)    |
| 3   | 2. Lenguaje del usuario         | «Actividad reciente» no decía respecto a qué fecha.                                                                      |    2     | Arreglado: «Activo al cierre del dato (2 nov)»                          |
| 4   | 2. Lenguaje del usuario         | Interfaz solo en español para un jurado internacional.                                                                   |    3     | Arreglado: español e inglés (`idioma.spec.ts`)                          |
| 5   | 3. Control y libertad           | Radio y Ajustes no se cerraban con Esc ni al pulsar fuera, y no movían el foco.                                          |    2     | Arreglado                                                               |
| 6   | 3. Control y libertad           | El panel de Capas no se cerraba con Esc.                                                                                 |    2     | Arreglado (no se cierra al pulsar el mapa: se usa a la vez)             |
| 7   | 3. Control y libertad           | Dibujar o medir no tenían salida clara.                                                                                  |    2     | Arreglado: Esc, «Cancelar» y «Salir» (`mapa.spec.ts`)                   |
| 8   | 4. Consistencia y estándares    | Dos controles distintos se llamaban «Línea de tiempo» (meses del calendario y horas del incendio).                       |    2     | Arreglado: «Recorrer los meses» y «Línea de tiempo del incendio»        |
| 9   | 4. Consistencia y estándares    | Pestañas de Unidades sin `aria-controls` ni flechas; mapa base con `role="radio"` y `aria-pressed` a la vez.             |    2     | Arreglado                                                               |
| 10  | 4. Consistencia y estándares    | Campos de formulario sin `id` ni `name` (aviso del navegador).                                                           |    1     | Arreglado                                                               |
| 11  | 5. Prevención de errores        | Los atajos «1» y «2» cambiaban el mapa con el briefing abierto.                                                          |    2     | Arreglado                                                               |
| 12  | 5. Prevención de errores        | Al dibujar, los clics caían en los marcadores de unidades; un rectángulo menor que una celda dejaba el calendario vacío. |    2     | Arreglado: los clics atraviesan los marcadores; área mínima de 5 km     |
| 13  | 5. Prevención de errores        | En móvil, girar con dos dedos desorientaba; en 3D, 80° de inclinación perdía el suelo.                                   |    2     | Arreglado: sin giro táctil, 70° máximo, vuelta al norte bajo 15°        |
| 14  | 6. Reconocer antes que recordar | Las tres franjas de predicción solo se distinguían por el color.                                                         |    2     | Arreglado: trama «/», «\» y cruzada, también en la leyenda              |
| 15  | 6. Reconocer antes que recordar | Las fichas y el botón «Capas» se tapaban entre sí y tapaban la lista del panel izquierdo.                                |    3     | Arreglado: pilas por esquina (`demo.spec.ts`)                           |
| 16  | 7. Flexibilidad y eficiencia    | No se podía buscar un lugar, medir ni compartir una vista exacta.                                                        |    2     | Arreglado: buscar, regla y enlace con la vista (`mapa.spec.ts`)         |
| 17  | 7. Flexibilidad y eficiencia    | Sin enlace para saltar la barra y el rail con el teclado.                                                                |    2     | Arreglado: «Saltar al mapa»                                             |
| 18  | 8. Diseño minimalista           | Botones «Entorno» y «Terreno» desactivados que parecían rotos.                                                           |    1     | Arreglado: retirados                                                    |
| 19  | 8. Diseño minimalista           | Con el calendario abierto el mapa quedaba en unos 200 px de alto.                                                        |    2     | Arreglado: calendario minimizado de inicio                              |
| 20  | 9. Recuperarse de errores       | El buscador sin clave o sin red no explicaba qué hacer.                                                                  |    2     | Arreglado: mensaje con la alternativa por coordenadas                   |
| 21  | 10. Ayuda y documentación       | El modelo de propagación del mapa era una caja negra; no había enlaces a las fuentes.                                    |    3     | Arreglado: «Datos y métodos» con ecuación, supuestos y límites; enlaces |
| 22  | 1. Visibilidad del estado       | El halo de los incendios reales usaba un viento inventado y parecía un pronóstico.                                       |    3     | Arreglado: capa «Ilustrativa», gris y apagada (`demo.spec.ts`)          |

## Pendiente

| #   | Heurística                      | Hallazgo                                                                                                       | Gravedad | Motivo para dejarlo                                                 |
| --- | ------------------------------- | -------------------------------------------------------------------------------------------------------------- | :------: | ------------------------------------------------------------------- |
| 23  | 6. Reconocer antes que recordar | En móvil, Buscar, Medir y Copiar enlace son solo iconos (tienen nombre accesible, pero no hay tooltip táctil). |    2     | No caben con texto en 320 px; valorar una fila de iconos con rótulo |
| 24  | 3. Control y libertad           | Cambiar de área no se puede deshacer (no hay «volver al área anterior»).                                       |    1     | Bajo impacto: las áreas rápidas están a un clic                     |
| 25  | 10. Ayuda y documentación       | No hay recorrido guiado la primera vez (capas, unidades, rutas), solo el briefing.                             |    2     | Requiere diseño; mejor tras probar con 3 o 4 personas de fuera      |
| 26  | 2. Lenguaje del usuario         | «Detecciones equivalentes MODIS» es jerga; se explica en «Datos y métodos», pero no junto al número.           |    1     | Añadir un «?» con la explicación corta                              |
| 27  | 9. Recuperarse de errores       | Algunos mensajes de error de datos con nombre de fichero quedan en español al usar el inglés.                  |    1     | Son mensajes técnicos poco frecuentes                               |
| 28  | 7. Flexibilidad y eficiencia    | El mapa mete muchos botones en el orden de tabulación (controles, marcadores).                                 |    1     | «Saltar al mapa» lo mitiga; revisar con lector de pantalla          |

## Siguiente paso recomendado

Probar con 3 o 4 personas ajenas al equipo, 5 minutos cada una, con dos tareas: «¿qué incendio
real sigue activo y cuándo se detectó?» y «¿qué pueblo hay que evacuar primero en Estepona?». Las
pruebas con usuarios encuentran lo que una evaluación heurística no ve.
