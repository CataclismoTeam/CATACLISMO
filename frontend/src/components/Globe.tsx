import { useEffect, useRef } from 'react';
import { ImageryLayer, OpenStreetMapImageryProvider, Viewer } from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';

// Globo base de Cesium sin Cesium ion (no necesita token): teselas de OpenStreetMap.
export default function Globe() {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const viewer = new Viewer(container.current, {
      baseLayer: new ImageryLayer(
        new OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }),
      ),
      baseLayerPicker: false,
      geocoder: false,
      timeline: false,
      animation: false,
    });
    return () => viewer.destroy();
  }, []);

  return <div ref={container} className="globe" data-testid="globo" />;
}
