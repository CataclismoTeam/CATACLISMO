// Tests end-to-end sobre el build real (dist/), servido como en GitHub Pages
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
  const toggle = page.getByRole('button', { name: 'Desplegar' });
  if (await toggle.isVisible()) await toggle.click();
  await expect(page.getByRole('table')).toBeVisible();
}

test('la portada explica qué es y deja entrar sin errores', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await expect(page).toHaveTitle('CATACLISMO');

  // Briefing inicial: propósito, público y acción principal
  const briefing = page.getByRole('dialog', { name: 'CATACLISMO' });
  await expect(briefing).toContainText('Plataforma de mando para emergencias');
  await briefing.getByRole('button', { name: 'Empezar' }).click();
  await expect(briefing).toBeHidden();

  await expect(page.getByRole('heading', { level: 1, name: 'CATACLISMO' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Actividad de fuego/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test('el briefing no vuelve a salir y se puede reabrir', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Cerrar' }).click();
  await page.reload();
  await openCalendar(page);
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByRole('button', { name: 'Qué es CATACLISMO' }).click();
  await expect(page.getByRole('dialog', { name: 'CATACLISMO' })).toBeVisible();
});

test('el mapa se carga sin pedirlo y cambia entre 2D y 3D', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await expect(page.getByTestId('mapa').locator('canvas').first()).toBeVisible({ timeout: 30_000 });
  const mode = page.getByRole('radiogroup', { name: 'Modo del mapa' });
  await expect(mode.getByRole('radio', { name: '2D' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('2');
  await expect(mode.getByRole('radio', { name: '3D' })).toHaveAttribute('aria-checked', 'true');
  await mode.getByRole('radio', { name: '2D' }).click();
  await expect(mode.getByRole('radio', { name: '2D' })).toHaveAttribute('aria-checked', 'true');
  expect(errors).toEqual([]);
});

test('una capa se oculta y se vuelve a mostrar', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  const panel = page.getByRole('complementary', { name: 'Capas del mapa' });
  if (!(await panel.isVisible())) await page.getByRole('button', { name: 'Capas' }).click();
  const layer = panel.getByRole('button', { name: /Propagación prevista/ });
  await expect(layer).toHaveAttribute('aria-pressed', 'true');
  await layer.click();
  await expect(layer).toHaveAttribute('aria-pressed', 'false');
  await layer.click();
  await expect(layer).toHaveAttribute('aria-pressed', 'true');
});

test('una ruta inexistente muestra la 404 propia', async ({ page }) => {
  const response = await page.goto('no-existe');
  expect(response?.status()).toBe(404);
  await expect(page.locator('#no-encontrada')).toBeVisible();
});
