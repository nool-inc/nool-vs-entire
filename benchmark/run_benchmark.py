#!/usr/bin/env python3
"""Reproducible Plain Git vs Entire vs Nool benchmark harness.

Every scenario runs in a fresh throwaway sandbox under a temp directory built
from the baseline commit of this repository. The live repository is only ever
*read* (versions, refs, `entire why`, `nool why`); nothing here commits,
merges, announces or proposes against it.

Each command is recorded with its exit code, wall-clock time and an output
excerpt, and the whole run is written to benchmark/results/latest.json (plus a
timestamped copy). `render_report.py` turns that JSON into
BENCHMARK_COMPARISON.md, so every claim in the report traces to a recorded run.

Usage: python3 benchmark/run_benchmark.py [--keep-sandboxes]
"""

import ast
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO, "benchmark", "results")
BASELINE_COMMIT = "53866f8"  # "add baseline auth service and test"
GIT_ID = ["-c", "user.name=bench", "-c", "user.email=bench@example.invalid"]
EXCERPT = 1500

OAUTH_METHOD = '''    def authenticate_oauth(self, provider: str, token: str) -> bool:
        """Authenticate via OAuth provider."""
        if provider not in ("google", "github"):
            return False
        return token.startswith("oauth-")
'''

SAML_METHOD = '''    def authenticate_saml(self, idp_entity_id: str, assertion_xml: str) -> bool:
        """Authenticate a SAML assertion from an identity provider."""
        if not idp_entity_id.endswith(".idp.example.com"):
            return False
        return "<saml:Assertion" in assertion_xml
'''

# Same-symbol collision: both branches rewrite the body of authenticate_user.
BASE_AUTH_BODY = 'return token == f"secret-{username}"'
OAUTH_AUTH_BODY = 'return token == f"secret-{username}" or token.startswith("oauth-")'
SAML_AUTH_BODY = 'return token == f"secret-{username}" and len(token) < 256'


class Recorder:
    """Runs commands and keeps a structured log of every step."""

    def __init__(self, sandbox_root):
        self.sandbox_root = sandbox_root

    def _clean(self, text):
        text = text.replace(self.sandbox_root, "<sandbox>")
        text = text.replace(os.path.realpath(self.sandbox_root), "<sandbox>")
        if len(text) > EXCERPT:
            text = "…" + text[-EXCERPT:]
        return text

    def run(self, steps, name, cmd, cwd, timeout=600, env=None):
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                  timeout=timeout, env=env)
            rc, out = proc.returncode, proc.stdout + proc.stderr
        except FileNotFoundError:
            rc, out = 127, f"command not found: {cmd[0]}"
        except subprocess.TimeoutExpired:
            rc, out = 124, f"timed out after {timeout}s"
        elapsed = round(time.monotonic() - start, 3)
        steps.append({
            "name": name,
            "cmd": " ".join(cmd),
            "rc": rc,
            "seconds": elapsed,
            "output": self._clean(out),
        })
        return rc, out, elapsed


# ---------------------------------------------------------------- helpers

def git(*args):
    return ["git", *GIT_ID, *args]


def make_sandbox(root, name):
    """A fresh git repo containing the baseline auth service and its test."""
    path = os.path.join(root, name)
    os.makedirs(os.path.join(path, "src"))
    os.makedirs(os.path.join(path, "tests"))
    for rel in ("src/auth.py", "tests/test_auth.py"):
        blob = subprocess.run(["git", "show", f"{BASELINE_COMMIT}:{rel}"], cwd=REPO,
                              capture_output=True, text=True, check=True).stdout
        with open(os.path.join(path, rel), "w") as f:
            f.write(blob)
    for rel in ("src/__init__.py", "tests/__init__.py"):
        open(os.path.join(path, rel), "w").close()
    with open(os.path.join(path, ".gitignore"), "w") as f:
        f.write("__pycache__/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(git("add", "-A"), cwd=path, check=True)
    subprocess.run(git("commit", "-qm", "baseline auth service"), cwd=path, check=True)
    return path


def edit_auth(path, transform):
    p = os.path.join(path, "src", "auth.py")
    with open(p) as f:
        s = f.read()
    with open(p, "w") as f:
        f.write(transform(s))


def insert_method(method):
    return lambda s: s.replace("    def get_user_role", method + "\n    def get_user_role", 1)


def replace_body(new_body):
    return lambda s: s.replace(BASE_AUTH_BODY, new_body, 1)


def make_branches(path, oauth_transform, saml_transform):
    """feat-oauth and feat-saml, both cut from main, each editing src/auth.py."""
    for branch, transform, msg in (("feat-oauth", oauth_transform, "feat: OAuth2"),
                                   ("feat-saml", saml_transform, "feat: SAML SSO")):
        subprocess.run(git("checkout", "-q", "-b", branch, "main"), cwd=path, check=True)
        edit_auth(path, transform)
        subprocess.run(git("commit", "-qam", msg), cwd=path, check=True)
    subprocess.run(git("checkout", "-q", "main"), cwd=path, check=True)


def inspect_auth(path):
    p = os.path.join(path, "src", "auth.py")
    with open(p) as f:
        src = f.read()
    info = {"conflict_markers": src.count("<<<<<<<"), "parses": True, "methods": []}
    try:
        tree = ast.parse(src)
        info["methods"] = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    except SyntaxError:
        info["parses"] = False
    info["authenticate_user_body"] = next(
        (b for b in (OAUTH_AUTH_BODY, SAML_AUTH_BODY, BASE_AUTH_BODY) if b in src), None)
    return info


def unit_tests(rec, steps, path):
    rc, _, _ = rec.run(steps, "unit tests", [sys.executable, "-m", "unittest", "tests.test_auth"], path)
    return rc == 0


def nool_init(rec, steps, path):
    rec.run(steps, "nool init", ["nool", "init", "--skip-discovery"], path)
    rec.run(steps, "record nool.toml", ["nool", "propose", "--path", "nool.toml", "--kind", "config",
                                        "--intent", "record config", "--justification", "benchmark sandbox",
                                        "--solidify"], path)
    rec.run(steps, "record ignore files", ["nool", "propose", "--path", ".gitignore", "--path", ".gitattributes",
                                           "--path", ".noolignore", "--kind", "config",
                                           "--intent", "record config", "--solidify"], path)
    rec.run(steps, "record baseline", ["nool", "propose", "--path", "src/auth.py", "--path", "tests/test_auth.py",
                                       "--path", "src/__init__.py", "--path", "tests/__init__.py",
                                       "--intent", "baseline auth service", "--solidify"], path)


def version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip().splitlines()[0]
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        return f"unavailable ({exc.__class__.__name__})"


# ---------------------------------------------------------------- scenarios

def scenario_plain_git(rec, root, transforms, label):
    steps = []
    path = make_sandbox(root, f"git-{label}")
    make_branches(path, *transforms)
    subprocess.run(git("checkout", "-q", "feat-oauth"), cwd=path, check=True)
    rc, _, t = rec.run(steps, "git merge feat-saml", git("merge", "feat-saml"), path)
    state = inspect_auth(path)
    return {
        "tool": "plain-git", "variant": label, "steps": steps,
        "merge_rc": rc, "merge_seconds": t,
        "conflict_detected_at": "merge" if rc != 0 else None,
        "manual_resolution_required": rc != 0,
        "result": state,
        "tests_pass_without_manual_edit": rc == 0 and unit_tests(rec, steps, path),
    }


def scenario_entire(rec, root):
    steps = []
    path = make_sandbox(root, "entire-disjoint")
    make_branches(path, insert_method(OAUTH_METHOD), insert_method(SAML_METHOD))
    subprocess.run(git("checkout", "-q", "feat-oauth"), cwd=path, check=True)
    rc_enable, _, _ = rec.run(steps, "entire enable", ["entire", "enable", "--agent", "claude-code", "--local"], path)
    hooks = sorted(h for h in os.listdir(os.path.join(path, ".git", "hooks")) if not h.endswith(".sample"))
    rc, _, t = rec.run(steps, "git merge feat-saml (Entire hooks installed)", git("merge", "feat-saml"), path)
    return {
        "tool": "entire", "variant": "disjoint", "steps": steps,
        "enabled": rc_enable == 0, "git_hooks_installed": hooks,
        "has_merge_hook": any("merge" in h for h in hooks),
        "merge_rc": rc, "merge_seconds": t,
        "conflict_detected_at": "merge" if rc != 0 else None,
        "manual_resolution_required": rc != 0,
        "result": inspect_auth(path),
    }


def scenario_nool_merge(rec, root, transforms, label):
    steps = []
    path = make_sandbox(root, f"nool-{label}")
    nool_init(rec, steps, path)
    make_branches(path, *transforms)
    rc1, _, t1 = rec.run(steps, "nool merge feat-oauth", ["nool", "merge", "feat-oauth"], path)
    rc2, out2, t2 = rec.run(steps, "nool merge feat-saml", ["nool", "merge", "feat-saml"], path)
    rec.run(steps, "nool candidate list", ["nool", "candidate", "list"], path)
    state = inspect_auth(path)
    clean = rc1 == 0 and rc2 == 0 and state["conflict_markers"] == 0 and state["parses"]
    return {
        "tool": "nool", "variant": label, "steps": steps,
        "merge_rc": [rc1, rc2], "merge_seconds": round(t1 + t2, 3),
        "textual_conflict_seen": "CONFLICT (content)" in out2,
        "union_reconciled": "Unioned" in out2,
        # What Nool's semantic engine *said* before the textual merge ran.
        "semantic_engine_reported_no_collision": "no same-symbol collisions" in out2,
        "manual_resolution_required": not clean,
        "result": state,
        "tests_pass_without_manual_edit": clean and unit_tests(rec, steps, path),
    }


def scenario_nool_coordination(rec, root):
    steps = []
    path = make_sandbox(root, "nool-coord")
    nool_init(rec, steps, path)
    scope = "file:src/auth.py"
    rc_a, _, t_a = rec.run(steps, "agent-oauth announces exclusive lease",
                           ["nool", "announce", "intent", "--intent", "implement OAuth2", "--target-nodes", scope,
                            "--agent-id", "agent-oauth", "--mode", "exclusive",
                            "--estimated-duration-ms", "600000"], path)
    rc_d, out_d, t_d = rec.run(steps, "agent-saml discovers conflicts",
                               ["nool", "discover", "conflicts", scope, "--as-agent", "agent-saml", "--json"], path)
    try:
        discover = json.loads(out_d[out_d.index("{"):out_d.rindex("}") + 1])
    except ValueError:
        discover = {}
    rc_b, _, t_b = rec.run(steps, "agent-saml announces exclusive lease on same file",
                           ["nool", "announce", "intent", "--intent", "implement SAML", "--target-nodes", scope,
                            "--agent-id", "agent-saml", "--mode", "exclusive",
                            "--estimated-duration-ms", "600000"], path)
    edit_auth(path, insert_method(SAML_METHOD))
    rc_p, out_p, t_p = rec.run(steps, "agent-saml proposes into the leased file anyway",
                               ["nool", "propose", "--path", "src/auth.py", "--intent", "implement SAML",
                                "--as-agent", "agent-saml"], path)
    rec.run(steps, "agent-oauth releases lease",
            ["nool", "announce", "release", "--all", "--agent-id", "agent-oauth"], path)
    rc_w, _, _ = rec.run(steps, "agent-saml re-discovers after release",
                         ["nool", "discover", "conflicts", scope, "--as-agent", "agent-saml", "--json"], path)
    # Two "agents" that do NOT pass distinct identities share the session identity.
    rc_s1, _, _ = rec.run(steps, "anonymous agent 1 announces exclusive",
                          ["nool", "announce", "intent", "--intent", "alpha", "--target-nodes", scope,
                           "--mode", "exclusive", "--estimated-duration-ms", "60000"], path)
    rc_s2, _, _ = rec.run(steps, "anonymous agent 2 announces exclusive on same file",
                          ["nool", "announce", "intent", "--intent", "beta", "--target-nodes", scope,
                           "--mode", "exclusive", "--estimated-duration-ms", "60000"], path)
    _, st, _ = rec.run(steps, "nool announce status", ["nool", "announce", "status"], path)
    rec.run(steps, "release", ["nool", "announce", "release", "--all"], path)
    return {
        "shared_identity_second_announce_granted": rc_s1 == 0 and rc_s2 == 0,
        "shared_identity_active_leases": int(st.split("Active leases (", 1)[1].split(",", 1)[0])
        if "Active leases (" in st else 0,
        "tool": "nool", "variant": "coordination", "steps": steps,
        "lease_granted": rc_a == 0, "announce_seconds": t_a,
        "conflict_discovered": bool(discover.get("has_conflicts")),
        "discover_rc": rc_d, "discover_seconds": t_d,
        "discovered_holder": [c.get("agent_label") for c in discover.get("conflicts", [])],
        "second_exclusive_announce_refused": rc_b != 0,
        "lease_violating_propose_refused": rc_p != 0 and "Coordination conflict" in out_p,
        "propose_seconds": t_p,
        "clear_after_release": rc_w == 0,
    }


def scenario_aram_provenance(rec, root):
    """Does `require_entire_provenance` stop an AI-tagged change with no Entire link?"""
    if not os.path.isdir(os.path.join(REPO, "policies")):
        return {"skipped": "policies/ not present in this checkout"}
    steps = []
    path = make_sandbox(root, "nool-aram")
    rec.run(steps, "nool init", ["nool", "init", "--skip-discovery"], path)
    shutil.copytree(os.path.join(REPO, "policies"), os.path.join(path, "policies"))
    cfg = os.path.join(path, "nool.toml")
    with open(cfg) as f:
        s = f.read()
    s = s.replace("rules = []", 'rules = ["require_entire_provenance"]', 1)
    s = s.replace("[invariants.rule_definitions]", """[invariants.rule_definitions.require_entire_provenance]
description = "All AI-generated changes must carry verified Entire Checkpoint trailers"
when_pattern = "has_metadata('is_ai_agent')"
then_requirement = "has_link('entire_checkpoint')"
severity = "error\"""", 1)
    with open(cfg, "w") as f:
        f.write(s)

    def attempt(label, *extra):
        edit_auth(path, lambda s: s + f"\n# {label}\n")
        rc, out, _ = rec.run(steps, label, ["nool", "propose", "--path", "src/auth.py", "--intent", label,
                                            *extra, "--solidify"], path)
        subprocess.run(["nool", "candidate", "clear"], cwd=path, capture_output=True)
        return {"rc": rc, "landed": rc == 0, "policy_deny": "POLICY_DENY" in out}

    # With a policy present, Aram refuses agent edits until an editor contract exists.
    no_contract = attempt("AI-tagged change before any editor contract", "--tag", "is_ai_agent")
    rec.run(steps, "grant editor contract", ["nool", "admin", "contract", "grant", "--role", "editor"], path)
    # Land the invariant and the policy set *before* testing, so the rule is in force.
    rc_cfg, _, _ = rec.run(steps, "land nool.toml with invariant",
                           ["nool", "propose", "--path", "nool.toml", "--kind", "config",
                            "--intent", "provenance invariant", "--justification", "benchmark", "--solidify"], path)
    rec.run(steps, "land ignore files", ["nool", "propose", "--path", ".gitignore", "--path", ".gitattributes",
                                         "--path", ".noolignore", "--kind", "config", "--intent", "config",
                                         "--solidify"], path)
    rc_pol, _, _ = rec.run(steps, "land policy set",
                           ["nool", "propose", "--path", "policies/entire_policy_test.toml",
                            "--path", "policies/entire_policy_test.wasm", "--binary", "raw",
                            "--intent", "policy set", "--solidify"], path)
    rec.run(steps, "nool admin plugin land", ["nool", "admin", "plugin", "land"], path)
    subprocess.run(["git", "checkout", "-q", "--", "src/auth.py"], cwd=path)
    rec.run(steps, "record baseline", ["nool", "propose", "--path", "src/auth.py", "--path", "tests/test_auth.py",
                                       "--path", "src/__init__.py", "--path", "tests/__init__.py",
                                       "--intent", "baseline", "--solidify"], path)
    ai_no_link = attempt("AI-tagged change, no Entire link", "--tag", "is_ai_agent")
    control = attempt("untagged change (control)")
    _, verify_out, _ = rec.run(steps, "nool verify --all", ["nool", "verify", "--all"], path)
    _, plugins, _ = rec.run(steps, "nool admin plugin list", ["nool", "admin", "plugin", "list"], path)
    with open(os.path.join(REPO, "policies", "entire_policy_test.wasm"), "rb") as f:
        wasm = f.read().lower()
    return {
        "tool": "nool", "variant": "aram-provenance", "steps": steps,
        "gate_denies_without_editor_contract": no_contract["policy_deny"],
        "invariant_config_landed": rc_cfg == 0,
        "policy_set_landed": rc_pol == 0,
        "ai_change_without_entire_link": ai_no_link,
        "untagged_control": control,
        "provenance_rule_enforced": not ai_no_link["landed"],
        "verify_reports_violation": "0 violations" not in verify_out,
        "policy_outdated_warning": "rebuild it" in plugins,
        "wasm_mentions_entire_or_checkpoint": any(w in wasm for w in (b"entire", b"checkpoint", b"is_ai_agent")),
    }


def scenario_nool_workflow(rec, root):
    """Session/workflow surface: context, checkpoint, handoff, PR summary, PR merge."""
    steps = []
    path = make_sandbox(root, "nool-workflow")
    nool_init(rec, steps, path)
    base = subprocess.run(["nool", "log"], cwd=path, capture_output=True, text=True).stdout
    base_knot = [l.split()[0] for l in base.splitlines() if l[:8].isalnum() and " [" in l[:12]][-1]
    rec.run(steps, "nool discover features", ["nool", "discover", "features"], path)
    rec.run(steps, "nool discover lift", ["nool", "discover", "lift"], path)
    rec.run(steps, "solidify lift", ["nool", "solidify"], path)
    _, ctx_nl, t_nl = rec.run(steps, "nool context (natural language)",
                              ["nool", "context", "add OAuth2 authentication", "--cite", "--budget", "800"], path)
    _, ctx_sym, t_sym = rec.run(steps, "nool context (symbol names)",
                                ["nool", "context", "AuthService authenticate_user", "--cite", "--budget", "800"], path)
    rc_cp, _, t_cp = rec.run(steps, "nool checkpoint", ["nool", "checkpoint", "bench-cp-1", "--solidify"], path)
    rc_ho, out_ho, t_ho = rec.run(steps, "nool thread handoff",
                                  ["nool", "thread", "handoff", "--name", "main",
                                   "--summary", "OAuth2 work paused; baseline green",
                                   "--decision", "keep authenticate_user unchanged",
                                   "--next", "add authenticate_oauth", "--solidify"], path)
    rc_pr, out_pr, t_pr = rec.run(steps, "nool pr summary", ["nool", "pr", "summary", "--base", base_knot], path)
    # PR merge through a local bare "origin" holding a feature branch.
    origin = os.path.join(root, "nool-workflow-origin.git")
    subprocess.run(["git", "init", "-q", "--bare", origin], check=True)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=path, check=True)
    subprocess.run(git("checkout", "-q", "-b", "feature/oauth", "main"), cwd=path, check=True)
    edit_auth(path, insert_method(OAUTH_METHOD))
    subprocess.run(git("commit", "-qam", "feat: OAuth2"), cwd=path, check=True)
    subprocess.run(["git", "push", "-q", "origin", "feature/oauth"], cwd=path, capture_output=True)
    subprocess.run(git("checkout", "-q", "main"), cwd=path, check=True)
    rc_pm, _, t_pm = rec.run(steps, "nool pr merge feature/oauth --into main",
                             ["nool", "pr", "merge", "feature/oauth", "--into", "main"], path)
    log = subprocess.run(["nool", "log"], cwd=path, capture_output=True, text=True).stdout
    return {
        "tool": "nool", "variant": "workflow", "steps": steps,
        "context_nl_matched_entities": "No matching entities" not in ctx_nl, "context_nl_seconds": t_nl,
        "context_symbol_matched_entities": "Entities (" in ctx_sym, "context_symbol_seconds": t_sym,
        "context_symbol_has_blast_radius": "Blast radius" in ctx_sym,
        "checkpoint_ok": rc_cp == 0 and "Release" in log, "checkpoint_seconds": t_cp,
        "handoff_ok": rc_ho == 0 and "Handoff" in log, "handoff_seconds": t_ho,
        "pr_summary_ok": rc_pr == 0 and "Nool Review Context" in out_pr, "pr_summary_seconds": t_pr,
        "pr_summary_has_blast_radius": "Blast Radius" in out_pr,
        "pr_merge_ok": rc_pm == 0, "pr_merge_seconds": t_pm,
        "pr_merge_method_present": "authenticate_oauth" in inspect_auth(path)["methods"],
    }


def live_repo_evidence(rec):
    """Read-only facts from the live repository."""
    steps = []
    _, refs, _ = rec.run(steps, "git show-ref", ["git", "show-ref"], REPO)
    names = [line.split()[-1] for line in refs.splitlines() if line.strip()]
    entire_refs = [n for n in names if n.startswith("refs/entire/")]
    nool_refs = [n for n in names if n.startswith("refs/nool/")]
    rc_why, why, _ = rec.run(steps, "entire why src/auth.py", ["entire", "why", "src/auth.py"], REPO)
    rc_nwhy, nwhy, _ = rec.run(steps, "nool why 77d3bf0c", ["nool", "why", "77d3bf0c"], REPO)
    _, cands, _ = rec.run(steps, "nool candidate list", ["nool", "candidate", "list"], REPO)
    _, plugins, _ = rec.run(steps, "nool admin plugin list", ["nool", "admin", "plugin", "list"], REPO)
    # Entire's session surface (all read-only).
    rc_cl, _, _ = rec.run(steps, "entire checkpoint list", ["entire", "checkpoint", "list"], REPO)
    rc_sl, sessions, _ = rec.run(steps, "entire session list", ["entire", "session", "list"], REPO)
    cp_ids = [n.rsplit("/", 1)[-1] for n in entire_refs if "/checkpoints/" in n]
    explain = ""
    if cp_ids:
        _, explain, _ = rec.run(steps, "entire checkpoint explain", ["entire", "checkpoint", "explain", cp_ids[0]], REPO)
    remote_needed = {}
    for sub in (["recap"], ["dispatch"], ["search", "OAuth2"]):
        rc, out, _ = rec.run(steps, "entire " + " ".join(sub), ["entire", *sub], REPO)
        remote_needed[sub[0]] = {"rc": rc, "reason": out.strip().splitlines()[-1][:160] if out.strip() else ""}
    return {
        "entire_checkpoint_list_ok": rc_cl == 0,
        "entire_session_list_ok": rc_sl == 0,
        "entire_sessions_listed": sessions.count("session "),
        "entire_explain_shows_prompt_intent": "## Intent" in explain,
        "entire_commands_needing_login_or_remote": remote_needed,
        "nool_context_live_returns_findings": "Prior findings" in subprocess.run(
            ["nool", "context", "add OAuth2 authentication", "--budget", "800"], cwd=REPO,
            capture_output=True, text=True).stdout,
        "steps": steps,
        "entire_ref_count": len(entire_refs),
        "nool_ref_count": len(nool_refs),
        "ref_namespace_overlap": sorted(set(entire_refs) & set(nool_refs)),
        "entire_why_rc": rc_why,
        "entire_why_links_checkpoint": "linked to a checkpoint" in why,
        "nool_why_rc": rc_nwhy,
        "nool_why_shows_chain": "Causal Chain" in nwhy,
        "pending_candidates": cands.strip().splitlines()[0] if cands.strip() else "",
        "live_policy_outdated": "rebuild it" in plugins,
    }


# ---------------------------------------------------------------- main

def main():
    keep = "--keep-sandboxes" in sys.argv
    root = tempfile.mkdtemp(prefix="nool-entire-bench-")
    rec = Recorder(root)
    started = dt.datetime.now(dt.timezone.utc)
    disjoint = (insert_method(OAUTH_METHOD), insert_method(SAML_METHOD))
    collision = (replace_body(OAUTH_AUTH_BODY), replace_body(SAML_AUTH_BODY))
    plan = [
        ("plain_git_disjoint", lambda: scenario_plain_git(rec, root, disjoint, "disjoint")),
        ("plain_git_same_symbol", lambda: scenario_plain_git(rec, root, collision, "same-symbol")),
        ("entire_disjoint", lambda: scenario_entire(rec, root)),
        ("nool_merge_disjoint", lambda: scenario_nool_merge(rec, root, disjoint, "disjoint")),
        ("nool_merge_same_symbol", lambda: scenario_nool_merge(rec, root, collision, "same-symbol")),
        ("nool_coordination", lambda: scenario_nool_coordination(rec, root)),
        ("nool_aram_provenance", lambda: scenario_aram_provenance(rec, root)),
        ("nool_workflow", lambda: scenario_nool_workflow(rec, root)),
        ("live_repo", lambda: live_repo_evidence(rec)),
    ]
    scenarios = {}
    try:
        for key, fn in plan:
            print(f"  • {key} …", flush=True)
            t0 = time.monotonic()
            try:
                scenarios[key] = fn()
            except Exception as exc:  # noqa: BLE001 - a broken scenario is a recorded result
                scenarios[key] = {"error": f"{exc.__class__.__name__}: {exc}"}
            scenarios[key]["scenario_seconds"] = round(time.monotonic() - t0, 2)
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)

    results = {
        "generated_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
        "baseline_commit": BASELINE_COMMIT,
        "environment": {
            "nool": version(["nool", "--version"]),
            "entire": version(["entire", "--version"]),
            "git": version(["git", "--version"]),
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        },
        "scenarios": scenarios,
    }
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    for name in ("latest.json", f"run-{stamp}.json"):
        with open(os.path.join(RESULTS_DIR, name), "w") as f:
            json.dump(results, f, indent=2)
    print(f"wrote benchmark/results/latest.json and run-{stamp}.json"
          + (f" (sandboxes kept in {root})" if keep else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
