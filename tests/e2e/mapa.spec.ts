// Mejoras del mapa (front v2): línea de tiempo del fuego, calendario ↔ mapa, avisos, buscar,
// medir y compartir. Con el mapa en 2D: sin GPU el relieve 3D satura el navegador.
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

test('la línea de tiempo cambia la hora del incendio simulado', async ({ page }) => {
  await start(page);
  const timeline = page.getByRole('region', { name: 'Línea de tiempo del incendio' });
  await expect(timeline).toBeVisible();
  const hour = timeline.locator('output');
  await expect(hour).toHaveText('T+1 h');

  await timeline.getByRole('slider').fill('3');
  await expect(hour).toHaveText('T+3 h');

  // Reproducir avanza la hora y se puede pausar
  await timeline.getByRole('button', { name: 'Reproducir' }).click();
  await expect(hour).not.toHaveText('T+3 h');
  await timeline.getByRole('button', { name: 'Pausar' }).click();
  await expect(timeline.getByRole('button', { name: 'Reproducir' })).toBeVisible();

  // De lejos (España entera) no hay nada que animar
  const zoomOut = page.getByRole('button', { name: /Alejar|Zoom out/ });
  for (let i = 0; i < 6; i++) {
    await zoomOut.click();
    await page.waitForTimeout(350); // cada clic anima el zoom
  }
  await expect(timeline).toBeHidden();
});
