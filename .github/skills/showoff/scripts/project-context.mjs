/**
 * project-context.mjs
 *
 * Emits compact JSON describing the current working directory for use as
 * dynamic context in the /showoff skill. Deterministic, dependency-free Node ESM.
 *
 * Output schema:
 *   cwd              string   - absolute path of process.cwd()
 *   platform         string   - process.platform ("win32", "darwin", "linux", ...)
 *   pathSep          string   - platform path separator
 *   git.available    boolean  - whether git is on PATH
 *   git.status       string|null - "clean", "dirty", or null if unavailable
 *   git.recentCommits string[] - last 5 commit messages (empty if unavailable)
 *   manifests        string[] - candidate project manifest filenames found in cwd
 *   assetDirs        string[] - asset/media subdirectories found in cwd
 *   existingOutputs  object   - info about prior showoff-output runs
 */

import { spawnSync } from 'child_process';
import { existsSync, readdirSync, statSync } from 'fs';
import { join } from 'path';

const cwd = process.cwd();
const platform = process.platform;
const pathSep = platform === 'win32' ? '\\' : '/';

// ---------------------------------------------------------------------------
// Git availability and status
// ---------------------------------------------------------------------------

const GIT_TIMEOUT_MS = 4000;

function runGit(args) {
  const result = spawnSync('git', args, {
    cwd,
    encoding: 'utf8',
    timeout: GIT_TIMEOUT_MS,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) return null;
  return (result.stdout || '').trim();
}

const statusRaw = runGit(['status', '--porcelain']);
const gitAvailable = statusRaw !== null;
const gitStatus = !gitAvailable
  ? null
  : statusRaw.length === 0
    ? 'clean'
    : 'dirty';

let recentCommits = [];
if (gitAvailable) {
  const logRaw = runGit(['log', '--oneline', '-5']);
  if (logRaw) {
    recentCommits = logRaw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
  }
}

// ---------------------------------------------------------------------------
// Candidate project manifests in cwd
// ---------------------------------------------------------------------------

const MANIFEST_NAMES = [
  'package.json',
  'pyproject.toml',
  'setup.py',
  'setup.cfg',
  'Cargo.toml',
  'go.mod',
  'requirements.txt',
  'composer.json',
  'pom.xml',
  'build.gradle',
  'build.gradle.kts',
  'README.md',
  'readme.md',
  'README.rst',
  'CHANGELOG.md',
  'CHANGELOG',
];

const manifests = MANIFEST_NAMES.filter((name) => existsSync(join(cwd, name)));

// ---------------------------------------------------------------------------
// Asset / media subdirectories in cwd
// ---------------------------------------------------------------------------

const ASSET_DIR_NAMES = [
  'assets',
  'public',
  'images',
  'screenshots',
  'docs',
  'media',
  'static',
  'resources',
];

const assetDirs = ASSET_DIR_NAMES.filter((name) => {
  const p = join(cwd, name);
  if (!existsSync(p)) return false;
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
});

// ---------------------------------------------------------------------------
// Existing showoff-output runs
// ---------------------------------------------------------------------------

const outputsRoot = join(cwd, 'showoff-output');
let existingRuns = [];
let mostRecentRun = null;

if (existsSync(outputsRoot)) {
  try {
    existingRuns = readdirSync(outputsRoot)
      .filter((entry) => /^\d{8}-\d{6}$/.test(entry))
      .sort()
      .reverse();

    if (existingRuns.length > 0) {
      mostRecentRun = join(outputsRoot, existingRuns[0]);
    }
  } catch {
    // Non-fatal: leave existingRuns empty
  }
}

// ---------------------------------------------------------------------------
// Emit
// ---------------------------------------------------------------------------

const output = {
  cwd,
  platform,
  pathSep,
  git: {
    available: gitAvailable,
    status: gitStatus,
    recentCommits,
  },
  manifests,
  assetDirs,
  existingOutputs: {
    root: existsSync(outputsRoot) ? outputsRoot : null,
    runCount: existingRuns.length,
    runs: existingRuns.slice(0, 5),
    mostRecentRun,
  },
};

process.stdout.write(JSON.stringify(output, null, 2) + '\n');
