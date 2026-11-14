// Unidades por aire, tierra y mar; radio por grupos; ajustes de tema y accesibilidad.
import { test, expect, type Page } from '@playwright/test';

// Sin GPU el relieve 3D satura el navegador: estas pruebas usan el mapa en 2D
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

async function start(page: Page) {
  await page.goto('./');
  await page.getByRole('button', { name: 'Empezar' }).click();
}

test('las unidades se separan en aire, tierra y mar, y tierra va por grupos', async ({ page }) => {
  await start(page);
  const rail = page.getByRole('navigation', { name: 'Módulos' });
  // Escritorio: botón del rail. Móvil: barra del mapa (ningún panel abierto al empezar)
  if (await rail.isVisible()) await rail.getByRole('button', { name: 'Unidades' }).click();
  else await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Unidades' });
  const tabs = panel.getByRole('tablist', { name: 'Dominio' });
  await expect(tabs.getByRole('tab', { name: /Aire/ })).toBeVisible();
  await expect(tabs.getByRole('tab', { name: /Tierra/ })).toHaveAttribute('aria-selected', 'true');
  // La simulación inicial (Sierra Bermeja) es costera: tiene medios de mar
  await expect(tabs.getByRole('tab', { name: /Mar/ })).toBeVisible();

  const count = async (name: RegExp) =>
    Number((await tabs.getByRole('tab', { name }).innerText()).match(/\((\d+)\)/)?.[1]);
  expect(await count(/Tierra/)).toBeGreaterThan(await count(/Aire/));
  expect(await count(/Tierra/)).toBeGreaterThan(await count(/Mar/));

  await expect(panel.getByText('Canal General Tierra')).toBeVisible();
  await expect(panel.getByRole('heading', { name: /Grupo 1 · Ataque directo/ })).toBeVisible();

  await panel.getByRole('button', { name: /AB-11/ }).click();
  await expect(page.getByRole('region', { name: /Ficha de Autobomba forestal/ })).toContainText(
    'Tierra · Grupo 1 · Ataque directo',
  );
});

test('la radio tiene canal de aire, general de tierra, uno por grupo y mar', async ({ page }) => {
  await start(page);
  await page.getByRole('button', { name: 'Radio', exact: true }).click();
  const radio = page.getByRole('complementary', { name: 'Radio' });
  for (const name of [
    'Coordinación aérea',
    'General Tierra',
    'Grupo 2 · Flanco',
    'Salvamento marítimo',
  ]) {
    await expect(radio.getByRole('radio', { name: new RegExp(name) })).toBeVisible();
  }
  await expect(radio.getByRole('button', { name: 'Pulsar para hablar' })).toBeDisabled();
});

test('los ajustes cambian el tema y activan el modo para daltonismo', async ({ page }) => {
  await start(page);
  const html = page.locator('html');
  await expect(html).toHaveAttribute('data-theme', 'oscuro');
  await page.getByRole('button', { name: 'Ajustes' }).click();
  const settings = page.getByRole('complementary', { name: 'Ajustes' });
  await settings.getByRole('radio', { name: 'Claro' }).click();
  await expect(html).toHaveAttribute('data-theme', 'claro');
  await settings.getByRole('radio', { name: /Deuteranopía/ }).click();
  await expect(html).toHaveAttribute('data-cvd', 'deuteranopia');
  // Se recuerda al volver a entrar
  await page.reload();
  await expect(html).toHaveAttribute('data-theme', 'claro');
  await expect(html).toHaveAttribute('data-cvd', 'deuteranopia');
});

test('el mapa base solo ofrece satélite y topográfico', async ({ page }) => {
  await start(page);
  await page.getByRole('button', { name: 'Capas', exact: true }).click();
  const base = page.getByRole('radiogroup', { name: 'Mapa base' });
  await expect(base.getByRole('radio')).toHaveCount(2);
  await expect(base.getByRole('radio', { name: 'Oscuro' })).toHaveCount(0);
});
