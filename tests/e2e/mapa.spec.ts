// Mejoras del mapa (front v2): línea de tiempo del fuego, calendario ↔ mapa, avisos, buscar,
// medir y compartir. Con el mapa en 2D: sin GPU el relieve 3D satura el navegador.
import { test, expect, type Page } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

async function start(page: Page) {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
}

test('la línea de tiempo cambia la hora del incendio simulado', async ({ page }) => {
  await start(page);
  const timeline = page.getByRole('region', { name: 'Línea de tiempo del incendio' });
  await expect(timeline).toBeVisible();
  const hour = timeline.locator('output');
  await expect(hour).toHaveText('T+1 h');

  await timeline.getByRole('slider').fill('3');
  await expect(hour).toHaveText('T+3 h');

  // Reproducir avanza la hora y se puede pausar
  await timeline.getByRole('button', { name: 'Reproducir' }).click();
  await expect(hour).not.toHaveText('T+3 h');
  await timeline.getByRole('button', { name: 'Pausar' }).click();
  await expect(timeline.getByRole('button', { name: 'Reproducir' })).toBeVisible();
});

test('de lejos no hay línea de tiempo', async ({ page }) => {
  // España entera (zoom 5.5): solo iconos, nada que animar
  await page.goto('./#sim=bermeja&z=5.5&c=-4.00000,40.00000&m=2d');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await expect(page.getByRole('toolbar', { name: 'Herramientas del mapa' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Línea de tiempo del incendio' })).toBeHidden();
});

async function openCalendar(page: Page) {
  const toggle = page.getByRole('button', { name: /^(Plegar|Desplegar)$/ });
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
  await expect(page.getByRole('table')).toBeVisible();
}

test('pulsar un mes del calendario pinta su actividad en el mapa', async ({ page }) => {
  await start(page);
  await openCalendar(page);
  await page.getByRole('button', { name: /^septiembre de 2021:/ }).click();
  const label = page.getByRole('status', { name: 'Capa del mes del calendario' });
  await expect(label).toContainText(/Real · FIRMS · septiembre de 2021/i);
  await expect(label).not.toContainText('cargando');

  // El interruptor del panel de capas la apaga
  await page.getByRole('button', { name: 'Capas', exact: true }).click();
  const toggle = page.getByRole('button', { name: /Actividad del mes del calendario/ });
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click();
  await expect(label).toBeHidden();
});

test('dibujar un área en el mapa cambia el calendario', async ({ page }) => {
  await start(page);
  await openCalendar(page);
  // Un poco más lejos para que el área abarque varias celdas de 5 km
  const zoomOut = page.getByRole('button', { name: /Alejar|Zoom out/ });
  for (let i = 0; i < 2; i++) {
    await zoomOut.click();
    await page.waitForTimeout(350);
  }
  await page.getByRole('button', { name: 'Dibujar en el mapa' }).click();
  await expect(page.getByText('Pulsa dos esquinas del área en el mapa')).toBeVisible();

  // El calendario se pliega mientras se dibuja para dejar sitio al mapa
  await expect(page.getByRole('table')).toBeHidden();
  const map = page.getByTestId('mapa');
  const box = (await map.boundingBox())!;
  await map.click({ position: { x: box.width * 0.45, y: box.height * 0.45 } });
  await map.click({ position: { x: box.width * 0.6, y: box.height * 0.6 } });

  await expect(page.getByLabel('Área de interés')).toHaveValue('Área dibujada');
  await expect(page.getByText(/km² · \d+ celdas de 5 km, [1-9]\d* con detecciones/)).toBeVisible();
  await expect(page.getByText('Pulsa dos esquinas del área en el mapa')).toBeHidden();
  // Al terminar vuelve a abrirse el calendario, ya con el área nueva
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ver en el mapa' })).toBeVisible();
});

test('los avisos se ordenan por la llegada del fuego y encuadran su ruta', async ({ page }) => {
  await start(page);
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  const incidents = rail.getByRole('button', { name: 'Incendios' });
  if ((await incidents.getAttribute('aria-pressed')) !== 'true') await incidents.click();
  await page
    .getByRole('complementary', { name: 'Incendios' })
    .getByRole('button', { name: /Interfaz urbano-forestal de Estepona/ })
    .click();

  // Estepona: un núcleo con margen de 29 min (crítico); el rail lo cuenta
  const alertsButton = rail.getByRole('button', { name: /Avisos/ });
  await expect(alertsButton).toContainText('1');
  await alertsButton.click();
  const panel = page.getByRole('complementary', { name: 'Avisos' });
  const items = panel.getByRole('list', { name: 'Núcleos en riesgo' }).getByRole('button');
  await expect(items).toHaveCount(3);
  await expect(items.nth(0)).toContainText('Valle Romano');
  await expect(items.nth(0)).toContainText('Crítico');
  await expect(items.nth(1)).toContainText('Alto');
  await expect(items.nth(2)).toContainText('Vigilancia');

  await items.nth(0).click();
  await expect(items.nth(0)).toHaveAttribute('aria-pressed', 'true');
});

const hashParam = (url: string, key: string) =>
  new URLSearchParams(new URL(url).hash.slice(1)).get(key);

test('buscar unas coordenadas lleva el mapa allí', async ({ page }) => {
  await start(page);
  // En escritorio el buscador va en la barra; en móvil se abre desde el mapa (ya cargado)
  await expect(page.getByRole('toolbar', { name: 'Herramientas del mapa' })).toBeVisible();
  const search = page.getByRole('search', { name: 'Buscar en el mapa' });
  if (!(await search.isVisible())) await page.getByRole('button', { name: 'Buscar' }).click();
  await search.getByRole('searchbox').fill('37.18, -3.6');
  await search.getByRole('searchbox').press('Enter');
  await expect
    .poll(() => hashParam(page.url(), 'c'), { timeout: 10_000 })
    .toMatch(/^-3\.6\d*,37\.1[78]\d*$/);
});

test('la regla mide distancias en km y superficies', async ({ page }) => {
  await start(page);
  await page.getByRole('button', { name: 'Medir' }).click();
  const ruler = page.getByRole('region', { name: 'Regla' });
  await expect(ruler).toBeVisible();
  const map = page.getByTestId('mapa');
  const box = (await map.boundingBox())!;
  const at = (x: number, y: number) => ({ position: { x: box.width * x, y: box.height * y } });
  await map.click(at(0.3, 0.35));
  await map.click(at(0.7, 0.35));
  await expect(ruler).toContainText(/Distancia\s*[\d,]+ (km|m)/);
  await map.click(at(0.7, 0.55));
  await ruler.getByRole('button', { name: 'Cerrar área' }).click();
  await expect(ruler).toContainText(/Superficie\s*[\d,]+ (ha|km²)/);
  await page.keyboard.press('Escape');
  await expect(ruler).toBeHidden();
});

test('un enlace con hash restaura la simulación y el encuadre', async ({ page }) => {
  await page.goto('./#sim=estepona&z=12.5&c=-5.15000,36.45000&m=2d');
  await page.getByRole('button', { name: 'Empezar' }).click();
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  const incidents = rail.getByRole('button', { name: 'Incendios' });
  if ((await incidents.getAttribute('aria-pressed')) !== 'true') await incidents.click();
  await expect(
    page
      .getByRole('complementary', { name: 'Incendios' })
      .getByRole('button', { name: /Interfaz urbano-forestal de Estepona/ }),
  ).toHaveAttribute('aria-pressed', 'true');
  // El mapa no vuela a la cámara de la simulación: conserva la del enlace
  await page.waitForTimeout(1500);
  expect(hashParam(page.url(), 'sim')).toBe('estepona');
  expect(hashParam(page.url(), 'z')).toBe('12.5');
  expect(hashParam(page.url(), 'c')).toBe('-5.15000,36.45000');
});

test('copiar enlace avisa de que se ha copiado', async ({ page, context, browserName }) => {
  test.skip(browserName !== 'chromium', 'permisos de portapapeles solo en Chromium');
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await start(page);
  await page.getByRole('button', { name: 'Copiar enlace' }).click();
  await expect(page.getByText('Enlace copiado')).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain('#sim=');
});
