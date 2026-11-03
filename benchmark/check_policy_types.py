#!/usr/bin/env python3
"""Exercise each live policy type against the installed Nool in a throwaway repo.

The probe copies this checkout's DSL policy files and checker into a sandbox,
configures the same `[rules]`, `[attestation]` and `[invariants]` settings, and
records whether each rule allows or refuses a representative change. It never
touches the live repository. Results go to benchmark/results/policy-types.json.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import secrets
import string
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_benchmark import Recorder, make_sandbox, nool_init  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "benchmark" / "results" / "policy-types.json"
CHECKPOINT_ID = "01M6CRZR6WVBD2GAEE84042PZA"
GIT_ID = ["-c", "user.name=policy-probe", "-c", "user.email=probe@example.invalid"]


def config(path, before, after):
    cfg = Path(path) / "nool.toml"
    text = cfg.read_text()
    if before not in text:
        raise SystemExit(f"sandbox nool.toml lacks {before!r}")
    cfg.write_text(text.replace(before, after, 1))


def append(path, rel, text):
    target = Path(path) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as f:
        f.write(text)


def fake_checkpoint(path, checkpoint_id, files):
    """Create a local Entire-style checkpoint ref recording `files`."""
    meta = json.dumps({"checkpoint_id": checkpoint_id, "files_touched": files,
                       "agent": "policy-probe"})
    blob = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=path, input=meta,
                          capture_output=True, text=True, check=True).stdout.strip()
    tree = subprocess.run(["git", "mktree"], cwd=path, input=f"100644 blob {blob}\tmetadata.json\n",
                          capture_output=True, text=True, check=True).stdout.strip()
    commit = subprocess.run(["git", *GIT_ID, "commit-tree", tree, "-m", "probe checkpoint"],
                            cwd=path, capture_output=True, text=True, check=True).stdout.strip()
    ref = f"refs/entire/checkpoints/{checkpoint_id[-2:]}/{checkpoint_id}"
    subprocess.run(["git", "update-ref", ref, commit], cwd=path, check=True)
    return ref


def main():
    steps, outcomes = [], []
    with tempfile.TemporaryDirectory(prefix="nool-policy-types-") as root:
        rec = Recorder(root)
        path = make_sandbox(root, "repo")
        nool_init(rec, steps, path)
        run = lambda name, *cmd, **kw: rec.run(steps, name, list(cmd), path, **kw)

        _, key, _ = run("identity key", "nool", "admin", "team", "key")
        key = key.strip().splitlines()[-1].strip()
        run("grant editor", "nool", "admin", "contract", "grant", "--role", "editor")
        config(path, "checker_keys = []", f'checker_keys = ["{key}"]')
        config(path, "[rules]\nforbidden_paths = []",
               '[rules]\nforbidden_paths = [".entire/metadata", ".entire/logs", ".env"]')
        config(path, 'relational_controls = "warn"', 'relational_controls = "block"')
        config(path, "[invariants]\ndisabled = false\nrules = []",
               '[invariants]\ndisabled = false\nrules = ["require_entire_provenance"]\n\n'
               "[invariants.rule_definitions.require_entire_provenance]\n"
               'description = "AI-tagged changes must link an Entire checkpoint"\n'
               "when_pattern = \"has_metadata('is_ai_agent')\"\n"
               "then_requirement = \"has_link('entire_checkpoint')\"\n"
               'severity = "error"')
        rc, out, _ = run("land policy config", "nool", "propose", "--path", "nool.toml", "--kind",
                         "config", "--intent", "chore: configure policy probe",
                         "--justification", "policy probe sandbox", "--solidify")
        if rc:
            raise SystemExit(out)
        os.makedirs(Path(path) / "policies", exist_ok=True)
        for name in ("secrets.yaml", "provenance.yaml"):
            shutil.copy(REPO / "policies" / name, Path(path) / "policies" / name)
        rc, out, _ = run("land DSL policies", "nool", "admin", "plugin", "land")
        if rc:
            raise SystemExit(out)
        shutil.copy(REPO / "scripts" / "attest_entire_checkpoint.py", Path(root) / "attest.py")

        def case(name, policy, expect, rc, out, ok, known_gap=False):
            outcomes.append({"case": name, "policy": policy, "expected": expect,
                             "rc": rc, "expectation_met": bool(ok), "known_gap": known_gap})

        def propose(name, rel, text, *extra):
            append(path, rel, text)
            rc, out, _ = run(name, "nool", "propose", "--path", rel, "--intent",
                             f"test: {name}", *extra, "--solidify")
            if rc:
                run("clear candidates", "nool", "candidate", "clear")
                if (Path(path) / rel).exists():
                    subprocess.run(["git", "checkout", "-q", "--", rel], cwd=path)
            return rc, out

        # Built strings so this file never carries a literal credential.
        aws = "AKIA" + "Q" * 16
        rc, out = propose("known-format secret", "src/auth.py", f"\nAWS_KEY = '{aws}'\n")
        case("known-format secret", "DSL SEC-1 (blocking)", "refused", rc, out,
             rc != 0 and "SEC-1" in out)

        alphabet = string.ascii_letters + string.digits
        token = "".join(secrets.choice(alphabet) for _ in range(48))
        rc, out = propose("high-entropy token", "src/auth.py", f"\nTOKEN_HINT = '{token}'\n")
        head_knot = subprocess.run(
            ["git", "log", "-1", "--format=%(trailers:key=Nool-Knot-ID,valueonly)"], cwd=path,
            capture_output=True, text=True).stdout.strip()
        _, receipt, _ = run("gate receipt for high-entropy change", "nool", "evidence", "knot",
                            head_knot or "missing")
        sec2 = [line for line in receipt.splitlines() if "SEC-2" in line]
        case("high-entropy token", "DSL SEC-2 (warning)", "lands; receipt records a warning",
             rc, out, rc == 0 and any("warn" in line.lower() for line in sec2))

        rc, out = propose("forbidden path", ".entire/metadata/probe.json", "{}\n")
        case("forbidden path", "[rules] forbidden_paths", "refused", rc, out, rc != 0)

        rc, out = propose("AI-tagged change without link", "src/auth.py", "\n# ai change\n",
                          "--tag", "is_ai_agent")
        case("AI-tagged change without link", "[invariants] require_entire_provenance",
             "refused at propose", rc, out, rc != 0, known_gap=True)
        rc, out, _ = run("verify invariants", "nool", "verify", "--all")
        case("invariant audit after AI-tagged change", "[invariants] require_entire_provenance",
             "nool verify reports the violation", rc, out,
             rc != 0 and "require_entire_provenance" in out, known_gap=True)

        remote = Path(root) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        rc, out, _ = run("push without checkpoint attestation", "nool", "push", str(remote))
        case("push without checkpoint attestation", "DSL ENTIRE-1 (evidence)",
             "held (pending evidence)", rc, out, rc != 0 and "ENTIRE-1" in out)

        rc, out, _ = run("checker: no checkpoint", sys.executable, str(Path(root) / "attest.py"),
                         "--repo", path)
        case("checker without a checkpoint", "entire-checkpoint checker", "fail verdict",
             rc, out, rc != 0 and '"verdict": "fail"' in out)
        rc, out, _ = run("push after failed attestation", "nool", "push", str(remote))
        case("push after failed attestation", "DSL ENTIRE-1 (evidence)", "refused", rc, out,
             rc != 0)

        fake_checkpoint(path, CHECKPOINT_ID, ["src/auth.py", "tests/test_auth.py"])
        log = subprocess.run(["git", "log", "--format=%H", "--", "src", "tests"], cwd=path,
                             capture_output=True, text=True, check=True).stdout.split()
        attested = True
        for sha in log:
            rc, out, _ = run(f"checker: link {sha[:8]}", sys.executable,
                             str(Path(root) / "attest.py"), "--repo", path, "--commit", sha,
                             "--checkpoint", CHECKPOINT_ID)
            attested = attested and rc == 0
        case("checker with an overlapping checkpoint", "entire-checkpoint checker",
             "pass verdict", 0 if attested else 1, "", attested)
        rc, out, _ = run("push after checkpoint attestation", "nool", "push", str(remote))
        case("push after checkpoint attestation", "DSL ENTIRE-1 (evidence)", "pushes", rc, out,
             rc == 0)

        run("nool version", "nool", "--version")
    result = {"nool_version": next((s["output"].strip() for s in steps
                                    if s["name"] == "nool version"), None),
              "all_expectations_met": all(o["expectation_met"] for o in outcomes
                                          if not o["known_gap"]),
              "known_gaps": [o["case"] for o in outcomes
                             if o["known_gap"] and not o["expectation_met"]],
              "outcomes": outcomes, "steps": steps}
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, indent=2))
    return 0 if result["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
