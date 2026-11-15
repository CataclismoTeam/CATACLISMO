// Arreglos previos a la demo: errores de carga visibles, procedencia de los datos y paneles
// que no se tapan entre sí.
import { test, expect, type Page } from '@playwright/test';

// Sin GPU el relieve 3D satura el navegador: estas pruebas usan el mapa en 2D
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

async function start(page: Page) {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
}

async function openIncidents(page: Page) {
  // El botón del rail dice si el panel ya está abierto (en escritorio empieza abierto)
  const button = page
    .getByRole('navigation', { name: 'Módulos' })
    .getByRole('button', { name: 'Incendios' });
  if ((await button.getAttribute('aria-pressed')) !== 'true') await button.click();
  return page.getByRole('complementary', { name: 'Incendios' });
}

test('si fallan los datos se dice y se puede reintentar', async ({ page }) => {
  let fail = true;
  await page.route('**/data/incidents-v1.json', (route) =>
    fail ? route.abort() : route.continue(),
  );
  await page.route('**/data/escape-routes-v1.json', (route) => route.abort());
  await start(page);
  const panel = await openIncidents(page);

  // Las vías de escape fallidas no se confunden con «no hay núcleos amenazados»
  await expect(panel.getByText(/no se han podido descargar las vías de escape/i)).toBeVisible();
  await expect(panel.getByText(/no encontró núcleos/)).toHaveCount(0);

  await expect(panel.getByText(/no se han podido descargar los incendios/i)).toBeVisible();
  fail = false;
  await panel
    .getByRole('alert')
    .filter({ hasText: 'incendios' })
    .getByRole('button', { name: 'Reintentar' })
    .click();
  await expect(panel.getByLabel('Comunidad autónoma')).toBeVisible();
});

type Box = { x: number; y: number; width: number; height: number };
const overlap = (a: Box, b: Box) =>
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;

test('las fichas no tapan los paneles ni el botón de capas', async ({ page }, info) => {
  test.skip(info.project.name === 'movil', 'en móvil las fichas cierran el panel lateral');
  await start(page);
  const panel = await openIncidents(page);
  await panel.getByLabel('Comunidad autónoma').selectOption({ index: 1 });
  await panel.locator('li button').filter({ hasText: 'detecciones' }).first().click();
  const card = page.getByRole('region', { name: /^Incendio / });
  await expect(card).toBeVisible();
  const layersButton = page.getByRole('button', { name: 'Capas', exact: true });
  expect(overlap((await card.boundingBox())!, (await layersButton.boundingBox())!)).toBe(false);

  await layersButton.click();
  const layers = page.getByRole('complementary', { name: 'Capas del mapa' });
  expect(overlap((await card.boundingBox())!, (await layers.boundingBox())!)).toBe(false);

  // Ficha de unidad con el panel de unidades abierto: va a su derecha
  await page
    .getByRole('navigation', { name: 'Módulos' })
    .getByRole('button', { name: 'Unidades' })
    .click();
  const units = page.getByRole('complementary', { name: 'Unidades' });
  await units.getByRole('button', { name: /AB-11/ }).click();
  const unitCard = page.getByRole('region', { name: /Ficha de/ });
  await expect(unitCard).toBeVisible();
  expect(overlap((await unitCard.boundingBox())!, (await units.boundingBox())!)).toBe(false);
  await page.screenshot({ path: 'test-results/solapes.png' });
});
