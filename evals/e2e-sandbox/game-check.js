const fs = require("fs");
const f = "game.html";
if (!fs.existsSync(f)) { console.error("FAIL: game.html missing"); process.exit(1); }
const html = fs.readFileSync(f, "utf8");
const reqs = [
  ["canvas element", /<canvas/i],
  ["2d context", /getContext\(['"]2d['"]\)/],
  ["animation loop", /requestAnimationFrame/],
  ["player object", /player/i],
  ["enemies/invaders array", /(invaders|enemies|aliens)/i],
  ["bullets/projectiles", /(bullet|projectile|laser|shot)/i],
  ["keyboard input", /(keydown|keyup|addEventListener\(['"]key)/i],
  ["collision detection", /(collision|collide|intersect|hit)/i],
  ["score", /score/i],
];
const fails = reqs.filter(([n,re]) => !re.test(html)).map(([n]) => n);
if (fails.length) { console.error("FAIL missing: " + fails.join(", ")); process.exit(1); }
// also: must be non-trivial size (a real game, not a stub)
if (html.length < 2000) { console.error("FAIL: game.html too small (" + html.length + " bytes) — likely a stub"); process.exit(1); }
console.log("OK: all " + reqs.length + " mechanics present, " + html.length + " bytes");
process.exit(0);
