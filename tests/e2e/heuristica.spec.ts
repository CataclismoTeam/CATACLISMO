// Arreglos de la evaluación heurística (docs/evaluacion-heuristica.md): control del usuario,
// prevención de errores, estándares de accesibilidad.
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

test('los atajos 1 y 2 no actúan con un diálogo abierto', async ({ page }) => {
  await page.goto('./');
  await expect(page.getByRole('dialog', { name: 'CATACLISMO' })).toBeVisible();
  await page.keyboard.press('2');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await expect(page.getByRole('radio', { name: '2D' })).toHaveAttribute('aria-checked', 'true');
  // Sin diálogo, el atajo sí funciona
  await page.locator('body').press('2');
  await expect(page.getByRole('radio', { name: '3D' })).toHaveAttribute('aria-checked', 'true');
});

test('ajustes y radio se cierran con Esc o pulsando fuera', async ({ page }) => {
  await start(page);
  const settingsButton = page.getByRole('button', { name: 'Ajustes' });
  await settingsButton.click();
  const settings = page.getByRole('complementary', { name: 'Ajustes' });
  await expect(settings).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(settings).toBeHidden();
  await expect(settingsButton).toBeFocused();

  await page.getByRole('button', { name: 'Radio', exact: true }).click();
  const radio = page.getByRole('complementary', { name: 'Radio' });
  await expect(radio).toBeVisible();
  await page.getByRole('heading', { name: /Actividad de fuego/ }).click();
  await expect(radio).toBeHidden();
});

test('el panel de capas se cierra con Esc y devuelve el foco', async ({ page }) => {
  await start(page);
  const button = page.getByRole('button', { name: 'Capas', exact: true });
  await button.click();
  const layers = page.getByRole('complementary', { name: 'Capas del mapa' });
  await layers.getByRole('radio', { name: 'Topográfico' }).focus();
  await page.keyboard.press('Escape');
  await expect(layers).toBeHidden();
  await expect(button).toBeFocused();
});

test('las pestañas de unidades se recorren con las flechas', async ({ page }) => {
  await start(page);
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  await rail.getByRole('button', { name: 'Unidades' }).click();
  const tabs = page.getByRole('tablist', { name: 'Dominio' });
  const ground = tabs.getByRole('tab', { name: /Tierra/ });
  await ground.focus();
  await page.keyboard.press('ArrowLeft');
  const air = tabs.getByRole('tab', { name: /Aire/ });
  await expect(air).toBeFocused();
  await expect(air).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('tabpanel', { name: /Aire/ })).toBeVisible();
});

test('el primer Tab ofrece saltar al mapa', async ({ page }) => {
  await start(page);
  await page.locator('body').focus();
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Saltar al mapa' });
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#mapa-principal')).toBeFocused();
});
