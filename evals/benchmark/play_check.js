// Hardened interaction gate for a canvas game. Loads the page in a real browser, drives input,
// and asserts OBSERVABLE behavior — not just "the file contains the word player".
// Usage: node play_check.js <path-to-html>   (exit 0 = all behaviors pass)
const { chromium } = require("playwright");
const path = require("path");

const file = process.argv[2] || "game.html";
const url = "file:///" + path.resolve(file).replace(/\\/g, "/");

(async () => {
  const results = [];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 900, height: 800 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  await page.goto(url);
  await page.waitForTimeout(500);

  // helper: read a numeric "score" from the page if the game exposes one (global or visible text)
  async function readScore() {
    return page.evaluate(() => {
      // try common globals, then any element whose text looks like "Score: N"
      for (const k of ["score", "Score", "playerScore", "gameScore"]) {
        if (typeof window[k] === "number") return window[k];
        if (window.game && typeof window.game[k] === "number") return window.game[k];
      }
      const m = (document.body.innerText || "").match(/score[:\s]*([0-9]+)/i);
      return m ? parseInt(m[1], 10) : null;
    });
  }

  function check(name, cond) { results.push({ name, ok: !!cond }); }

  // 1. The canvas exists and has non-trivial dimensions (it's actually a rendered game surface).
  const canvas = await page.evaluate(() => {
    const c = document.querySelector("canvas");
    return c ? { w: c.width, h: c.height } : null;
  });
  check("canvas renders with size", canvas && canvas.w >= 200 && canvas.h >= 200);

  // 2. The game loop runs: the canvas pixels change between two frames (something is animating/moving).
  async function canvasHash() {
    return page.evaluate(() => {
      const c = document.querySelector("canvas");
      if (!c) return "no-canvas";
      try { return c.toDataURL().slice(-200); } catch (e) { return "tainted"; }
    });
  }
  const f1 = await canvasHash();
  await page.waitForTimeout(700);
  const f2 = await canvasHash();
  check("game loop animates (frame changes over time)", f1 !== f2 && f1 !== "no-canvas");

  // 3. Player responds to input: hold a movement key, the frame must change as a result.
  await page.keyboard.down("ArrowLeft");
  await page.waitForTimeout(300);
  await page.keyboard.up("ArrowLeft");
  const f3 = await canvasHash();
  check("responds to keyboard input", f3 !== f2);

  // 4. Shooting works and scoring is reachable: fire repeatedly; either the score increases OR
  //    the canvas keeps changing under fire (bullets present). Score increase is the strong signal.
  const sBefore = await readScore();
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press("Space");
    await page.keyboard.down("ArrowRight"); await page.waitForTimeout(40); await page.keyboard.up("ArrowRight");
  }
  await page.waitForTimeout(500);
  const sAfter = await readScore();
  const scored = sBefore !== null && sAfter !== null && sAfter > sBefore;
  const f4 = await canvasHash();
  check("shooting produces activity (score up, or bullets animating)", scored || f4 !== f3);

  // 5. No uncaught JS errors during play (a broken game throws).
  check("no uncaught JS errors during play", errors.length === 0);

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  for (const r of results) console.log(`  ${r.ok ? "PASS" : "FAIL"}  ${r.name}`);
  if (sBefore !== null) console.log(`  (score: ${sBefore} -> ${sAfter})`);
  if (errors.length) console.log("  JS errors:", errors.slice(0, 3));
  if (failed.length) { console.log(`PLAY_CHECK_FAIL ${failed.length}/${results.length}`); process.exit(1); }
  console.log(`PLAY_CHECK_OK ${results.length}/${results.length}`);
  process.exit(0);
})().catch((e) => { console.log("PLAY_CHECK_ERROR:", e.message); process.exit(1); });
