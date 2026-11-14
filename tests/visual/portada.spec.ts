// Regresión visual de la portada, comparada con una captura de referencia.
// Solo en el CI: las referencias se generan en el mismo entorno (Ubuntu + Chromium de Playwright),
// porque el renderizado de fuentes cambia entre sistemas. Actualizar: ver tests/visual/README.md
import { test, expect } from '@playwright/test';

test.describe('regresión visual', () => {
  test.skip(!process.env.CI && !process.env.VISUAL, 'solo en el CI (o con VISUAL=1)');

  // Sin GPU (CI y navegador sin ventana) el relieve 3D se pinta por software y satura la página:
  // las pruebas arrancan el mapa en 2D, salvo la que comprueba el cambio de modo.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() =>
      window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
    );
  });

  test('portada', async ({ page }) => {
    await page.goto('./');
    await page.evaluate(() => document.fonts.ready);
    // La portada es el briefing sobre el calendario ya cargado
    await expect(page.getByRole('dialog', { name: 'CATACLISMO' })).toBeVisible();
    // En móvil el calendario empieza plegado: basta con que su barra esté pintada
    await expect(page.locator('#calendario-titulo')).toBeVisible();
    await expect(page).toHaveScreenshot('portada.png', {
      animations: 'disabled',
      caret: 'hide',
      // Aquí irá lo que cambie solo (datos en tiempo real, fechas...)
      mask: [page.locator('[data-dinamico]')],
      maxDiffPixelRatio: 0.01,
    });
  });

  test('calendario', async ({ page }) => {
    await page.goto('./');
    await page.getByRole('button', { name: 'Empezar' }).click();
    const toggle = page.getByRole('button', { name: /^(Plegar|Desplegar)$/ });
    if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
    await expect(page.getByRole('img', { name: /Detecciones de/ })).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot('calendario.png', {
      animations: 'disabled',
      caret: 'hide',
      // El mapa (teselas de red) cambia entre ejecuciones: se enmascara
      mask: [page.locator('[data-dinamico]'), page.getByRole('region', { name: 'Mapa' })],
      maxDiffPixelRatio: 0.01,
    });
  });
});
