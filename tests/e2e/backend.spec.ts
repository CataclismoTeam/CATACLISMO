// Conexión opcional con el backend (FastAPI). El CI no levanta la API: se simula con page.route.
import { test, expect, type Page } from '@playwright/test';

const API = 'http://api.prueba:8000';

const lucia = {
  type: 'FeatureCollection',
  metadata: {
    total_routes_generated: 1,
    zones: [{ zone_id: 'Z1', predicted_date: '2022-07-18 12:00' }],
  },
  features: [
    {
      type: 'Feature',
      properties: { feature_type: 'fire_cell', fire_zone_category: 'BURNING_ACTIVE' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [-6, 41.7],
            [-5.99, 41.7],
            [-5.99, 41.71],
            [-6, 41.71],
            [-6, 41.7],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { feature_type: 'evacuation_route', profile: 'human', distance_km: 3 },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-6, 41.7],
          [-5.95, 41.75],
        ],
      },
    },
  ],
};

const juli = {
  type: 'FeatureCollection',
  metadata: {
    total_teams: 1,
    total_operators: 1,
    proof_of_life: { active_alerts_count: 1, alerts: [{ operator_id: 'op_1' }] },
  },
  features: [
    {
      type: 'Feature',
      properties: {
        feature_type: 'field_operator',
        operator_id: 'op_1',
        callsign: 'ALFA-1',
        name: 'Ana',
        status: 'en_terreno',
      },
      geometry: { type: 'Point', coordinates: [-5.97, 41.72] },
    },
  ],
};

async function mockApi(page: Page, up = true) {
  await page.route(`${API}/**`, (route) => {
    if (!up) return route.abort('connectionrefused');
    const path = new URL(route.request().url()).pathname;
    const body =
      path === '/health'
        ? { status: 'ok', database: 'unavailable' }
        : path === '/api/live/status'
          ? { status: 'idle' }
          : path === '/api/lucia/routes'
            ? lucia
            : path === '/api/juli/geojson'
              ? juli
              : undefined;
    return body
      ? route.fulfill({ json: body, headers: { 'access-control-allow-origin': '*' } })
      : route.fulfill({ status: 404, json: { detail: 'no' } });
  });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() =>
    window.localStorage.setItem('cataclismo.mapa', JSON.stringify({ mode: '2d' })),
  );
});

test('sin backend la app sigue en modo demo', async ({ page }) => {
  await page.goto('./');
  await expect(page.getByText('Demo · sin conexión a backend')).toBeVisible();
  await page.getByRole('button', { name: 'Empezar' }).click();
  await page.locator('[data-abre="capas"]').first().click();
  await expect(page.getByRole('heading', { name: 'Backend' })).toHaveCount(0);
});

test('con ?api= se conecta y muestra CATA, LUCIA y JULI', async ({ page }) => {
  await mockApi(page);
  await page.goto(`./?api=${API}`);
  await expect(page.getByText('Backend conectado')).toBeVisible();
  await page.getByRole('button', { name: 'Empezar' }).click();
  await page.locator('[data-abre="capas"]').first().click();
  const layers = page.getByRole('complementary', { name: 'Capas del mapa' });
  await expect(layers.getByText('CATA · predicción neuronal')).toBeVisible();
  await expect(
    layers.getByText('1 zonas · predicción para 2022-07-18 12:00 en celdas de 1 km'),
  ).toBeVisible();
  await expect(layers.getByText(/1 equipos · 1 operarios · 1 sin prueba de vida/)).toBeVisible();
});

test('si el backend no responde se avisa y se puede desconectar', async ({ page }) => {
  await mockApi(page, false);
  await page.goto(`./?api=${API}`);
  await page.getByRole('button', { name: 'Empezar' }).click();
  await page.locator('[data-abre="ajustes"]').first().click();
  const settings = page.getByRole('complementary', { name: 'Ajustes' });
  await expect(
    settings.getByRole('status').filter({ hasText: 'El backend no responde' }),
  ).toBeVisible();
  await settings.getByRole('button', { name: 'Desconectar' }).click();
  await expect(settings.getByText('Sin backend: la app usa sus datos de demo.')).toBeVisible();
});
