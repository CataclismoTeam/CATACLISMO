// Regresión visual de la portada, comparada con una captura de referencia.
// Solo en el CI: las referencias se generan en el mismo entorno (Ubuntu + Chromium de Playwright),
// porque el renderizado de fuentes cambia entre sistemas. Actualizar: ver tests/visual/README.md
import { test, expect } from '@playwright/test';

test.describe('regresión visual', () => {
  test.skip(!process.env.CI && !process.env.VISUAL, 'solo en el CI (o con VISUAL=1)');

  test('portada', async ({ page }) => {
    await page.goto('./');
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot('portada.png', {
      animations: 'disabled',
      caret: 'hide',
      // Aquí irá lo que cambie solo (datos en tiempo real, fechas...)
      mask: [page.locator('[data-dinamico]')],
      maxDiffPixelRatio: 0.01,
    });
  });
});
