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
  const toggle = page.getByRole('button', { name: /^(Plegar|Desplegar)$/ });
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
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
  // El relieve 3D se pinta por software en el CI: con varios tests a la vez va lento
  test.slow();
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  await expect(page.getByTestId('mapa').locator('canvas').first()).toBeVisible({ timeout: 30_000 });
  const mode = page.getByRole('radiogroup', { name: 'Modo del mapa' });
  await expect(mode.getByRole('radio', { name: '2D' })).toHaveAttribute('aria-checked', 'true');
  // dispatchEvent: sin GPU el 3D satura la página y un clic normal esperaría a que se estabilice
  await mode.getByRole('radio', { name: '3D' }).dispatchEvent('click');
  await expect(mode.getByRole('radio', { name: '3D' })).toHaveAttribute('aria-checked', 'true', {
    timeout: 30_000,
  });
  await mode.getByRole('radio', { name: '2D' }).dispatchEvent('click');
  await expect(mode.getByRole('radio', { name: '2D' })).toHaveAttribute('aria-checked', 'true', {
    timeout: 30_000,
  });
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

test('los incendios detectados se filtran por comunidad y se abren en el mapa', async ({
  page,
}) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  // El panel vive dentro del mapa, que carga al cerrar el briefing: se espera a que esté
  await expect(page.getByTestId('mapa')).toBeVisible();
  const panel = page.getByRole('complementary', { name: 'Incendios' });
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  const button = rail.getByRole('button', { name: 'Incendios' });
  if ((await button.getAttribute('aria-pressed')) !== 'true') await button.click();
  await expect(panel.getByText('Real · FIRMS')).toBeVisible();
  await panel.getByLabel('Comunidad autónoma').selectOption('Andalucía');
  const first = panel.getByRole('button', { name: /detecciones/ }).first();
  await first.click();
  const card = page.getByRole('region', { name: /Incendio INC-/ });
  await expect(card).toContainText('Andalucía');
  await expect(card).toContainText('Real · NASA FIRMS');
  await expect(card.getByRole('button', { name: 'Cerrar ficha del incendio' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(card).toBeHidden();
});

test('el botón Incendios del rail abre y cierra su panel', async ({ page }) => {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  test.skip(!(await rail.isVisible()), 'el rail solo se muestra en pantallas anchas');
  const button = rail.getByRole('button', { name: 'Incendios' });
  const panel = page.getByRole('complementary', { name: 'Incendios' });
  await expect(button).toHaveAttribute('aria-pressed', 'true');
  await expect(panel).toBeVisible();
  await button.click();
  await expect(panel).toBeHidden();
  await expect(button).toHaveAttribute('aria-pressed', 'false');
  await button.click();
  await expect(panel).toBeVisible();
  await expect(rail.getByRole('button', { name: 'Histórico' })).toHaveCount(0);
});
