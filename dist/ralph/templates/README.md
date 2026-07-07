# dist/ralph/templates/

Reusable gate templates for phoenix-ralph lights-out runs.

## verify-live.mjs

A live-acceptance gate for Next.js and Node.js web apps. Proves the app not only
builds but also runs, serves all routes HTTP 200, renders expected DOM content,
captures non-blank screenshots, and produces no fatal console errors.

### Usage

Copy into scripts/, edit the four constants at the top, install Playwright
(npm i -D playwright), then use as a phoenix_sense command_exit gate:

  { "kind": "command_exit", "target": ["node", "scripts/verify-live.mjs"], "expect": 0, "cwd": "." }

Run directly: node scripts/verify-live.mjs [--port N] [--json]

### What it checks

1. Server starts and accepts connections within READY_TIMEOUT_MS
2. Every route in ROUTES returns HTTP 200
3. Each route marker appears in the runtime DOM (catches hydration failures)
4. No uncaught page errors; no fatal console errors (error|hydration|react|exception)
5. Non-blank full-page screenshot captured per route (blank < MIN_SCREENSHOT_BYTES)

Windows-safe: uses taskkill /T /F for process tree teardown; stdio always ignored
(avoids the stdio:inherit hang documented in phoenix issue #12).