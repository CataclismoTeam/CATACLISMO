// Presupuesto de peso del build: falla (exit 1) si el sitio engorda por encima de los límites.
// Mide los ficheros de dist/ sin comprimir. Se ejecuta en el CI tras el build.
//
// Se separan dos grupos, porque se cargan en momentos distintos:
//   - inicial: el JS y CSS que enlaza index.html (lo que paga cualquier visita)
//   - diferido: los chunks que se cargan bajo demanda (el mapa con MapLibre, ECharts…)
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, extname } from 'node:path';

const DIST = 'dist';
const KB = 1024;

// Límites (en KB). Referencia con MapLibre: inicial JS 276, diferido JS 1643, CSS total 98
// (la hoja de MapLibre pesa unos 60 KB sin comprimir).
const BUDGET = {
  initialJs: 300, // JS que enlaza index.html (React + shell, estado y sistema de diseño)
  initialCss: 36, // CSS que enlaza index.html (incluye tema claro y paletas para daltonismo)
  lazyJs: 2500, // resto del JS de la app (chunks diferidos)
  cssTotal: 120, // todo el CSS de la app
  htmlPage: 50, // cada página HTML
  image: 300, // cada imagen de la app
  font: 100, // cada fichero de fuente
};

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const all = walk(DIST).map((path) => ({
  path: relative(DIST, path),
  ext: extname(path).toLowerCase(),
  kb: statSync(path).size / KB,
}));
const app = all;

// Lo que enlaza index.html directamente (script de entrada, modulepreload y hojas de estilo)
const indexHtml = readFileSync(join(DIST, 'index.html'), 'utf8');
const linked = new Set(
  [...indexHtml.matchAll(/\s(?:src|href)="\/CATACLISMO\/([^"]+)"/g)].map((m) => m[1]),
);

const total = (files) => files.reduce((a, f) => a + f.kb, 0);
const isJs = (f) => ['.js', '.mjs'].includes(f.ext);
const initialJs = total(app.filter((f) => isJs(f) && linked.has(f.path)));
const lazyJs = total(app.filter((f) => isJs(f) && !linked.has(f.path)));
const initialCss = total(app.filter((f) => f.ext === '.css' && linked.has(f.path)));
const cssTotal = total(app.filter((f) => f.ext === '.css'));

const errors = [];
const fmt = (n) => `${n.toFixed(1)} KB`;
const check = (value, max, label) => {
  if (value > max) errors.push(`${label} ${fmt(value)} > ${max} KB`);
  return `${label.padEnd(14)} ${fmt(value).padStart(10)} / ${max} KB`;
};

const report = [
  check(initialJs, BUDGET.initialJs, 'JS inicial'),
  check(initialCss, BUDGET.initialCss, 'CSS inicial'),
  check(lazyJs, BUDGET.lazyJs, 'JS diferido'),
  check(cssTotal, BUDGET.cssTotal, 'CSS total'),
];

const limits = [
  [['.html'], BUDGET.htmlPage, 'página'],
  [['.png', '.jpg', '.jpeg', '.webp', '.avif', '.svg', '.gif'], BUDGET.image, 'imagen'],
  [['.woff', '.woff2', '.ttf', '.otf'], BUDGET.font, 'fuente'],
];
for (const [exts, max, what] of limits) {
  for (const f of app.filter((x) => exts.includes(x.ext))) {
    if (f.kb > max) errors.push(`${what} ${f.path}: ${fmt(f.kb)} > ${max} KB`);
  }
}

console.log(report.join('\n'));
if (errors.length) {
  console.error(`✗ Presupuesto de peso superado:\n  - ${errors.join('\n  - ')}`);
  process.exit(1);
}
console.log('✓ Dentro del presupuesto de peso');
