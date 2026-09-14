---
type: Phoenix Skill
name: phoenix-deps
description: Dependency and supply-chain hygiene where the clean-room install is the objective gate — audit every package manager in the repo, rank remediation by exploitation evidence rather than severity label, disclose any manager that could not be audited, and stop at the no-op boundary instead of opening an empty dependency PR. Use when dependencies are outdated, a CVE needs remediating, a lockfile changed, a major bump needs a forward fix, a new package is being adopted, or the user says /phoenix-deps.
license: MIT
---

# phoenix-deps — a dependency change is a supply-chain decision, and it needs a gate

> Encodes the practice from [`jongio/skills` → `deps-doctor`](https://github.com/jongio/skills/tree/main/skills/deps-doctor)
> (MIT). That skill states the two hard rules as craft. Phoenix's contribution is to make them
> **gates**, because a rule an agent can talk its way past is not a rule.

## Overview

Everywhere else, Phoenix refuses to let an agent grade its own work. Dependencies are the one surface
where "I updated the packages" has historically been accepted on assertion. It shouldn't be — a dependency
bump is not a version edit, it is a decision to run someone else's new code inside your build.

So the gate is not "the manifest changed". **The gate is that the regenerated lockfile installs clean in
a fresh environment the way CI will, and the test suite is still green after it.**

## The gate

```
{"check":{"kind":"command_exit","target":["npm","ci"],"expect":0}}
```

Per-ecosystem equivalents — always the *clean-room* form, never the incremental one, because an
incremental install passes on a lockfile CI will reject:

| ecosystem | gate command |
|---|---|
| npm / pnpm / yarn | `npm ci` · `pnpm install --frozen-lockfile` · `yarn install --immutable` |
| Python | `uv sync --locked` · `pip install -r requirements.txt` in a fresh venv |
| Rust | `cargo build --locked` |
| Go | `go mod verify && go build ./...` |
| .NET / Java | `dotnet restore --locked-mode` · `mvn -B verify` |

Run the install gate **and** the test gate. A lockfile that resolves but breaks the suite is red.

## The loop

```
  inventory every manager ──► audit ──► is there a real change? ──no──► STOP. Report. No branch, no PR.
                                │                                        (the no-op boundary)
                               yes
                                ▼
                 resolve with lifecycle scripts DISABLED
                                │
                                ▼
                 review every package whose version or source changed
                                │
                                ▼
                 install for real ──► clean-room install gate (phoenix_sense)
                                │                    │
                              green                 red
                                │                    ▼
                                │       fix FORWARD — never --force, never downgrade
                                │                    │
                                ▼                    ▼
                        test gate ──────────────► re-sense
                                │
                                ▼
              report, naming every manager that came back BLOCKED
```

## The two rules that are gates, not advice

**1. Stop at the no-op boundary.** If the audit finds nothing that needs changing, produce **no branch, no
commit, no pull request** — a report is the deliverable. This is the charter's no-op bias in dependency
form. An empty dependency PR is not diligence; it is churn that costs a human a review cycle and teaches
the team to skim dependency PRs, which is how the real one gets waved through.

**2. A manager you could not audit is BLOCKED, and blocked is said out loud.** If a toolchain is missing,
a private registry won't authenticate, or a manager isn't installed, that manager is reported as blocked
**by name**. Never silently narrow the scope to what worked and report green. This is the silent-failure
SLO — the failure is not the gap, it is the undisclosed gap. **Always report coverage beside the result.**
"Clean across 4 of 6 managers, Maven and NuGet blocked" is honest; "dependencies are clean" is a lie with
the same green tint.

## Craft rules (each keeps the gate meaningful)

1. **Inventory before you audit.** Language managers (npm, pnpm, Yarn, pip, Pipenv, Poetry, uv, Go
   modules, Cargo, Bundler, Composer, NuGet, Maven, Gradle, SwiftPM, pub, Hex) *and* the surfaces no
   language manager owns — Docker base images, GitHub Actions pins, Terraform providers and modules, dev
   container features, pre-commit hook revisions. An audit that skips the unowned surfaces misses where
   much of the real supply-chain risk lives.
2. **Defer to the bot that already owns routine bumps.** If Dependabot or Renovate is configured, do not
   race it. Work the scope it leaves uncovered — the unowned surfaces, majors it won't take, and CVEs it
   has no fix path for. Two actors opening PRs against the same lockfile is a merge-conflict generator.
3. **Rank by exploitation evidence, not by severity label.** A High that appears in CISA's Known
   Exploited Vulnerabilities catalog outranks an unexploited Critical. Severity is a score; exploitation
   is a fact. Fix what is being used against people first.
4. **Resolve with lifecycle scripts disabled first.** `--ignore-scripts` (or the ecosystem equivalent) for
   the resolution pass, review what changed, *then* install for real. Install hooks execute arbitrary code
   at resolve time — running them before you have looked at the diff is trusting the package you are
   auditing to be worth auditing.
5. **Screen every new direct dependency.** Typosquatting against a popular name, install hooks,
   non-registry sources (a git URL or tarball), maintainer count and recency, license compatibility,
   registry provenance. A new dependency is a new author with commit access to your build.
6. **Withhold releases inside the minimum release age window.** A version published hours ago has had no
   exposure, and registry compromises are typically caught within days. Prefer a package-manager *setting*
   that protects every future install over a one-time manual date check — a setting is a gate, a habit is
   not.
7. **Reconcile declared against imported, and keep the reachable ones.** Unused-dependency tooling reads
   imports; it cannot see packages reached through configuration, plugin loading, or runtime resolution.
   Confirm before removing, or the "cleanup" is an outage.
8. **Fix forward. Never `--force`, never downgrade to dodge a peer conflict.** A force flag doesn't
   resolve the conflict, it suppresses the resolver's report of it, and the failure moves to runtime. A
   downgrade to green is the dependency equivalent of editing the test to match broken code.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Nothing changed, but I'll open the PR to show I ran it." | An empty dependency PR is churn. The report is the deliverable. Stop at the no-op boundary. |
| "Maven wasn't installed, but everything else was clean." | Then the result is "clean across N-1 managers, Maven blocked". Dropping it silently is a partial audit wearing a clean audit's face. |
| "It's only a patch bump, skip the clean-room install." | Patch bumps are exactly where a compromised release hides. The gate is cheap; run it. |
| "`--force` got the install through." | It suppressed the resolver's finding. The conflict is still there, now discovered at runtime. |
| "It's a Critical, fix it first." | Rank by exploitation evidence. A High in the KEV catalog is being used against people right now; an unexploited Critical is not. |
| "Dependabot handles this repo." | Then work the scope it doesn't cover — Docker images, Actions pins, Terraform, majors, unfixed CVEs. Don't duplicate its PRs. |
| "The lockfile resolved, so we're done." | Resolution is not installation. Prove the clean-room install CI will actually run. |

## Red Flags

- A dependency PR whose diff is only a lockfile timestamp or ordering change. → No-op. Close it.
- A green audit report that never names its coverage. → Ask which managers were audited; a missing denominator is a missing result.
- `--force` / `--legacy-peer-deps` / a downgrade added to make an install pass. → Fix forward; that flag is a gate hole.
- A new direct dependency added in the same PR as a routine bump. → Split it. New authors get their own review.
- Claiming done on an incremental install. → Run the clean-room gate; that is the one CI will run.

## Next

Pair with `phoenix-test` (the suite must be green *after* the install gate, not before),
`phoenix-build` (snapshot before a lockfile edit — lockfiles are exactly what `phoenix_heal` rollback is
for), and `phoenix-ship` (report coverage beside the result, never a bare green).
