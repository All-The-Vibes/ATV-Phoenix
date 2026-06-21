#!/usr/bin/env pwsh
# Point git at the versioned hooks dir so the local CI gate is shared across clones,
# not hidden in each clone's .git/hooks. Run once after cloning.
Set-Location (Split-Path $PSScriptRoot -Parent)
git config core.hooksPath .githooks
Write-Host 'hooks installed: core.hooksPath -> .githooks' -ForegroundColor Green
