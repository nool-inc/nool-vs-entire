#!/usr/bin/env python3
"""Check that a landed commit links an Entire checkpoint, then attest the result.

Nool exports its commits through libgit2, so Entire's git hooks never add an
`Entire-Checkpoint:` trailer to them. This checker therefore accepts the
checkpoint from two sources: the commit's own trailer (for example after
`entire session attach --commit <sha>`), or `--checkpoint <id>` given by the
operator. Either way the link must be backed by evidence in this clone:

  * the ID has Entire's format (26-character ULID for the `git-refs` backend,
    12 hex characters for the legacy `git-branch` backend);
  * a checkpoint ref `refs/entire/checkpoints/<shard>/<id>` exists locally;
  * the checkpoint's recorded `files_touched` overlaps the commit's changes.

The verdict is recorded as a signed Nool attestation (assertion
`entire-checkpoint`), which the `ENTIRE-1` rule in `policies/provenance.yaml`
requires before `nool push` publishes source, test or benchmark changes.

`--baseline-before <rev>` is the audited exemption for history that predates
the rule: it records `provenance-baseline` (pass) only for a commit that is an
ancestor of `<rev>` (the commit that adopted ENTIRE-1) and links no checkpoint.
It refuses any later commit, so new work always needs a real checkpoint.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

ASSERTION = "entire-checkpoint"
BASELINE_ASSERTION = "provenance-baseline"
CHECKER = "entire-checkpoint-check"
ULID = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
BRANCH_ID = re.compile(r"^[0-9a-f]{12}$")
IGNORED_PREFIXES = (".nool/",)


def git(repo, *args, check=True):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result


def valid_id(checkpoint_id):
    return bool(ULID.match(checkpoint_id) or BRANCH_ID.match(checkpoint_id))


def trailer_ids(repo, commit):
    out = git(repo, "log", "-1", "--format=%(trailers:key=Entire-Checkpoint,valueonly)",
              commit).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def knot_id(repo, commit):
    out = git(repo, "log", "-1", "--format=%(trailers:key=Nool-Knot-ID,valueonly)",
              commit).stdout.strip()
    return out.splitlines()[0].strip() if out else None


def changed_files(repo, commit):
    out = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root",
              commit).stdout
    return sorted(p for p in out.splitlines()
                  if p and not p.startswith(IGNORED_PREFIXES))


def checkpoint_ref(repo, checkpoint_id):
    out = git(repo, "for-each-ref", "--format=%(refname)",
              f"refs/entire/checkpoints/*/{checkpoint_id}").stdout.split()
    return out[0] if out else None


def files_touched(repo, ref):
    """Union of `files_touched` over the checkpoint's metadata files."""
    names = git(repo, "ls-tree", "-r", "--name-only", ref).stdout.split()
    touched = set()
    for name in names:
        if name == "metadata.json" or name.endswith("/metadata.json"):
            blob = git(repo, "show", f"{ref}:{name}", check=False)
            if blob.returncode:
                continue
            try:
                touched.update(json.loads(blob.stdout).get("files_touched") or [])
            except json.JSONDecodeError:
                continue
    return sorted(touched)


def evaluate(repo, commit, explicit_ids=()):
    """Return the evidence dict; `verdict` is `pass` or `fail`."""
    sha = git(repo, "rev-parse", commit).stdout.strip()
    changed = changed_files(repo, sha)
    sources = [(i, "trailer") for i in trailer_ids(repo, sha)]
    sources += [(i, "operator") for i in explicit_ids if i not in {s for s, _ in sources}]
    checked = []
    for checkpoint_id, source in sources:
        entry = {"id": checkpoint_id, "source": source, "format_ok": valid_id(checkpoint_id)}
        ref = checkpoint_ref(repo, checkpoint_id) if entry["format_ok"] else None
        entry["ref"] = ref
        touched = files_touched(repo, ref) if ref else []
        entry["files_touched"] = touched
        entry["overlap"] = sorted(set(touched) & set(changed))
        entry["ok"] = bool(entry["format_ok"] and ref and entry["overlap"])
        checked.append(entry)
    linked = [c for c in checked if c["ok"]]
    if not sources:
        reason = "commit carries no Entire-Checkpoint trailer and no --checkpoint was given"
    elif linked:
        reason = f"linked to checkpoint {linked[0]['id']} ({linked[0]['source']})"
    else:
        reason = "no named checkpoint exists locally with files overlapping this commit"
    return {"commit": sha, "knot": knot_id(repo, sha), "changed_files": changed,
            "checkpoints": checked, "verdict": "pass" if linked else "fail",
            "reason": reason}


def baseline(repo, commit, adopted):
    """Evidence for the pre-ENTIRE-1 exemption; `verdict` is `pass` or `fail`."""
    sha = git(repo, "rev-parse", commit).stdout.strip()
    adopted_sha = git(repo, "rev-parse", adopted).stdout.strip()
    before = sha != adopted_sha and git(
        repo, "merge-base", "--is-ancestor", sha, adopted_sha, check=False).returncode == 0
    linked = trailer_ids(repo, sha)
    if not before:
        verdict, reason = "fail", f"commit is not an ancestor of the ENTIRE-1 adoption commit {adopted_sha[:12]}"
    elif linked:
        verdict, reason = "fail", "commit names an Entire checkpoint; attest it without --baseline-before"
    else:
        verdict, reason = "pass", (f"landed before ENTIRE-1 was adopted at {adopted_sha[:12]}; "
                                   "no Entire checkpoint exists for it")
    return {"commit": sha, "knot": knot_id(repo, sha), "changed_files": changed_files(repo, sha),
            "adopted_at": adopted_sha, "assertion": BASELINE_ASSERTION, "verdict": verdict,
            "reason": reason}


def record(repo, evidence, environment):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(evidence, f, indent=2)
        evidence_path = f.name
    try:
        cmd = ["nool", "attest", "record", "--checker", CHECKER,
               "--assertion", evidence.get("assertion", ASSERTION),
               "--verdict", evidence["verdict"], "--scope", "full",
               "--environment", environment, "--commit", evidence["commit"],
               "--detail", evidence["reason"], "--evidence", evidence_path]
        if evidence["knot"]:
            cmd += ["--target", evidence["knot"]]
        else:
            cmd += ["--from-head"]
        return subprocess.run(cmd, cwd=repo).returncode
    finally:
        os.unlink(evidence_path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--checkpoint", action="append", default=[],
                        help="Entire checkpoint ID to link (repeatable)")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--environment", default="local")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the evidence without recording an attestation")
    parser.add_argument("--baseline-before", metavar="REV",
                        help="record the pre-ENTIRE-1 exemption for a commit that predates REV")
    args = parser.parse_args(argv)
    if args.baseline_before:
        evidence = baseline(args.repo, args.commit, args.baseline_before)
    else:
        evidence = evaluate(args.repo, args.commit, args.checkpoint)
    print(json.dumps(evidence, indent=2))
    if not args.dry_run:
        rc = record(args.repo, evidence, args.environment)
        if rc:
            return rc
    return 0 if evidence["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
