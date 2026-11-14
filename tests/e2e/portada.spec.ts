// Tests end-to-end sobre el build real (dist/), servido como en GitHub Pages
import { test, expect } from '@playwright/test';

test('la portada explica qué es y deja entrar sin errores', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await expect(page).toHaveTitle('CATACLISMO');

  // Briefing inicial: propósito, público y acción principal
  const briefing = page.getByRole('dialog', { name: 'CATACLISMO' });
  await expect(briefing).toContainText('Plataforma de mando para emergencias');
  await briefing.getByRole('button', { name: 'Ver el calendario de fuego' }).click();
  await expect(briefing).toBeHidden();

  await expect(page.getByRole('heading', { level: 1, name: 'CATACLISMO' })).toBeVisible();
  await expect(page.getByRole('heading', { name: /Actividad de fuego/ })).toBeVisible();
  expect(errors).toEqual([]);
});

test('el briefing no vuelve a salir y se puede reabrir', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Cerrar' }).click();
  await page.reload();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByRole('button', { name: 'Qué es CATACLISMO' }).click();
  await expect(page.getByRole('dialog', { name: 'CATACLISMO' })).toBeVisible();
});

test('el mapa (Cesium) se carga bajo demanda', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await page.getByRole('dialog').getByRole('button', { name: 'Abrir el mapa' }).click();
  // Cesium monta su canvas WebGL dentro del contenedor del globo
  await expect(page.getByTestId('globo').locator('canvas').first()).toBeVisible({
    timeout: 30_000,
  });
  expect(errors).toEqual([]);
});

test('una ruta inexistente muestra la 404 propia', async ({ page }) => {
  const response = await page.goto('no-existe');
  expect(response?.status()).toBe(404);
  await expect(page.locator('#no-encontrada')).toBeVisible();
});
