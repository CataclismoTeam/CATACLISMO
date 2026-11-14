## Qué cambia

<!-- Resumen en 1-3 frases. El título del PR sigue Conventional Commits (feat:, fix:, ci:…). -->

## Comprobaciones

- [ ] `pnpm format:check`, `pnpm check` y `pnpm lint` pasan
- [ ] `pnpm build`, `pnpm check:links`, `pnpm check:html` y `pnpm check:size` pasan
- [ ] Tests e2e: `pnpm test:e2e` (o `CHROME_PATH=/usr/bin/chromium pnpm test:e2e`)
- [ ] Backend (si cambia): `uv run ruff check .`, `uv run ruff format --check .` y `uv run pytest` en `backend/`
- [ ] Si cambia el aspecto a propósito: referencias visuales actualizadas (ver `tests/visual/README.md`)
- [ ] Sin secretos ni datos personales nuevos (el guardián lo vigila, pero revísalo)
