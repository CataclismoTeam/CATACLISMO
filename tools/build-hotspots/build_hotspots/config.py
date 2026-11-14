"""Parámetros del preproceso. Todo lo que cambia el resultado está aquí y acaba en el manifiesto."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Grid:
    """Rejilla regular en grados. La celda (fila, columna) se numera fila * ncols + columna."""

    west: float
    south: float
    east: float
    north: float
    cell_deg: float

    @property
    def ncols(self) -> int:
        return int(round((self.east - self.west) / self.cell_deg))

    @property
    def nrows(self) -> int:
        return int(round((self.north - self.south) / self.cell_deg))


# España completa, con Canarias y Baleares
SPAIN_BBOX = (-18.2, 27.6, 4.4, 43.8)


@dataclass(frozen=True)
class Config:
    grid: Grid = field(default_factory=lambda: Grid(*SPAIN_BBOX, cell_deg=0.05))
    # Tipos FIRMS que cuentan: 0 vegetación, 1 volcán, 2 fuente estática, 3 offshore
    types: tuple[int, ...] = (0,)
    # Regla común de confianza: MODIS es numérica (0-100) y VIIRS categórica (l/n/h).
    # FIRMS define "baja" como < 30 en MODIS, equivalente a la clase "l" de VIIRS.
    modis_min_confidence: int = 30
    viirs_drop_low: bool = True
    # El NRT no trae "type": se descartan sus detecciones en puntos donde el archivo
    # estándar ya vio al menos este número de detecciones de tipos excluidos.
    static_mask_min: int = 3
    static_mask_deg: float = 0.01
    # Días de detecciones individuales que se publican para la capa del mapa
    recent_days: int = 90
    # Mínimo de detecciones VIIRS de un mes del año para darle factor propio
    min_calibration_count: int = 100
    bootstrap_samples: int = 2000
    seed: int = 20261114
