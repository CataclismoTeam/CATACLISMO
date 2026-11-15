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
