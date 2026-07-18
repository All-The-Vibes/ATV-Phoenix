#!/usr/bin/env bash
# ATV-Phoenix Ralph loop driver (bash twin of phoenix-ralph.ps1).
# Geoffrey Huntley's loop (https://ghuntley.com/ralph), Phoenix-gated: the DRIVER proves completion
# via `phoenix-mcp accept` (failure-first, intact trace) — the agent only proposes.
set -uo pipefail

DIR="${PHOENIX_RALPH_DIR:-.phoenix-ralph}"
MAX_LOOPS="${MAX_LOOPS:-50}"
MAX_MINUTES="${MAX_MINUTES:-120}"
NO_PROGRESS_STOP="${NO_PROGRESS_STOP:-3}"
ALLOW_PREGREEN="${ALLOW_PREGREEN:-0}"
NO_TAG="${NO_TAG:-0}"
RESCOPE=0

for arg in "$@"; do
  case "$arg" in
    --rescope) RESCOPE=1 ;;
    *) printf '\033[31m[ralph] FATAL: unknown argument: %s\033[0m\n' "$arg"; exit 2 ;;
  esac
done

repo="$(pwd)"
state="$repo/$DIR"
done_check="$state/done-check.json"
acceptance_contract="$state/acceptance-contract.json"
acceptance_contract_arg="${acceptance_contract#"$repo/"}"
prompt="$state/PROMPT.md"
trace="$repo/.phoenix/trace.jsonl"
backlog="$state/backlog.json"
export PHOENIX_WORKSPACE="$repo"

info(){ printf '\033[36m[ralph] %s\033[0m\n' "$*"; }
warn(){ printf '\033[33m[ralph] %s\033[0m\n' "$*"; }
die(){  printf '\033[31m[ralph] FATAL: %s\033[0m\n' "$*"; exit 2; }
sig(){ [ -f "$1" ] && sha256sum "$1" | cut -d' ' -f1 || echo absent; }

# locate binaries
PHOENIX_BIN="${PHOENIX_BIN:-}"
if [ -z "$PHOENIX_BIN" ]; then
  for c in "$repo/target/release/phoenix-mcp" "$repo/target/debug/phoenix-mcp"; do [ -x "$c" ] && PHOENIX_BIN="$c" && break; done
  [ -z "$PHOENIX_BIN" ] && command -v phoenix-mcp >/dev/null && PHOENIX_BIN="phoenix-mcp"
fi
[ -z "$PHOENIX_BIN" ] && die "phoenix-mcp not found (cargo build --release, or set PHOENIX_BIN)."
COP="${COPILOT:-}"; [ -z "$COP" ] && command -v copilot >/dev/null && COP="copilot"
[ -z "$COP" ] && die "copilot CLI not found (set COPILOT)."

[ -f "$done_check" ] || die "missing $done_check"
[ -f "$prompt" ] || die "missing $prompt"
done_arg="@$done_check"   # pass by @file (robust across shells)

validate_contract(){
  "$PHOENIX_BIN" contract-validate "$acceptance_contract_arg" "$done_arg" >/dev/null ||
    die "acceptance contract mismatch $1 — stopping; use --rescope only with an intentional currently-RED replacement."
}

info "binaries: phoenix=$PHOENIX_BIN copilot=$COP"
info "baseline sense of done-check..."
"$PHOENIX_BIN" sense "$done_arg" >/dev/null
if [ $? -eq 0 ] && [ "$ALLOW_PREGREEN" != "1" ]; then
  die "done-check is ALREADY GREEN at start — can't prove failure-first (vacuous). Re-target it, or set ALLOW_PREGREEN=1."
fi

if [ "$RESCOPE" = "1" ]; then
  info "explicitly re-scoping acceptance contract..."
  "$PHOENIX_BIN" contract-rescope "$acceptance_contract_arg" "$done_arg" >/dev/null ||
    die "acceptance contract re-scope rejected; the replacement must be currently RED."
else
  info "freezing initial acceptance contract..."
  "$PHOENIX_BIN" contract-freeze "$acceptance_contract_arg" "$done_arg" >/dev/null ||
    die "acceptance contract freeze rejected; refusing to run with a changed or non-RED done-check."
fi

start=$(date +%s); no_progress=0; last_sig=""; loop=0
while [ "$loop" -lt "$MAX_LOOPS" ]; do
  loop=$((loop+1))
  elapsed_min=$(( ( $(date +%s) - start ) / 60 ))
  [ "$elapsed_min" -ge "$MAX_MINUTES" ] && { warn "wall-clock budget reached."; break; }

  validate_contract "before accept"
  "$PHOENIX_BIN" accept "$done_arg" >/dev/null 2>&1 && { info "done-check ACCEPTED. Goal proven complete."; break; }

  info "iteration $loop/$MAX_LOOPS — invoking agent (fresh context)..."
  flat="$(tr '\n' ' ' < "$prompt")"
  "$COP" -p "$flat" --allow-all-tools --allow-all-paths --add-dir "$repo" || warn "copilot exited $?."

  validate_contract "after agent iteration $loop"
  "$PHOENIX_BIN" verify-trace >/dev/null 2>&1 || die "trace chain BROKEN after iteration $loop."

  cur_sig="$(sig "$trace")|$(sig "$backlog")"
  if [ "$cur_sig" = "$last_sig" ]; then no_progress=$((no_progress+1)); warn "no state change ($no_progress/$NO_PROGRESS_STOP)."; else no_progress=0; fi
  last_sig="$cur_sig"
  [ "$no_progress" -ge "$NO_PROGRESS_STOP" ] && { warn "no progress — stopping (stuck)."; break; }
done

validate_contract "before accept"
if final_accept="$("$PHOENIX_BIN" accept "$done_arg" 2>&1)"; then
  cat > "$state/completed.json" <<EOF
{"completed_at":"$(date -u +%FT%TZ)","iterations":$loop,"trace_sha256":"$(sig "$trace")","backlog_sha256":"$(sig "$backlog")"}
EOF
  info "COMPLETE in $loop iterations. Proof -> $DIR/completed.json"
  if [ "$NO_TAG" != "1" ] && [ -d "$repo/.git" ]; then
    tag="phoenix-ralph-$(date +%Y%m%d-%H%M%S)"
    git -C "$repo" tag -a "$tag" -m "phoenix-ralph: done-check proven failure-first ($loop iterations)" 2>/dev/null && info "git tag: $tag"
  fi
  exit 0
else
  warn "stopped WITHOUT proving the done-check ($loop iterations)."
  printf '%s\n' "$final_accept"
  exit 1
fi
