// surface-scan-template.mjs -- Phoenix Ralph negative/absence assertion template (issue #13 rec-1)
// PURPOSE: Walk dirs for forbidden legacy signatures; exit 1 while any remain (file:line listed),
// exit 0 when surface is clean. Copy + edit CONFIG, then use as a done-check node script.
// DONE-CHECK: { kind: command_exit, target: [node, verify-surface-clean.mjs], expect: 0 }
// Start RED (offenders present before migration) -> GREEN (all removed) = failure-first proof.

import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = fileURLToPath(new URL(".", import.meta.url));

// -- CONFIG (customise per project) ------------------------------------------
const CONFIG = {
  // Directories to scan relative to this file (or absolute paths).
  scanDirs: ['app', 'components'],
  extensions: ['.tsx', '.jsx', '.ts', '.js', '.css', '.scss'],
  // Path substrings to skip (vendor/generated trees).
  excludeFragments: ['node_modules', '.next', 'dist', '/ui/'],
  // Forbidden legacy signatures (regex strings). Each match => offender at file:line.
  // Examples below are the canonical set from issue #13 (glassmorphism -> warm-editorial).
  forbiddenPatterns: [
    'text-gradient',
    'glow-[a-z]',
    'ambient(?:-[a-z])?',
    'glass(?:-[a-z])?',
    "bg-white\\/\\d+",
    // add your project-specific legacy colour/class patterns here
  ],
};
// ----------------------------------------------------------------------------

const compiled = CONFIG.forbiddenPatterns.map((p) => new RegExp(p));

function collectFiles(dir) {
  const results = [];
  let entries;
  try { entries = readdirSync(dir, { withFileTypes: true }); }
  catch { return results; }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    const rel  = relative(process.cwd(), full).replace(/\\/g, "/");
    if (CONFIG.excludeFragments.some((frag) => rel.includes(frag))) continue;
    if (entry.isDirectory()) { results.push(...collectFiles(full)); }
    else if (entry.isFile() && CONFIG.extensions.some((ext) => entry.name.endsWith(ext)))
      results.push(full);
  }
  return results;
}

/** Scan one file; return offender objects with file:lineNum:lineText:pattern. */
function scanFile(filePath) {
  let src;
  try { src = readFileSync(filePath, "utf-8"); } catch { return []; }
  const offenders = [];
  const srcLines = src.split("\n");
  for (let lineNum = 0; lineNum < srcLines.length; lineNum++) {
    const lineText = srcLines[lineNum];
    for (const re of compiled) {
      if (re.test(lineText)) {
        offenders.push({
          file: relative(process.cwd(), filePath).replace(/\\/g, "/"),
          lineNum: lineNum + 1,
          lineText: lineText.trim().slice(0, 120),
          pattern: re.source,
        });
        break;
      }
    }
  }
  return offenders;
}

// -- MAIN --------------------------------------------------------------------
let allFiles = [];
for (const scanDir of CONFIG.scanDirs) {
  const absDir = (scanDir.startsWith("/") || /^[A-Za-z]:/.test(scanDir))
    ? scanDir : join(__dirname, scanDir);
  allFiles.push(...collectFiles(absDir));
}
const allOffenders = allFiles.flatMap(scanFile);

if (allOffenders.length === 0) {
  console.log("[surface-scan] PASS: no forbidden legacy signatures found.");
  process.exit(0);
} else {
  console.log(`[surface-scan] FAIL: ${allOffenders.length} offender(s) found -- legacy signatures must be removed.`);
  for (const o of allOffenders) {
    console.log(`  ${o.file}:${o.lineNum}  [pattern: ${o.pattern}]`);
    console.log(`    ${o.lineText}`);
  }
  console.log("Tip: add negative/absence assertions (legacy thing gone) alongside positive ones (new thing present).");
  process.exit(1);
}
