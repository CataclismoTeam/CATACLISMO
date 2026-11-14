import { Deck, OrthographicView } from '@deck.gl/core';
import { ScatterplotLayer } from '@deck.gl/layers';
import { useEffect, useRef } from 'react';

const POINTS = [
  { position: [34, 52], color: [255, 112, 67], radius: 11 },
  { position: [86, 38], color: [98, 168, 255], radius: 8 },
  { position: [142, 70], color: [76, 201, 140], radius: 8 },
  { position: [192, 46], color: [255, 184, 51], radius: 8 },
] as const;

/** Inset táctico de deck.gl; no sustituye al globo Cesium. */
export function OperationalDeck() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvas.current) return;
    const deck = new Deck({
      canvas: canvas.current,
      views: new OrthographicView({ id: 'tactical' }),
      initialViewState: { target: [120, 60, 0], zoom: 0 },
      controller: false,
      useDevicePixels: false,
      layers: [
        new ScatterplotLayer({
          id: 'operational-points',
          data: POINTS,
          getPosition: (point) => point.position,
          getFillColor: (point) => point.color,
          getRadius: (point) => point.radius,
          radiusUnits: 'pixels',
          pickable: false,
        }),
      ],
    });
    return () => deck.finalize();
  }, []);

  return <canvas ref={canvas} className="h-24 w-full" aria-label="Vista táctica de unidades" />;
}
