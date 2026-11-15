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

async function openCalendar(page: Page) {
  const toggle = page.getByRole('button', { name: /^(Plegar|Desplegar)$/ });
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
  await expect(page.getByRole('table')).toBeVisible();
}

test('pulsar un mes del calendario pinta su actividad en el mapa', async ({ page }) => {
  await start(page);
  await openCalendar(page);
  await page.getByRole('button', { name: /^septiembre de 2021:/ }).click();
  const label = page.getByRole('status', { name: 'Capa del mes del calendario' });
  await expect(label).toContainText(/Real · FIRMS · septiembre de 2021/i);
  await expect(label).not.toContainText('cargando');

  // El interruptor del panel de capas la apaga
  await page.getByRole('button', { name: 'Capas', exact: true }).click();
  const toggle = page.getByRole('button', { name: /Actividad del mes del calendario/ });
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await toggle.click();
  await expect(label).toBeHidden();
});

test('dibujar un área en el mapa cambia el calendario', async ({ page }) => {
  await start(page);
  await openCalendar(page);
  // Un poco más lejos para que el área abarque varias celdas de 5 km
  const zoomOut = page.getByRole('button', { name: /Alejar|Zoom out/ });
  for (let i = 0; i < 2; i++) {
    await zoomOut.click();
    await page.waitForTimeout(350);
  }
  await page.getByRole('button', { name: 'Dibujar en el mapa' }).click();
  await expect(page.getByText('Pulsa dos esquinas del área en el mapa')).toBeVisible();

  // El calendario se pliega mientras se dibuja para dejar sitio al mapa
  await expect(page.getByRole('table')).toBeHidden();
  const map = page.getByTestId('mapa');
  const box = (await map.boundingBox())!;
  await map.click({ position: { x: box.width * 0.45, y: box.height * 0.45 } });
  await map.click({ position: { x: box.width * 0.6, y: box.height * 0.6 } });

  await expect(page.getByLabel('Área de interés')).toHaveValue('Área dibujada');
  await expect(page.getByText(/km² · \d+ celdas de 5 km, [1-9]\d* con detecciones/)).toBeVisible();
  await expect(page.getByText('Pulsa dos esquinas del área en el mapa')).toBeHidden();
  // Al terminar vuelve a abrirse el calendario, ya con el área nueva
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Ver en el mapa' })).toBeVisible();
});
