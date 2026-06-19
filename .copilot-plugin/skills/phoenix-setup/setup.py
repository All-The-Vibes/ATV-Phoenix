#!/usr/bin/env python3
"""ATV-Phoenix setup — register the phoenix agent + MCP server into GitHub Copilot CLI.

Idempotent. Safe to re-run. Prints exactly what it changed.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

# The agent definition is the single source of truth at dist/phoenix.agent.md (also embedded into the
# phoenix-mcp binary at build time, so `doctor` can detect drift and re-sync). We read it here rather
# than duplicate it, so a fresh install always matches what the binary ships.


def find_repo(args) -> Path:
    if args.repo:
        return Path(args.repo).resolve()
    if os.environ.get("PHOENIX_REPO"):
        return Path(os.environ["PHOENIX_REPO"]).resolve()
    # walk up from CWD looking for Cargo.toml with name = phoenix
    cur = Path.cwd()
    for p in [cur, *cur.parents]:
        if (p / "Cargo.toml").exists() and "phoenix" in (p / "Cargo.toml").read_text(encoding="utf-8"):
            return p
    sys.exit("ERROR: could not locate the ATV-Phoenix repo. Pass --repo <path>.")


def ensure_binary(repo: Path) -> Path:
    exe = "phoenix-mcp.exe" if os.name == "nt" else "phoenix-mcp"
    binpath = repo / "target" / "release" / exe
    if binpath.exists():
        print(f"[phoenix] binary present: {binpath}")
        return binpath
    if not shutil.which("cargo"):
        sys.exit("ERROR: cargo not found and binary missing. Install Rust (https://rustup.rs) then re-run.")
    print("[phoenix] building release binary (cargo build --release)...")
    subprocess.run(["cargo", "build", "--release", "--bin", "phoenix-mcp"], cwd=repo, check=True)
    if not binpath.exists():
        sys.exit(f"ERROR: build finished but {binpath} not found.")
    return binpath


def copilot_home() -> Path:
    h = Path.home() / ".copilot"
    h.mkdir(parents=True, exist_ok=True)
    return h


def register_mcp(binpath: Path):
    cfg_path = copilot_home() / "mcp-config.json"
    cfg = {"mcpServers": {}}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg.setdefault("mcpServers", {})
    cfg["mcpServers"]["phoenix"] = {"type": "stdio", "command": str(binpath).replace("\\", "/")}
    # backup once
    bak = cfg_path.with_suffix(".json.phoenix-bak")
    if cfg_path.exists() and not bak.exists():
        shutil.copy2(cfg_path, bak)
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[phoenix] registered MCP server in {cfg_path}")


def install_agent(repo: Path, binpath: Path):
    agents = copilot_home() / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    template_path = repo / "dist" / "phoenix.agent.md"
    template = template_path.read_text(encoding="utf-8")
    dest = agents / "phoenix.agent.md"
    dest.write_text(template.replace("__PHOENIX_BIN__", str(binpath).replace("\\", "/")), encoding="utf-8")
    print(f"[phoenix] installed agent: {dest}")


def install_tokenmaster(repo: Path):
    """Install the BUNDLED TokenMasterX (vendor/token-master) for token-efficient code retrieval.
    It's the user's own MIT plugin, vendored so Phoenix is self-contained. Best-effort: needs graphify."""
    tm_setup = repo / "vendor" / "token-master" / "skills" / "token-master" / "setup.py"
    if not tm_setup.exists():
        return False
    if not shutil.which("graphify"):
        print("[phoenix] TokenMasterX bundled but graphify not found. Install it, then run:")
        print(f"          python {tm_setup} . --host=copilot   (and: uv tool install graphifyy)")
        return False
    try:
        env = dict(os.environ, TOKEN_MASTER_HOST="copilot")
        r = subprocess.run([sys.executable, str(tm_setup), str(Path.cwd()), "--host=copilot"],
                           capture_output=True, text=True, timeout=300, env=env)
        ok = r.returncode == 0
        print(f"[phoenix] TokenMasterX (bundled): {'installed/refreshed' if ok else 'setup returned ' + str(r.returncode)}")
        if not ok:
            print("          " + (r.stderr.strip()[:300] or r.stdout.strip()[:300]))
        return ok
    except Exception as e:
        print(f"[phoenix] TokenMasterX install skipped: {e}")
        return False


def check_companions(repo: Path):
    """Install the bundled TokenMasterX (token-efficient retrieval)."""
    print("\n[phoenix] companions:")
    install_tokenmaster(repo)


def install_skills(repo: Path, binpath: Path):
    """Copy Phoenix's bundled skills into the Copilot skills dir, then self-check them with `doctor`."""
    src = repo / "skills"
    if not src.exists():
        print("[phoenix] (no bundled skills dir found, skipping)")
        return
    dst = copilot_home() / "skills"
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for skill in sorted(src.iterdir()):
        if skill.is_dir() and (skill / "SKILL.md").exists():
            target = dst / skill.name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(skill, target)
            count += 1
    print(f"[phoenix] installed {count} bundled skills -> {dst}")
    # self-maintenance: Phoenix validates its OWN install (agent + skills + MCP registration) with its
    # own doctor — the same objective discipline it gives the agent. --home pins it to where we installed.
    try:
        r = subprocess.run([str(binpath), "doctor", "--home", str(copilot_home())],
                           capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        tail = (r.stderr.strip().splitlines() or [""])[-1]
        print(f"[phoenix] install self-check (doctor): {'OK' if ok else 'PROBLEMS'} — {tail}")
        if not ok:
            print("          run `phoenix-mcp doctor --fix` to repair.")
    except Exception as e:
        print(f"[phoenix] install self-check skipped: {e}")


def main():
    ap = argparse.ArgumentParser(description="Install ATV-Phoenix into GitHub Copilot CLI.")
    ap.add_argument("--repo", help="path to the ATV-Phoenix repo root")
    ap.add_argument("--no-companions", action="store_true", help="skip the companion-plugin recommendations")
    args = ap.parse_args()
    repo = find_repo(args)
    print(f"[phoenix] repo: {repo}")
    binpath = ensure_binary(repo)
    register_mcp(binpath)
    install_agent(repo, binpath)
    install_skills(repo, binpath)
    print("\n[phoenix] OK installed. Restart Copilot (or run `copilot --agent phoenix`).")
    print("[phoenix] Tools: phoenix_sense, phoenix_snapshot, phoenix_heal, phoenix_verify_trace")
    print("[phoenix] Bundled skills: phoenix (router) + think/plan/build/test/debug/context/review/ship + craft/typescript/design + self-heal/okf/doctor + goal/ralph/auto (18 skills)")
    print("[phoenix] If the agent ever won't load or a skill goes missing (e.g. after a Copilot update),")
    print("          run:  phoenix-mcp doctor --fix   (re-syncs the install to this build).")
    if not args.no_companions:
        check_companions(repo)


if __name__ == "__main__":
    main()


