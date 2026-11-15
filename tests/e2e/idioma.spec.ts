// Interfaz bilingüe: español por defecto e inglés para el jurado internacional.
import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

test('se cambia a inglés y el enlace compartido lo conserva', async ({ page }, info) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'es');

  // En escritorio hay botón en la barra; en móvil, dentro de Ajustes
  if (info.project.name === 'movil') {
    await page.getByRole('button', { name: 'Ajustes' }).click();
    await page.getByRole('radio', { name: 'English' }).click();
    await page.getByRole('button', { name: 'Close settings' }).click();
  } else {
    await page.getByRole('button', { name: 'Switch to English' }).click();
  }
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('button', { name: 'Layers', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Modules' })).toContainText('Fires');
  await expect(page.getByRole('button', { name: 'Maximise' })).toBeVisible();
  await expect.poll(() => new URL(page.url()).hash).toContain('l=en');

  // Un enlace con &l=en abre en inglés (también el briefing)
  // Sin nada guardado (visitante nuevo): manda el enlace. Misma URL con hash: hay que recargar
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
  await expect(page.getByRole('button', { name: 'Start' })).toBeVisible();
});
