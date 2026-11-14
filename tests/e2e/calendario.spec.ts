// Flujo del reto: elegir un área, ver el calendario, comparar un mes con su mediana,
// descargar los datos y consultar la metodología.
import { readFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';

// Sin GPU (CI y navegador sin ventana) el relieve 3D se pinta por software y satura la página:
// las pruebas arrancan el mapa en 2D, salvo la que comprueba el cambio de modo.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

/** En pantallas estrechas el calendario empieza plegado: se despliega si hace falta. */
async function openCalendar(page: Page) {
  const toggle = page.getByRole('button', { name: /^(Plegar|Desplegar)$/ });
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
  await expect(page.getByRole('table')).toBeVisible();
}

async function enter(page: Page) {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await openCalendar(page);
}

test('el calendario muestra toda la serie y avisa del mes incompleto', async ({ page }) => {
  await enter(page);
  const table = page.getByRole('table');
  await expect(table.getByRole('rowheader', { name: '2012' })).toBeVisible();
  await expect(table.getByRole('rowheader', { name: '2026' })).toBeVisible();
  // Mes en curso: se compara con la mediana y se avisa de que está a medias
  await expect(page.getByRole('heading', { name: 'Noviembre de 2026' })).toBeVisible();
  await expect(page.getByText(/Mes incompleto: hay datos de 2 de 30 días/)).toBeVisible();
  await page.getByRole('button', { name: /último mes completo/ }).click();
  await expect(page.getByRole('heading', { name: 'Octubre de 2026' })).toBeVisible();
});

test('un área propia cambia el calendario y la anomalía', async ({ page }) => {
  await enter(page);
  await page.getByLabel('Área de interés').selectOption('Sierra Bermeja (Málaga)');
  await expect(page.getByText(/celdas de 5 km, \d+ con detecciones/)).toBeVisible();

  // El incendio de Sierra Bermeja de septiembre de 2021 debe destacar
  await page.getByRole('button', { name: /^septiembre de 2021:/ }).click();
  await expect(page.getByRole('heading', { name: 'Septiembre de 2021' })).toBeVisible();
  await expect(page.getByText('Muy por encima')).toBeVisible();

  await page.getByLabel('Área de interés').selectOption('personalizada');
  await page.getByLabel('Latitud').fill('95');
  await page.getByRole('button', { name: 'Aplicar área' }).click();
  await expect(page.getByRole('alert')).toContainText('fuera de los datos');

  // Un punto en el mar no tiene detecciones: la pantalla vacía dice qué hacer
  await page.getByLabel('Latitud').fill('36.0');
  await page.getByLabel('Longitud').fill('2.0');
  await page.getByRole('textbox', { name: /^Radio/ }).fill('5');
  await page.getByRole('button', { name: 'Aplicar área' }).click();
  await expect(page.getByText(/Sin detecciones en esta área/)).toBeVisible();
});

test('se descargan el CSV y el PNG de la búsqueda', async ({ page }) => {
  await enter(page);
  await page.getByLabel('Área de interés').selectOption('Andalucía');
  await page.getByLabel('Desde').selectOption('2020');

  const csvButton = page.getByRole('button', { name: 'Descargar CSV' });
  await expect(csvButton).toBeEnabled();
  const [csv] = await Promise.all([page.waitForEvent('download'), csvButton.click()]);
  expect(csv.suggestedFilename()).toBe('cataclismo-fuego_andalucia_2020-2026.csv');
  const text = await readFile(await csv.path(), 'utf8');
  const lines = text.trimEnd().split('\r\n');
  expect(lines[0]).toContain(
    'sensor_origen,conteo_bruto_modis,conteo_bruto_viirs,conteo_armonizado',
  );
  expect(lines[1]).toMatch(/^2020-01-01,2020,1,MODIS\+VIIRS,\d+,\d+,[\d.]+,/);
  expect(lines).toHaveLength(1 + 6 * 12 + 11); // 2020-2025 completos + 11 meses de 2026

  const [png] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Descargar PNG' }).click(),
  ]);
  expect(png.suggestedFilename()).toBe('cataclismo-fuego_andalucia_2020-2026.png');
});

test('la metodología explica la armonización y se cierra con Esc', async ({ page }) => {
  await enter(page);
  await page.getByRole('button', { name: 'Cómo se armonizan los datos' }).click();
  const dialog = page.getByRole('dialog', { name: 'Cómo se armonizan los datos' });
  await expect(dialog).toContainText('NASA FIRMS');
  await expect(dialog).toContainText('Factor k por mes del año');
  await expect(dialog).toContainText('Limitaciones');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
});
