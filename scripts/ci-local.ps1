#!/usr/bin/env pwsh
# Windows-native local CI gate - identical checks to scripts/ci-local.sh.
# Run before pushing, or let .githooks/pre-push run the .sh version automatically.
#
# tests/test_release_drift.py asserts this file and ci-local.sh gate the same targets.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step([string]$name, [string]$cmd) {
    Write-Host "== $name ==" -ForegroundColor Cyan
    & ([scriptblock]::Create($cmd))
    if ($LASTEXITCODE -ne 0) { Write-Error "ci-local FAILED: $name"; exit 1 }
}

Step 'cargo test --locked'             'cargo test --locked'
Step 'pytest tests/okf'                'python -m pytest tests/okf -q'
Step 'pytest phoenix_learn'            'python -m pytest tests/test_phoenix_learn.py tests/test_phoenix_learn_optimize.py -q'
Step 'pytest cloud contracts'          'python -m pytest tests/test_cloud_setup.py tests/test_cloud_proof_workflow.py -q'
Step 'pytest release metadata'         'python -m pytest tests/test_version_consistency.py tests/test_release_drift.py -q'
Step 'release drift'                   'python scripts/release_drift.py'
Step 'okf_validate (code bundle)'      'python skills/phoenix-okf/scripts/okf_validate.py examples/okf-code-graph'
Step 'okf_validate (external, strict)' 'python skills/phoenix-okf/scripts/okf_validate.py examples/okf-external-demo --strict-links'

Write-Host 'ci-local: ALL GREEN' -ForegroundColor Green
