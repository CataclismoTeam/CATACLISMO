// Guardián del repositorio: falla (exit 1) si se versiona algo que no debe o si se
// debilitan las protecciones del repo. Se ejecuta en el CI y en local con `pnpm check:guard`.
// Sin dependencias: solo Node y git.
//
// Con --staged (hook pre-commit) las reglas por fichero (1, 2, 5 y 6) solo miran lo que va en el
// commit, para que nadie quede bloqueado por ficheros que no ha tocado; el CI revisa siempre todo.
import { execFileSync } from 'node:child_process';
import { readFileSync, statSync, existsSync } from 'node:fs';

const errors = [];
const fail = (msg) => errors.push(msg);

const git = (...args) =>
  execFileSync('git', args, { encoding: 'utf8' }).split('\n').filter(Boolean);
// Versionados + nuevos sin ignorar (así también revisa lo que aún no se ha añadido)
const tracked = [
  ...new Set([...git('ls-files'), ...git('ls-files', '--others', '--exclude-standard')]),
];
const staged = process.argv.includes('--staged');
// Ficheros a los que se aplican las reglas por fichero
const scope = staged ? git('diff', '--cached', '--name-only', '--diff-filter=ACMR') : tracked;
const inScope = new Set(scope);

// ── 1. Nada versionado que .gitignore diga que se ignora ──────────────────────
for (const file of git('ls-files', '-ci', '--exclude-standard')) {
  if (!inScope.has(file)) continue;
  fail(`${file}: está versionado pero .gitignore lo ignora. Sácalo con "git rm --cached ${file}".`);
}

// ── 2. Lista negra fija (no depende de .gitignore: aunque alguien lo edite, salta) ──
const forbidden = [
  [/(^|\/)\.env(\.(?!example$)[^/]+)?$/, 'variables de entorno'],
  [/\.(pem|key|crt|cer|p12|pfx|jks|keystore|gpg|asc|ppk)$/i, 'clave o certificado'],
  [/(^|\/)id_(rsa|ed25519|ecdsa|dsa)(\.pub)?$/, 'clave SSH'],
  [/(^|\/)(\.npmrc|\.netrc|\.htpasswd|\.pypirc)$/, 'fichero con credenciales'],
  [/(^|\/)(credentials|secrets?|service-account)[^/]*\.json$/i, 'credenciales en JSON'],
  // Los .sql solo se permiten en backend/sql/ (scripts de esquema, nunca volcados)
  [/^(?!backend\/sql\/).*\.sql$/i, 'volcado SQL fuera de backend/sql/'],
  [/\.(sqlite3?|db|dump|bak|backup)$/i, 'base de datos o copia de seguridad'],
  [
    /(^|\/)(node_modules|dist|\.vite|\.lighthouseci|coverage|playwright-report|test-results)\//,
    'dependencias o artefactos de build',
  ],
  [/(^|\/)(\.venv|venv|__pycache__|\.pytest_cache|\.ruff_cache)\//, 'entorno o caché de Python'],
  [/(^|\/)(package-lock\.json|yarn\.lock|bun\.lockb?)$/, 'lockfile de otro gestor (usamos pnpm)'],
  [/(^|\/)(\.claude|\.codex|\.cursor|\.idea)\//, 'configuración local de agentes o editores'],
  [/\.log$/i, 'log'],
];
for (const file of scope) {
  for (const [pattern, what] of forbidden) {
    if (pattern.test(file)) fail(`${file}: ${what}; no debe estar en el repositorio.`);
  }
}

// ── 3. Estructura: en la raíz solo lo previsto ────────────────────────────────
const allowedRoot = new Set([
  '.github',
  'backend',
  'config',
  'data',
  'docs',
  'frontend',
  'ops',
  'packages',
  'scripts',
  'tests',
  'tools',
  '.dockerignore',
  '.env.example',
  '.gitignore',
  'CHANGELOG.md',
  'README.md',
  'docker-compose.yml',
  'lefthook.yml',
  'package.json',
  'pnpm-lock.yaml',
  'pnpm-workspace.yaml',
]);
for (const root of new Set(tracked.map((f) => f.split('/')[0]))) {
  if (!allowedRoot.has(root)) {
    fail(
      `${root}: no está previsto en la raíz. Muévelo a su carpeta o añádelo a allowedRoot en tools/dev-utils/guard.mjs si es intencionado.`,
    );
  }
}

// ── 4. Ficheros críticos que no pueden desaparecer ────────────────────────────
const required = [
  '.gitignore',
  '.dockerignore',
  'package.json',
  'pnpm-lock.yaml',
  'pnpm-workspace.yaml',
  'lefthook.yml',
  'frontend/package.json',
  'frontend/vite.config.ts',
  'frontend/public/404.html',
  'backend/pyproject.toml',
  'backend/uv.lock',
  '.github/workflows/deploy.yml',
  '.github/workflows/release.yml',
  '.github/workflows/scorecard.yml',
  '.github/workflows/links.yml',
  '.github/workflows/monitor.yml',
  '.github/PULL_REQUEST_TEMPLATE/pull_request_template.md',
  '.github/dependabot.yml',
  '.github/SECURITY.md',
  'ops/deployment/maintenance.html',
  'tools/dev-utils/guard.mjs',
  'tools/dev-utils/commit-msg.mjs',
  'tools/dev-utils/check-links.mjs',
  'tools/dev-utils/check-size.mjs',
  'tools/dev-utils/serve.mjs',
  'tests/e2e/portada.spec.ts',
  'tests/visual/portada.spec.ts',
];
for (const file of required) {
  if (!tracked.includes(file)) fail(`${file}: fichero crítico ausente.`);
}

// ── 5. Tamaño máximo (evita binarios enormes o volcados por error) ────────────
const MAX_KB = 1024;
// Modelos entrenados y sus salidas: límite propio, más alto, solo en sus carpetas del backend
const MODEL_KB = 5120;
const modelArtifact = /^backend\/(checkpoints\/|app\/[^/]+\/artifacts\/)/;
for (const file of scope) {
  if (!existsSync(file)) continue; // borrado en el árbol de trabajo
  const kb = statSync(file).size / 1024;
  const max = modelArtifact.test(file) ? MODEL_KB : MAX_KB;
  if (kb > max) fail(`${file}: ocupa ${Math.round(kb)} KB (máximo ${max} KB).`);
}

// ── 6. Contenido: claves privadas y tokens con formato conocido ───────────────
const secretPatterns = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----/, 'clave privada'],
  [/\bgh[pousr]_[A-Za-z0-9]{36,}\b/, 'token de GitHub'],
  [/\bgithub_pat_[A-Za-z0-9_]{60,}\b/, 'token de GitHub'],
  [/\bAKIA[0-9A-Z]{16}\b/, 'clave de AWS'],
  [/\bsk-(ant-|proj-)?[A-Za-z0-9_-]{32,}\b/, 'clave de API (OpenAI/Anthropic)'],
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}\b/, 'token de Slack'],
  [/\bAIza[0-9A-Za-z_-]{35}\b/, 'clave de Google API'],
];
const textExt =
  /\.(tsx?|mjs|js|py|json|toml|ya?ml|md|html|css|txt|svg|cfg|ini)$|(^|\/)(\.gitignore|\.env\.example|Dockerfile)$/;
const lockfiles = new Set(['pnpm-lock.yaml', 'backend/uv.lock']);
for (const file of scope) {
  if (!textExt.test(file) || !existsSync(file) || lockfiles.has(file)) continue;
  const text = readFileSync(file, 'utf8');
  for (const [pattern, what] of secretPatterns) {
    if (pattern.test(text)) fail(`${file}: parece contener: ${what}.`);
  }
}

// ── 7. .gitignore conserva las entradas de seguridad mínimas ──────────────────
const ignore = readFileSync('.gitignore', 'utf8')
  .split('\n')
  .map((l) => l.trim());
for (const entry of [
  'node_modules/',
  'dist/',
  '.env',
  '.env.*',
  '!.env.example',
  '*.pem',
  '*.key',
  '.claude/',
  '.npmrc',
  '.venv/',
  '__pycache__/',
]) {
  if (!ignore.includes(entry)) fail(`.gitignore: falta la entrada de seguridad "${entry}".`);
}

// ── 8. Endurecimiento de los workflows ────────────────────────────────────────
for (const wf of tracked.filter((f) => /^\.github\/workflows\/.+\.ya?ml$/.test(f))) {
  const yml = readFileSync(wf, 'utf8');
  if (!/^permissions:\s*\{\}\s*$/m.test(yml)) {
    fail(`${wf}: debe declarar "permissions: {}" a nivel global (permisos mínimos).`);
  }
  if (/pull_request_target/.test(yml)) {
    fail(`${wf}: usa pull_request_target, que ejecuta código de forks con permisos de escritura.`);
  }
  for (const [, ref] of yml.matchAll(/^\s*-?\s*uses:\s*([^\s#]+)/gm)) {
    if (ref.startsWith('./') || ref.startsWith('docker://')) continue;
    if (!/@[0-9a-f]{40}$/.test(ref))
      fail(`${wf}: "${ref}" no está fijada a un SHA de 40 caracteres.`);
  }
  const checkouts = (yml.match(/uses:\s*actions\/checkout@/g) ?? []).length;
  const noCreds = (yml.match(/persist-credentials:\s*false/g) ?? []).length;
  if (checkouts !== noCreds) {
    fail(
      `${wf}: cada actions/checkout debe llevar "persist-credentials: false" (${noCreds}/${checkouts}).`,
    );
  }
}

// ── 9. Gestor de paquetes ─────────────────────────────────────────────────────
const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
if (!String(pkg.packageManager ?? '').startsWith('pnpm@')) {
  fail('package.json: "packageManager" debe ser pnpm.');
}

// ── Resultado ─────────────────────────────────────────────────────────────────
if (errors.length) {
  console.error(`✗ Guardián: ${errors.length} problema(s)\n  - ${errors.join('\n  - ')}`);
  process.exit(1);
}
console.log(
  `✓ Guardián: ${scope.length} ficheros revisados${staged ? ' (en stage)' : ''}, todo en orden`,
);
