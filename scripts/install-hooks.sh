#!/bin/sh
# Point git at the versioned hooks dir (run once after cloning).
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
echo "hooks installed: core.hooksPath -> .githooks"
