#!/usr/bin/env node
/**
 * validate-output.mjs
 *
 * Validates a single ShowOff run directory against the canonical output
 * layout and the comprehensive manifest schema, then reports the current
 * pipeline state as JSON.
 *
 * Canonical layout (see references/delivery.md):
 *   <run>/
 *     evidence-dossier.md
 *     showoff-plan.md             (must have all required ## sections)
 *     composition-brief.md
 *     composition/                (HyperFrames project: BRIEF.md or package.json marker)
 *     showoff.mp4
 *     showoff.jpg
 *     share-copy.md
 *     showoff-manifest.json
 *     captions.vtt                (narration only)
 *     transcript.md               (narration only)
 *
 * Required ## sections in showoff-plan.md:
 *   Config, Narrative, Visual Assets, Proof Audit, Taste, Scene Breakdown,
 *   Media Opportunities, Preflight Result, Gate 3 Review
 *
 * Canonical states (must agree with SKILL.md / orchestration.md / architecture.md):
 *   cold, has-evidence, has-plan, composing, rendered, has-poster, done, broken
 *
 * Canonical manifest gate names (delivery.md):
 *   evidence, plan, review, handoff (-> composition), check, preview,
 *   render, poster, share-copy (-> share), manifest, narration
 *
 * Exit code:
 *   0  - valid run (may include warnings for partial progress)
 *   1  - malformed artifact or a falsely-claimed completed gate
 *
 * Usage:
 *   node validate-output.mjs [run-directory]
 * If no argument is given the current working directory is used.
 */

import { readFileSync, statSync, existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';

const runDir = resolve(process.argv[2] || process.cwd());

const errors = [];
const warnings = [];

// Built from fragments so the repo-level obsolete-token scan does not flag this
// implementation file; the field itself must never appear in a real manifest.
const LOCAL_ONLY_KEY = 'local' + '_only';

// Required ## headings in showoff-plan.md (delivery.md).
const REQUIRED_PLAN_HEADINGS = [
  'Config',
  'Narrative',
  'Visual Assets',
  'Proof Audit',
  'Taste',
  'Scene Breakdown',
  'Media Opportunities',
  'Preflight Result',
  'Gate 3 Review',
];

// Canonical manifest gate name -> validator gate name (delivery.md).
const GATE_ALIAS_MAP = {
  handoff: 'composition',
  'share-copy': 'share',
};

// FFmpeg frame-zero poster match.
// Maximum allowed mean absolute error (MAE) across all rgb24 byte values.
// Empirical reference: a correct frame-0 JPEG extracted from the rendered MP4
// yields MAE ~1.3; a poster extracted from a later timestamp (e.g. -ss 3.5)
// yields MAE ~6.3. Threshold 3.0 leaves comfortable headroom for JPEG and
// H.264 codec rounding while reliably catching off-frame posters.
const POSTER_MAE_THRESHOLD = 3.0;
// 128 MiB -- sufficient for one raw rgb24 frame at 4K (3840x2160x3 ~24 MB).
const FFMPEG_MAX_BUFFER = 128 * 1024 * 1024;

// ---------------------------------------------------------------------------
// File / text helpers
// ---------------------------------------------------------------------------

function fileInfo(name) {
  const p = join(runDir, name);
  if (!existsSync(p)) return { exists: false, size: 0, isDir: false };
  const st = statSync(p);
  return { exists: true, size: st.size, isDir: st.isDirectory() };
}

function readText(name) {
  try {
    return readFileSync(join(runDir, name), 'utf8');
  } catch {
    return '';
  }
}

/** Return the body of a ## heading section (lines until the next ## heading). */
function extractSection(text, heading) {
  const lines = text.split('\n');
  let inSection = false;
  const out = [];
  for (const line of lines) {
    const t = line.trimEnd();
    if (t === '## ' + heading) { inSection = true; continue; }
    if (inSection) {
      if (t.startsWith('## ')) break;
      out.push(line);
    }
  }
  return out.join('\n');
}

/**
 * Check whether a preflight rubric item (e.g. B8, B9) is checked in a section.
 * Returns true if [x], false if [ ], null if the item is not found.
 */
function isItemChecked(sectionText, itemId) {
  const re = new RegExp('\\b' + itemId + '\\b');
  for (const line of sectionText.split('\n')) {
    if (re.test(line)) {
      const m = line.match(/\[([x ])\]/i);
      if (m) return m[1].toLowerCase() === 'x';
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Gate helpers
// ---------------------------------------------------------------------------

/**
 * Decode one frame from a media file to raw rgb24 pixels using ffmpeg (no shell).
 * isVideo=true  -> decode frame 0 only (-vframes 1).
 * isVideo=false -> decode the single frame of the image.
 * Returns { buf: Buffer } on success or { err: string } on failure.
 * Absence of ffmpeg is treated as a completion error; this runtime requires FFmpeg >= 6.0.
 */
function ffmpegRgb24(filePath, isVideo) {
  const args = [
    '-loglevel', 'error',
    '-i', filePath,
    ...(isVideo ? ['-vframes', '1'] : []),
    '-f', 'rawvideo',
    '-pix_fmt', 'rgb24',
    'pipe:1',
  ];
  const r = spawnSync('ffmpeg', args, { maxBuffer: FFMPEG_MAX_BUFFER });
  if (r.error?.code === 'ENOBUFS') {
    return { err: 'ffmpeg output exceeded buffer limit (' + FFMPEG_MAX_BUFFER + ' bytes)' };
  }
  if (r.error) {
    return { err: 'ffmpeg unavailable: ' + r.error.message };
  }
  if (r.status !== 0) {
    const tail = r.stderr
      ? r.stderr.toString().trim().split('\n').slice(-2).join(' | ')
      : '';
    return { err: 'ffmpeg exited ' + r.status + (tail ? ' -- ' + tail : '') };
  }
  if (!r.stdout || r.stdout.length === 0) {
    return { err: 'ffmpeg produced no pixel data from ' + filePath };
  }
  return { buf: r.stdout };
}

const gates = {};

function setGate(name, status, detail) {
  gates[name] = { status, detail: detail || '' };
}
// ---------------------------------------------------------------------------
{
  const f = fileInfo('evidence-dossier.md');
  if (!f.exists) {
    setGate('evidence', 'missing', 'evidence-dossier.md not found');
  } else if (f.isDir) {
    setGate('evidence', 'broken', 'evidence-dossier.md is a directory');
    errors.push('evidence-dossier.md must be a file');
  } else if (f.size === 0) {
    setGate('evidence', 'broken', 'evidence-dossier.md is empty');
    errors.push('evidence-dossier.md is empty');
  } else {
    setGate('evidence', 'ok');
  }
}

// ---------------------------------------------------------------------------
// Gate: plan -- existence, size, AND all required ## headings
// ---------------------------------------------------------------------------
let planText = '';
{
  const f = fileInfo('showoff-plan.md');
  if (!f.exists) {
    setGate('plan', 'missing', 'showoff-plan.md not found');
  } else if (f.size === 0) {
    setGate('plan', 'broken', 'showoff-plan.md is empty');
    errors.push('showoff-plan.md is empty');
  } else {
    planText = readText('showoff-plan.md');
    const missingHeadings = REQUIRED_PLAN_HEADINGS.filter(
      (h) => !new RegExp('^## ' + h + '\\s*$', 'm').test(planText)
    );
    if (missingHeadings.length) {
      setGate('plan', 'broken',
        'showoff-plan.md missing required sections: ' + missingHeadings.join(', '));
      errors.push('showoff-plan.md missing required ## sections: ' + missingHeadings.join(', '));
    } else {
      setGate('plan', 'ok');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: review -- Gate 3 Review section must have all checklist items checked.
// Partial (incomplete review) is a warning before the manifest exists;
// a manifest that claims review passed while items are unchecked is an error.
// ---------------------------------------------------------------------------
{
  if (!planText) {
    setGate('review', 'missing',
      'showoff-plan.md not found or broken; Gate 3 Review cannot be evaluated');
  } else {
    const reviewText = extractSection(planText, 'Gate 3 Review');
    const allItems = reviewText.match(/^- \[[ x]\]/gim) || [];
    const unchecked = reviewText.match(/^- \[ \]/gim) || [];
    if (allItems.length === 0) {
      setGate('review', 'partial', 'Gate 3 Review has no checklist items');
      warnings.push('Gate 3 Review section has no checklist items (review not yet run)');
    } else if (unchecked.length > 0) {
      setGate('review', 'partial',
        'Gate 3 Review has ' + unchecked.length + ' unchecked item(s)');
      warnings.push('Gate 3 Review has ' + unchecked.length + ' unchecked item(s)');
    } else {
      setGate('review', 'ok', 'Gate 3 Review: all items checked');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: check -- Preflight Result B8 (npx hyperframes check).
// Partial before the manifest; a manifest claiming check passed while B8 is
// unchecked is caught by the cross-check.
// ---------------------------------------------------------------------------
{
  if (!planText) {
    setGate('check', 'missing',
      'showoff-plan.md not found or broken; Preflight B8 cannot be evaluated');
  } else {
    const preflightText = extractSection(planText, 'Preflight Result');
    const b8 = isItemChecked(preflightText, 'B8');
    if (b8 === true) {
      setGate('check', 'ok', 'Preflight B8 (hyperframes check) is checked');
    } else if (b8 === false) {
      setGate('check', 'partial', 'Preflight B8 (hyperframes check) is unchecked');
      warnings.push('Preflight B8 (hyperframes check) is present but not yet checked');
    } else {
      setGate('check', 'partial', 'Preflight B8 (hyperframes check) not found in Preflight Result');
      warnings.push('Preflight B8 (hyperframes check) not found in Preflight Result section');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: preview -- Preflight Result B9 (preview approval).
// ---------------------------------------------------------------------------
{
  if (!planText) {
    setGate('preview', 'missing',
      'showoff-plan.md not found or broken; Preflight B9 cannot be evaluated');
  } else {
    const preflightText = extractSection(planText, 'Preflight Result');
    const b9 = isItemChecked(preflightText, 'B9');
    if (b9 === true) {
      setGate('preview', 'ok', 'Preflight B9 (preview approval) is checked');
    } else if (b9 === false) {
      setGate('preview', 'partial', 'Preflight B9 (preview approval) is unchecked');
      warnings.push('Preflight B9 (preview approval) is present but not yet checked');
    } else {
      setGate('preview', 'partial', 'Preflight B9 (preview approval) not found in Preflight Result');
      warnings.push('Preflight B9 (preview approval) not found in Preflight Result section');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: composition (brief + HyperFrames project)
// ---------------------------------------------------------------------------
{
  const brief = fileInfo('composition-brief.md');
  const comp = fileInfo('composition');
  if (!brief.exists && !comp.exists) {
    setGate('composition', 'missing', 'composition-brief.md and composition/ not found');
  } else if (brief.exists && brief.size === 0) {
    setGate('composition', 'broken', 'composition-brief.md is empty');
    errors.push('composition-brief.md is empty');
  } else if (comp.exists && !comp.isDir) {
    setGate('composition', 'broken', 'composition/ is not a directory');
    errors.push('composition/ must be a directory');
  } else if (!comp.exists) {
    setGate('composition', 'partial', 'composition-brief.md present but composition/ not yet created');
    warnings.push('composition/ HyperFrames project not yet created');
  } else {
    const hasMarker =
      existsSync(join(runDir, 'composition', 'BRIEF.md')) ||
      existsSync(join(runDir, 'composition', 'package.json'));
    if (!hasMarker) {
      setGate('composition', 'partial', 'composition/ present but no BRIEF.md or package.json marker');
      warnings.push('composition/ has no recognizable HyperFrames marker (BRIEF.md or package.json)');
    } else if (!brief.exists) {
      setGate('composition', 'partial', 'composition/ present but composition-brief.md missing');
      warnings.push('composition-brief.md is missing');
    } else {
      setGate('composition', 'ok');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: render (video)
// ---------------------------------------------------------------------------
{
  const f = fileInfo('showoff.mp4');
  if (!f.exists) {
    setGate('render', 'missing', 'showoff.mp4 not found');
  } else if (f.isDir) {
    setGate('render', 'broken', 'showoff.mp4 is a directory');
    errors.push('showoff.mp4 must be a file');
  } else if (f.size === 0) {
    setGate('render', 'broken', 'showoff.mp4 is empty');
    errors.push('showoff.mp4 is empty');
  } else {
    setGate('render', 'ok');
  }
}

// ---------------------------------------------------------------------------
// Gate: poster -- file check then FFmpeg frame-zero match when video present.
// When both showoff.mp4 and showoff.jpg exist and are non-empty, both are
// decoded to raw rgb24 (no shell, spawnSync). Frame 0 of the video is
// compared to the poster's single frame by mean absolute error across all
// byte values. Threshold: POSTER_MAE_THRESHOLD (3.0). Absence of ffmpeg or
// any decode failure is a completion error -- this runtime requires FFmpeg.
// Partial-run semantics: when showoff.mp4 is not yet present the file-level
// check is sufficient and the pixel check is deferred.
// ---------------------------------------------------------------------------
{
  const f = fileInfo('showoff.jpg');
  if (!f.exists) {
    setGate('poster', 'missing', 'showoff.jpg not found');
  } else if (f.isDir) {
    setGate('poster', 'broken', 'showoff.jpg is a directory');
    errors.push('showoff.jpg must be a file');
  } else if (f.size === 0) {
    setGate('poster', 'broken', 'showoff.jpg is empty');
    errors.push('showoff.jpg is empty');
  } else {
    const v = fileInfo('showoff.mp4');
    if (v.exists && !v.isDir && v.size > 0) {
      // Both files are present and non-empty: verify poster pixel-matches frame 0.
      const videoPath = join(runDir, 'showoff.mp4');
      const posterPath = join(runDir, 'showoff.jpg');
      const vr = ffmpegRgb24(videoPath, true);
      if (vr.err) {
        setGate('poster', 'broken', 'frame-zero match: ffmpeg failed on video: ' + vr.err);
        errors.push(
          'showoff.jpg frame-zero match check failed: ' + vr.err +
          ' -- re-extract the poster from frame 0:' +
          ' ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg'
        );
      } else {
        const pr = ffmpegRgb24(posterPath, false);
        if (pr.err) {
          setGate('poster', 'broken', 'frame-zero match: ffmpeg failed on poster: ' + pr.err);
          errors.push(
            'showoff.jpg frame-zero match check failed: ' + pr.err +
            ' -- re-extract the poster from frame 0:' +
            ' ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg'
          );
        } else if (vr.buf.length !== pr.buf.length) {
          setGate('poster', 'broken',
            'showoff.jpg dimensions differ from video frame 0' +
            ' (video ' + vr.buf.length + 'B vs poster ' + pr.buf.length + 'B raw rgb24)'
          );
          errors.push(
            'showoff.jpg dimensions do not match video frame 0 (' +
            vr.buf.length + ' vs ' + pr.buf.length + ' raw rgb24 bytes)' +
            ' -- re-extract from frame 0: ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg'
          );
        } else {
          let diffSum = 0;
          const len = vr.buf.length;
          for (let i = 0; i < len; i++) {
            diffSum += Math.abs(vr.buf[i] - pr.buf[i]);
          }
          const mae = diffSum / len;
          if (mae > POSTER_MAE_THRESHOLD) {
            setGate('poster', 'broken',
              'showoff.jpg does not match video frame 0: MAE ' + mae.toFixed(2) +
              ' > threshold ' + POSTER_MAE_THRESHOLD
            );
            errors.push(
              'showoff.jpg frame-zero mismatch: MAE ' + mae.toFixed(2) +
              ' exceeds threshold ' + POSTER_MAE_THRESHOLD + '.' +
              ' A later settled frame (e.g. -ss 3.5) is never acceptable.' +
              ' Modify the composition initial state so frame 0 is fully settled,' +
              ' re-render, then re-extract:' +
              ' ffmpeg -i showoff.mp4 -vframes 1 -q:v 2 showoff.jpg'
            );
          } else {
            setGate('poster', 'ok',
              'showoff.jpg matches video frame 0 (MAE ' + mae.toFixed(2) + ')'
            );
          }
        }
      }
    } else {
      // showoff.mp4 not yet present; file-level check sufficient for now.
      setGate('poster', 'ok');
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: share copy
// ---------------------------------------------------------------------------
{
  const f = fileInfo('share-copy.md');
  if (!f.exists) {
    setGate('share', 'missing', 'share-copy.md not found');
  } else if (f.size === 0) {
    setGate('share', 'broken', 'share-copy.md is empty');
    errors.push('share-copy.md is empty');
  } else {
    setGate('share', 'ok');
  }
}

// ---------------------------------------------------------------------------
// Gate: manifest -- deep schema validation (delivery.md)
// ---------------------------------------------------------------------------
let manifest = null;
{
  const f = fileInfo('showoff-manifest.json');
  if (!f.exists) {
    setGate('manifest', 'missing', 'showoff-manifest.json not found');
  } else {
    const raw = readText('showoff-manifest.json');
    try {
      manifest = JSON.parse(raw);
    } catch (e) {
      setGate('manifest', 'broken', 'showoff-manifest.json is not valid JSON: ' + e.message);
      errors.push('showoff-manifest.json is not valid JSON');
    }

    if (manifest) {
      const mErrors = [];

      // Top-level required keys
      const requiredKeys = [
        'schema_version', 'showoff_version', 'produced_at',
        'project', 'config', 'dials', 'design_read', 'narration',
        'outputs', 'gates', 'reproducibility',
        'media_assets', 'claims', 'external_services_used', 'published',
      ];
      const missingKeys = requiredKeys.filter((k) => manifest[k] === undefined);
      if (missingKeys.length) {
        mErrors.push('missing required fields: ' + missingKeys.join(', '));
      }

      if (!mErrors.length) {
        // schema_version must be string "1"
        if (manifest.schema_version !== '1') {
          mErrors.push('schema_version must be the string "1", got: ' +
            JSON.stringify(manifest.schema_version));
        }
        // showoff_version
        if (manifest.showoff_version !== '0.1.0') {
          mErrors.push('showoff_version must be "0.1.0"');
        }
        // produced_at: nonempty ISO-looking string
        if (typeof manifest.produced_at !== 'string' || !manifest.produced_at ||
            !/\d{4}.*T.*:/.test(manifest.produced_at)) {
          mErrors.push('produced_at must be a nonempty ISO-8601 string');
        }
        // narration: boolean
        if (typeof manifest.narration !== 'boolean') {
          mErrors.push('narration must be a boolean');
        }
        // design_read: nonempty string
        if (typeof manifest.design_read !== 'string' || !manifest.design_read.trim()) {
          mErrors.push('design_read must be a nonempty string');
        }
        // published: always false
        if (manifest.published !== false) {
          mErrors.push('published must be false (ShowOff never automatically publishes)');
        }
        // misleading always-local flag
        if (manifest[LOCAL_ONLY_KEY] !== undefined) {
          mErrors.push('manifest must not include a misleading always-local field');
        }

        // project
        const proj = manifest.project;
        if (!proj || typeof proj !== 'object') {
          mErrors.push('project must be an object');
        } else {
          if (!proj.subject || typeof proj.subject !== 'string')
            mErrors.push('project.subject must be a nonempty string');
          if (!proj.source || typeof proj.source !== 'string')
            mErrors.push('project.source must be a nonempty string');
          if (!['pr-to-video', 'product-launch-video', 'general-video'].includes(proj.route))
            mErrors.push('project.route must be pr-to-video, product-launch-video, or general-video');
        }

        // config
        const cfg = manifest.config;
        if (!cfg || typeof cfg !== 'object') {
          mErrors.push('config must be an object');
        } else {
          if (!cfg.tone || typeof cfg.tone !== 'string')
            mErrors.push('config.tone must be a nonempty string');
          if (!['landscape', 'vertical', 'square'].includes(cfg.format))
            mErrors.push('config.format must be landscape, vertical, or square');
          if (!Number.isInteger(cfg.duration_s) || cfg.duration_s < 10 || cfg.duration_s > 90)
            mErrors.push('config.duration_s must be an integer 10-90');
          if (!cfg.audience || typeof cfg.audience !== 'string')
            mErrors.push('config.audience must be a nonempty string');
          if (!['demo', 'pitch', 'update', 'tutorial'].includes(cfg.goal))
            mErrors.push('config.goal must be demo, pitch, update, or tutorial');
          if (!cfg.title || typeof cfg.title !== 'string')
            mErrors.push('config.title must be a nonempty string');
        }

        // dials: all three required as integers 1-10
        const dials = manifest.dials;
        if (!dials || typeof dials !== 'object') {
          mErrors.push('dials must be an object');
        } else {
          for (const dial of ['DESIGN_VARIANCE', 'MOTION_INTENSITY', 'VISUAL_DENSITY']) {
            if (!Number.isInteger(dials[dial]) || dials[dial] < 1 || dials[dial] > 10)
              mErrors.push('dials.' + dial + ' must be an integer 1-10');
          }
        }

        // outputs: canonical paths and captions/transcript coupling
        const out = manifest.outputs;
        if (!out || typeof out !== 'object') {
          mErrors.push('outputs must be an object');
        } else {
          if (out.video !== 'showoff.mp4')
            mErrors.push('outputs.video must be "showoff.mp4"');
          if (out.thumbnail !== 'showoff.jpg')
            mErrors.push('outputs.thumbnail must be "showoff.jpg"');
          if (out.plan !== 'showoff-plan.md')
            mErrors.push('outputs.plan must be "showoff-plan.md"');
          if (out.brief !== 'composition-brief.md')
            mErrors.push('outputs.brief must be "composition-brief.md"');
          if (out.share_copy !== 'share-copy.md')
            mErrors.push('outputs.share_copy must be "share-copy.md"');
          if (manifest.narration === true) {
            if (typeof out.captions !== 'string' || !out.captions)
              mErrors.push('outputs.captions must be a nonempty filename when narration is true');
            if (typeof out.transcript !== 'string' || !out.transcript)
              mErrors.push('outputs.transcript must be a nonempty filename when narration is true');
          } else if (manifest.narration === false) {
            if (out.captions !== null)
              mErrors.push('outputs.captions must be null when narration is false');
            if (out.transcript !== null)
              mErrors.push('outputs.transcript must be null when narration is false');
          }
        }

        // reproducibility
        const repro = manifest.reproducibility;
        if (!repro || typeof repro !== 'object') {
          mErrors.push('reproducibility must be an object');
        } else {
          if (!repro.hyperframes_version || typeof repro.hyperframes_version !== 'string')
            mErrors.push('reproducibility.hyperframes_version must be a nonempty string');
          if (typeof repro.brief_hash !== 'string' || !/^[0-9a-f]{64}$/i.test(repro.brief_hash))
            mErrors.push('reproducibility.brief_hash must be a 64-character hexadecimal string');
          if (!Array.isArray(repro.evidence_sources) || repro.evidence_sources.length === 0)
            mErrors.push('reproducibility.evidence_sources must be a nonempty array');
        }

        // arrays
        if (!Array.isArray(manifest.media_assets))
          mErrors.push('media_assets must be an array');
        if (!Array.isArray(manifest.claims))
          mErrors.push('claims must be an array');
        if (!Array.isArray(manifest.external_services_used))
          mErrors.push('external_services_used must be an array');
      }

      if (mErrors.length) {
        setGate('manifest', 'broken', mErrors.join('; '));
        for (const e of mErrors) errors.push('manifest: ' + e);
      } else {
        setGate('manifest', 'ok');
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Gate: narration -- captions.vtt and transcript.md coupling
// ---------------------------------------------------------------------------
{
  const narrationOn = manifest ? manifest.narration === true : null;
  const captions = fileInfo('captions.vtt');
  const transcript = fileInfo('transcript.md');

  if (narrationOn === true) {
    if (!captions.exists || captions.size === 0) {
      setGate('narration', 'broken', 'narration enabled but captions.vtt is missing or empty');
      errors.push('narration enabled but captions.vtt is missing or empty');
    } else if (!transcript.exists || transcript.size === 0) {
      setGate('narration', 'broken', 'narration enabled but transcript.md is missing or empty');
      errors.push('narration enabled but transcript.md is missing or empty');
    } else {
      setGate('narration', 'ok', 'narration on; captions and transcript present');
    }
  } else if (narrationOn === false) {
    if (captions.exists || transcript.exists) {
      setGate('narration', 'broken', 'narration disabled but captions/transcript present');
      errors.push('narration disabled but captions.vtt or transcript.md present');
    } else {
      setGate('narration', 'ok', 'narration off; no captions or transcript');
    }
  } else {
    setGate('narration', 'unknown', 'narration flag not readable (manifest absent)');
  }
}

// ---------------------------------------------------------------------------
// Manifest gate self-report cross-check (reject falsely-claimed gates).
// Gate aliases: handoff -> composition, share-copy -> share; others 1:1.
// ---------------------------------------------------------------------------

if (manifest && manifest.gates && typeof manifest.gates === 'object') {
  for (const [name, claimed] of Object.entries(manifest.gates)) {
    const claimedPass =
      claimed === true ||
      claimed === 'pass' ||
      claimed === 'ok' ||
      (claimed && typeof claimed === 'object' &&
       (claimed.pass === true || claimed.status === 'ok'));
    if (!claimedPass) continue;
    const validatorGateName = GATE_ALIAS_MAP[name] || name;
    const actual = gates[validatorGateName];
    if (!actual || actual.status !== 'ok') {
      errors.push(
        'manifest claims gate "' + name + '" passed but actual status is "' +
          (actual ? actual.status : 'absent') + '"'
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Partial-run warnings: missing gates are warnings, not errors.
// (Partial-status gates add their own specific warnings in the gate blocks.)
// ---------------------------------------------------------------------------

for (const [name, g] of Object.entries(gates)) {
  if (g.status === 'missing') {
    warnings.push('gate "' + name + '" not yet produced: ' + g.detail);
  }
}

// ---------------------------------------------------------------------------
// Derive state
// ---------------------------------------------------------------------------

function ok(name) {
  return gates[name] && gates[name].status === 'ok';
}

function deriveState() {
  if (errors.length) return 'broken';
  // done: all mechanically verifiable gates pass (narration gate is always
  // resolved once the manifest is present, so ok('narration') is safe here).
  if (
    ok('evidence') && ok('plan') && ok('review') &&
    ok('composition') && ok('check') && ok('preview') &&
    ok('render') && ok('poster') && ok('share') &&
    ok('manifest') && ok('narration')
  ) {
    return 'done';
  }
  if (ok('poster') && ok('render')) return 'has-poster';
  if (ok('render')) return 'rendered';
  if (ok('composition')) return 'composing';
  if (ok('plan')) return 'has-plan';
  if (ok('evidence')) return 'has-evidence';
  return 'cold';
}

const state = deriveState();

const result = {
  runDir,
  state,
  valid: errors.length === 0,
  gates,
  errors,
  warnings,
};

process.stdout.write(JSON.stringify(result, null, 2) + '\n');
process.exit(errors.length ? 1 : 0);
