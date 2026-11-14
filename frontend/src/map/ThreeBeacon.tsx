import { useEffect, useRef } from 'react';
import {
  AmbientLight,
  BoxGeometry,
  Color,
  DirectionalLight,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  WebGLRenderer,
} from 'three';

/** Elemento 3D compacto para comunicar el estado del incidente sin duplicar el mapa. */
export function ThreeBeacon() {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current) return;
    const renderer = new WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(96, 64, false);
    host.current.appendChild(renderer.domElement);

    const scene = new Scene();
    scene.add(new AmbientLight(0xffffff, 1.8));
    const light = new DirectionalLight(0xffffff, 2.5);
    light.position.set(2, 4, 3);
    scene.add(light);

    const beacon = new Mesh(
      new BoxGeometry(0.9, 1.5, 0.9),
      new MeshStandardMaterial({ color: new Color('#ff7043'), roughness: 0.35, metalness: 0.15 }),
    );
    scene.add(beacon);

    const camera = new PerspectiveCamera(35, 1.5, 0.1, 100);
    camera.position.set(2.4, 1.8, 3.2);
    camera.lookAt(0, 0.4, 0);
    let frame = 0;
    const animate = () => {
      beacon.rotation.y += 0.012;
      beacon.rotation.x = Math.sin(performance.now() / 900) * 0.08;
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();
    return () => {
      cancelAnimationFrame(frame);
      renderer.dispose();
      beacon.geometry.dispose();
      beacon.material.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={host} className="h-16 w-24 shrink-0" aria-label="Indicador 3D del incidente" />;
}
