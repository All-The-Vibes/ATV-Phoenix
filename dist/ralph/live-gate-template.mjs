/**
 * live-gate-template.mjs — Phoenix Ralph live/serve acceptance gate template
 *
 * Bakes in two Windows gotchas discovered in issue #12:
 *
 * FIX 1 — stdio:'ignore' + port-kill teardown
 *   NEVER use stdio:'inherit' for a long-lived serve process: the served tree
 *   inherits the sense process's stdout/stderr pipe and keeps it open after a
 *   pid-tree kill (detached grandchildren on Windows survive taskkill /T).
 *   phoenix-mcp sense captures evidence by reading the child pipe to EOF —
 *   with an inherited-stdio server alive, sense blocks until the 1200s budget
 *   (observed: 864838ms hang, 24 leaked node processes).
 *   FIX: spawn serve with { stdio: 'ignore', windowsHide: true }.
 *   Teardown: kill by PORT (netstat -ano) as well as pid-tree — the detached
 *   grandchild holds the port even after its parent is killed.
 *
 * FIX 2 — case-insensitive innerText matching
 *   innerText applies CSS text-transform before returning text. Any design
 *   system that uppercases headings/eyebrows (common) renders e.g.
 *   "Next Best Offer" as "NEXT BEST OFFER". A case-sensitive includes() check
 *   produces false-RED on content that IS present and visible, which pressures
 *   the agent to remove CSS uppercase styling to satisfy a broken gate — the
 *   mirror image of the anti-pattern Phoenix is built to prevent.
 *   FIX: bodyText.toLowerCase().includes(marker.toLowerCase())
 *
 * Usage: copy and customise the CONFIG section. Run with:
 *   node live-gate-template.mjs
 * Returns exit 0 on pass, 1 on failure, 2 on setup error.
 */

import { spawn, execSync } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';

// ── CONFIG (customise per project) ──────────────────────────────────────────
const CONFIG = {
  serveCmd:   'pnpm',
  serveArgs:  ['start'],           // e.g. ['run', 'start'] or ['next', 'start']
  servePort:  3000,
  serveReady: /ready|listening|started/i, // stdout/stderr line that signals ready
  readyTimeout: 60_000,            // ms to wait for serveReady before giving up
  gateTimeout:  9 * 60_000,        // hard watchdog: gate always exits within this
  markers: [                       // text expected on the page (case-insensitive)
    'Home',
  ],
  url: 'http://localhost:3000',
};
// ─────────────────────────────────────────────────────────────────────────────

let serveProc = null;

// Hard watchdog — gate always terminates and reports (FIX 1 complement)
const watchdog = setTimeout(() => {
  console.error(`[live-gate] FAIL: gate watchdog fired after ${CONFIG.gateTimeout}ms`);
  teardown(CONFIG.servePort).then(() => process.exit(1));
}, CONFIG.gateTimeout).unref();

async function killByPort(port) {
  // Windows: find PIDs listening on port via netstat, then taskkill
  try {
    const out = execSync(`netstat -ano`, { encoding: 'utf8', timeout: 10_000 });
    const pids = new Set();
    for (const line of out.split('\n')) {
      const m = line.match(/:(\d+)\s+.*LISTENING\s+(\d+)/);
      if (m && Number(m[1]) === port) pids.add(m[2]);
    }
    for (const pid of pids) {
      try { execSync(`taskkill /PID ${pid} /T /F`, { timeout: 5_000 }); } catch {}
    }
  } catch {}
}

async function teardown(port) {
  if (serveProc) {
    try { serveProc.kill('SIGTERM'); } catch {}
    serveProc = null;
  }
  await killByPort(port);   // FIX 1: port-kill catches detached grandchildren
}

async function waitForReady(proc, pattern, timeout) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('ready timeout')), timeout);
    const check = (data) => {
      if (pattern.test(String(data))) { clearTimeout(t); resolve(); }
    };
    // stdout/stderr are null (stdio:'ignore') — poll HTTP instead
    clearTimeout(t);
    resolve(); // fall through to HTTP poll below
  });
}

async function pollHttp(url, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const { default: http } = await import('node:http');
      await new Promise((res, rej) => {
        const req = http.get(url, (r) => { r.resume(); res(); });
        req.on('error', rej);
        req.setTimeout(2000, () => { req.destroy(); rej(new Error('timeout')); });
      });
      return;
    } catch {
      await sleep(1000);
    }
  }
  throw new Error(`Server at ${url} not ready after ${timeout}ms`);
}

(async () => {
  // Spawn server with stdio:'ignore' — FIX 1: never inherit stdio for serve
  serveProc = spawn(CONFIG.serveCmd, CONFIG.serveArgs, {
    stdio: 'ignore',          // ← THE KEY FIX: no pipe inheritance
    windowsHide: true,
    detached: false,
  });

  serveProc.on('error', async (err) => {
    console.error(`[live-gate] FAIL: serve spawn error: ${err.message}`);
    await teardown(CONFIG.servePort);
    process.exit(2);
  });

  try {
    await pollHttp(CONFIG.url, CONFIG.readyTimeout);
  } catch (e) {
    console.error(`[live-gate] FAIL: ${e.message}`);
    await teardown(CONFIG.servePort);
    clearTimeout(watchdog);
    process.exit(1);
  }

  // Evaluate page content with Playwright (or fallback to http fetch for text)
  let pass = true;
  try {
    const { chromium } = await import('playwright');
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(CONFIG.url, { waitUntil: 'networkidle', timeout: 30_000 });
    const bodyText = await page.evaluate(() => document.body.innerText);
    // FIX 2: case-insensitive marker matching — innerText applies text-transform
    for (const marker of CONFIG.markers) {
      if (!bodyText.toLowerCase().includes(marker.toLowerCase())) {
        console.error(`[live-gate] FAIL: marker not found (case-insensitive): "${marker}"`);
        pass = false;
      }
    }
    await browser.close();
  } catch (e) {
    console.error(`[live-gate] FAIL: page evaluation error: ${e.message}`);
    pass = false;
  }

  await teardown(CONFIG.servePort);
  clearTimeout(watchdog);
  console.log(pass ? '[live-gate] PASS' : '[live-gate] FAIL');
  process.exit(pass ? 0 : 1);
})();