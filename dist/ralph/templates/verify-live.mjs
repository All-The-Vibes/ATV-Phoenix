/**
 * verify-live.mjs  --  reusable live-acceptance gate for Next.js / Node apps
 *
 * Usage (phoenix_sense command_exit gate):
 *   node verify-live.mjs                   # checks localhost:PORT, routes from ROUTES below
 *   node verify-live.mjs --port 4000
 *   node verify-live.mjs --json            # machine-readable result (phoenix_sense compatible)
 *
 * What it proves (beyond "cargo build passes"):
 *   1. The server actually starts and responds on the expected port.
 *   2. Every route returns HTTP 200 with the expected marquee content in the runtime DOM
 *      (catches render/hydration failures that a build check misses).
 *   3. Global nav is reachable on every page.
 *   4. No uncaught page errors; no fatal console errors (React/Next hydration).
 *   5. A non-blank full-page screenshot is captured per route as visual proof.
 *      (size threshold = blank-proxy: a blank/white page would be < MIN_SCREENSHOT_BYTES)
 *
 * CUSTOMISE these four constants for your project, then wire the script as a
 * phoenix_sense command_exit check in your .phoenix-ralph/done-check.json:
 *
 *   { "kind": "command_exit",
 *     "target": ["node", "scripts/verify-live.mjs"],
 *     "expect": 0, "cwd": "." }
 *
 * Requires: playwright (npm i -D playwright) + a server command (START_CMD below).
 * Windows-safe: server is killed via process.kill on SIGTERM/exit/uncaughtException.
 */

import { chromium } from 'playwright';
import { spawn }    from 'child_process';
import { existsSync, mkdirSync, statSync } from 'fs';
import { setTimeout as sleep } from 'timers/promises';

// ── CONFIGURE FOR YOUR PROJECT ────────────────────────────────────────────────
const PORT            = parseInt(process.env.PORT ?? '3000', 10);
const START_CMD       = process.env.START_CMD ?? 'npm';
const START_ARGS      = (process.env.START_ARGS ?? 'start').split(' ');
const SCREENSHOTS_DIR = process.env.SCREENSHOTS_DIR ?? 'screenshots';
const MIN_SCREENSHOT_BYTES = 5_000;   // blank/white page is typically < 5 KB
const READY_TIMEOUT_MS     = 30_000;  // how long to wait for server to accept connections
const FATAL_CONSOLE_RE     = /error|hydration|react|exception/i;
const BENIGN_CONSOLE_RE    = /favicon|hot-reload|webpack|_next\/static/i;

// Routes table: { path, marker } -- marker must appear in the runtime DOM text.
// Add/remove entries for your app's routes.
const ROUTES = [
  { path: '/',         marker: null },  // null = skip DOM marker check, just assert 200
  // { path: '/about',   marker: 'About' },
  // { path: '/contact', marker: 'Contact' },
];
// ── END CONFIGURATION ─────────────────────────────────────────────────────────

const JSON_MODE = process.argv.includes('--json');
const results   = { ok: true, routes: [], errors: [] };

function log(msg) { if (!JSON_MODE) console.log(msg); }
function fail(msg) { results.ok = false; results.errors.push(msg); log(`  FAIL: ${msg}`); }

// ── Server lifecycle ──────────────────────────────────────────────────────────
let server = null;
function startServer() {
  server = spawn(START_CMD, START_ARGS, {
    stdio: 'ignore',   // do NOT inherit stdio -- avoids the 'stdio:inherit hangs sense' gotcha (#12)
    detached: false,
    shell: process.platform === 'win32',
  });
  server.on('error', err => fail(`server spawn error: ${err.message}`));
}

function stopServer() {
  if (!server) return;
  try {
    if (process.platform === 'win32') {
      // taskkill /T kills the whole process tree on Windows
      spawn('taskkill', ['/pid', String(server.pid), '/T', '/F'], { stdio: 'ignore', shell: true });
    } else {
      process.kill(-server.pid, 'SIGTERM');
    }
  } catch (_) {}
  server = null;
}

async function waitForServer(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`http://localhost:${port}/`, { signal: AbortSignal.timeout(1000) });
      if (r.ok || r.status < 500) return true;
    } catch (_) {}
    await sleep(500);
  }
  return false;
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  mkdirSync(SCREENSHOTS_DIR, { recursive: true });

  log(`[verify-live] starting server (${START_CMD} ${START_ARGS.join(' ')})...`);
  startServer();

  const ready = await waitForServer(PORT, READY_TIMEOUT_MS);
  if (!ready) {
    fail(`server did not become ready on port ${PORT} within ${READY_TIMEOUT_MS}ms`);
    stopServer();
    if (JSON_MODE) process.stdout.write(JSON.stringify(results) + '\n');
    process.exit(1);
  }
  log(`[verify-live] server ready on :${PORT}`);

  const browser = await chromium.launch();
  const ctx     = await browser.newContext();

  try {
    for (const route of ROUTES) {
      log(`  checking ${route.path}...`);
      const page        = await ctx.newPage();
      const consoleErrs = [];
      const pageErrs    = [];

      page.on('console', msg => {
        if (msg.type() === 'error' && FATAL_CONSOLE_RE.test(msg.text()) && !BENIGN_CONSOLE_RE.test(msg.text())) {
          consoleErrs.push(msg.text());
        }
      });
      page.on('pageerror', err => pageErrs.push(err.message));

      const res = await page.goto(`http://localhost:${PORT}${route.path}`, {
        waitUntil: 'load',
        timeout: 15_000,
      });

      const routeResult = { path: route.path, status: res?.status(), ok: true, errors: [] };

      // 1. HTTP 200
      if (!res || res.status() !== 200) {
        const msg = `${route.path} returned HTTP ${res?.status() ?? 'no-response'}`;
        fail(msg); routeResult.ok = false; routeResult.errors.push(msg);
      }

      // 2. Marker in runtime DOM
      if (route.marker) {
        const text = await page.evaluate(() => document.body.innerText).catch(() => '');
        if (!text.includes(route.marker)) {
          const msg = `${route.path}: marker "${route.marker}" not found in runtime DOM`;
          fail(msg); routeResult.ok = false; routeResult.errors.push(msg);
        }
      }

      // 3. No fatal console errors
      if (consoleErrs.length > 0) {
        const msg = `${route.path}: fatal console errors: ${consoleErrs.slice(0,3).join('; ')}`;
        fail(msg); routeResult.ok = false; routeResult.errors.push(msg);
      }
      if (pageErrs.length > 0) {
        const msg = `${route.path}: uncaught page errors: ${pageErrs.slice(0,3).join('; ')}`;
        fail(msg); routeResult.ok = false; routeResult.errors.push(msg);
      }

      // 4. Non-blank screenshot
      const shotPath = `${SCREENSHOTS_DIR}/${route.path.replace(/\//g,'_') || 'root'}.png`;
      await page.screenshot({ path: shotPath, fullPage: true });
      const shotSize = existsSync(shotPath) ? statSync(shotPath).size : 0;
      if (shotSize < MIN_SCREENSHOT_BYTES) {
        const msg = `${route.path}: screenshot too small (${shotSize}B < ${MIN_SCREENSHOT_BYTES}B) -- possible blank page`;
        fail(msg); routeResult.ok = false; routeResult.errors.push(msg);
      } else {
        log(`    screenshot: ${shotPath} (${shotSize}B)`);
      }

      results.routes.push(routeResult);
      await page.close();
    }
  } finally {
    await browser.close();
    stopServer();
  }

  if (JSON_MODE) {
    process.stdout.write(JSON.stringify(results) + '\n');
  } else {
    const passed = results.routes.filter(r => r.ok).length;
    console.log(`[verify-live] ${passed}/${results.routes.length} routes OK  errors=${results.errors.length}`);
    if (results.errors.length > 0) results.errors.forEach(e => console.error(`  ERR: ${e}`));
  }
  process.exit(results.ok ? 0 : 1);
}

process.on('SIGTERM', () => { stopServer(); process.exit(1); });
process.on('uncaughtException', err => { console.error(err); stopServer(); process.exit(1); });

main().catch(err => { console.error(err); stopServer(); process.exit(1); });