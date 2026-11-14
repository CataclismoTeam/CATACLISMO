// Tests end-to-end sobre el build real (dist/), servido como en GitHub Pages
import { test, expect } from '@playwright/test';

test('la portada carga con el título y sin errores', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await expect(page).toHaveTitle('CATACLISMO');
  await expect(page.getByRole('heading', { level: 1, name: 'CATACLISMO' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('el globo 3D (Cesium) se carga bajo demanda', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await page.getByRole('button', { name: 'Abrir globo 3D' }).click();
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
