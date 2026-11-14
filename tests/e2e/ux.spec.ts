// "Alerta roja" de la Ruta de lanzamiento (docs/ux-ruta-de-lanzamiento.md): en las pantallas
// del flujo principal no puede verse texto de relleno ni errores técnicos.
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

const FORBIDDEN = /undefined|NaN|lorem|Error 500|\[object Object\]|Título aquí|asdf/i;

async function expectClean(page: Page, screen: string) {
  const text = await page.locator('body').innerText();
  expect(text.match(FORBIDDEN)?.[0], `texto prohibido en "${screen}"`).toBeUndefined();
}

test('ninguna pantalla del flujo principal muestra relleno ni errores técnicos', async ({
  page,
}) => {
  await page.goto('./');
  await expect(page.getByRole('dialog', { name: 'CATACLISMO' })).toBeVisible();
  await expectClean(page, 'briefing');

  await page.getByRole('button', { name: 'Empezar' }).click();
  await openCalendar(page);
  await expect(page.getByRole('img', { name: /Detecciones de/ })).toBeVisible();
  await expectClean(page, 'calendario de España');

  for (const area of ['Sierra Bermeja (Málaga)', 'Canarias']) {
    await page.getByLabel('Área de interés').selectOption(area);
    await expect(page.getByText(/celdas de 5 km, \d+ con detecciones/)).toBeVisible();
    await expectClean(page, `calendario de ${area}`);
  }

  // Meses con mediana cero, parciales y con pocos años de referencia
  await page.getByRole('button', { name: /^enero de 2012:/ }).click();
  await expectClean(page, 'mes parcial');
  await page.getByLabel('Desde').selectOption('2024');
  await expectClean(page, 'rango corto');

  await page.getByLabel('Serie').selectOption('Solo VIIRS');
  await expectClean(page, 'serie VIIRS');

  await page.getByRole('button', { name: 'Cómo se armonizan los datos' }).click();
  await expect(page.getByRole('dialog')).toContainText('Limitaciones');
  await expectClean(page, 'metodología');
});

test('el texto principal no baja de 14 px y los botones se pueden pulsar', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await openCalendar(page);
  const bodySize = await page.evaluate(() => parseFloat(getComputedStyle(document.body).fontSize));
  expect(bodySize).toBeGreaterThanOrEqual(14);
  for (const name of ['Descargar CSV', 'Descargar PNG', 'Plegar']) {
    const box = await page.getByRole('button', { name }).boundingBox();
    expect(box?.height, name).toBeGreaterThanOrEqual(36);
  }
});
