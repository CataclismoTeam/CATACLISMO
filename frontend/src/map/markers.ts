// Símbolos operativos: cada unidad es una placa con icono de su tipo, su indicativo y su estado
// (color + icono + texto), no un punto genérico.
import {
  Ambulance,
  CircleCheck,
  CircleSlash,
  createElement,
  Drone,
  Flag,
  Flame,
  Helicopter,
  Fuel,
  Navigation,
  Plane,
  Ship,
  Tractor,
  ShieldUser,
  Truck,
  Users,
  type IconNode,
} from 'lucide';
import type { Unit, UnitKind, UnitStatus } from './scenario.ts';

export const KIND: Record<UnitKind, { icon: IconNode; label: string }> = {
  autobomba: { icon: Truck, label: 'Autobomba' },
  helicoptero: { icon: Helicopter, label: 'Helicóptero' },
  dron: { icon: Drone, label: 'Dron' },
  mando: { icon: ShieldUser, label: 'Puesto de mando' },
  ambulancia: { icon: Ambulance, label: 'Ambulancia' },
  brigada: { icon: Users, label: 'Brigada' },
  nodriza: { icon: Fuel, label: 'Nodriza' },
  maquinaria: { icon: Tractor, label: 'Maquinaria pesada' },
  avion: { icon: Plane, label: 'Avión' },
  embarcacion: { icon: Ship, label: 'Embarcación' },
};

export const STATUS: Record<UnitStatus, { icon: IconNode; label: string; color: string }> = {
  disponible: { icon: CircleCheck, label: 'Disponible', color: 'var(--color-st-disponible)' },
  'en ruta': { icon: Navigation, label: 'En ruta', color: 'var(--color-st-ruta)' },
  'en intervencion': {
    icon: Flame,
    label: 'En intervención',
    color: 'var(--color-st-intervencion)',
  },
  'no disponible': { icon: CircleSlash, label: 'No disponible', color: 'var(--color-st-no)' },
};

function icon(node: IconNode, size: number, color = 'currentColor'): SVGElement {
  const el = createElement(node);
  el.setAttribute('width', String(size));
  el.setAttribute('height', String(size));
  // style y no atributo: los colores de estado son variables CSS (cambian con tema y daltonismo)
  el.style.stroke = color;
  el.setAttribute('stroke-width', '1.75');
  el.setAttribute('aria-hidden', 'true');
  return el;
}

export function unitElement(unit: Unit, onSelect: (unit: Unit) => void): HTMLElement {
  const status = STATUS[unit.status];
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'unit-marker';
  button.style.setProperty('--status', status.color);
  button.setAttribute(
    'aria-label',
    `${KIND[unit.kind].label} ${unit.id}: ${status.label}. Simulado`,
  );
  const badge = document.createElement('span');
  badge.className = 'unit-marker__icon';
  badge.append(icon(KIND[unit.kind].icon, 20));
  const text = document.createElement('span');
  text.className = 'unit-marker__text';
  const id = document.createElement('strong');
  id.textContent = unit.id;
  const st = document.createElement('span');
  st.className = 'unit-marker__status';
  st.append(icon(status.icon, 13, status.color), document.createTextNode(status.label));
  text.append(id, st);
  button.append(badge, text);
  button.addEventListener('click', (e) => {
    e.stopPropagation();
    onSelect(unit);
  });
  return button;
}

export function meetingElement(name: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'meeting-marker';
  el.append(icon(Flag, 16), document.createTextNode(name));
  return el;
}

export function ignitionElement(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'ignition-marker';
  el.append(icon(Flame, 16), document.createTextNode('Origen · SIMULADO'));
  return el;
}
