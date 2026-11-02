#!/usr/bin/env python3
"""Probe the development policy in a throwaway repo; never installs it live."""
import json
from pathlib import Path
import tempfile

from run_benchmark import Recorder, make_sandbox, nool_init


def main():
    repo = Path(__file__).resolve().parents[1]
    policy = repo / "policies-src/entire_provenance"
    artifact = policy / "entire_provenance.wasm"
    if not artifact.is_file():
        raise SystemExit("Build first: nool admin plugin build policies-src/entire_provenance")
    steps = []
    with tempfile.TemporaryDirectory(prefix="entire-policy-probe-") as root:
        rec = Recorder(root)
        path = make_sandbox(root, "repo")
        nool_init(rec, steps, path)
        rc, out, _ = rec.run(steps, "grant editor", [
            "nool", "admin", "contract", "grant", "--role", "editor"], path)
        if rc:
            raise SystemExit(out)
        rc, out, _ = rec.run(steps, "install development policy", [
            "nool", "admin", "plugin", "install", str(artifact), "--policy", "--no-land"], path)
        if rc:
            raise SystemExit(out)
        cases = [
            ("missing-link", ["--tag", "is_ai_agent"], False),
            ("malformed-link", ["--tag", "is_ai_agent", "--issue", "entire_checkpoint:bad"], False),
            ("valid-link", ["--tag", "is_ai_agent", "--issue",
                            "entire_checkpoint:01M6CRZR6WVBD2GAEE84042PZA"], True),
            ("untagged", [], True),
        ]
        outcomes = []
        for name, flags, should_land in cases:
            with open(Path(path) / "src/auth.py", "a") as f:
                f.write(f"\n# {name}\n")
            rc, out, _ = rec.run(steps, name, [
                "nool", "propose", "--path", "src/auth.py", "--intent", name,
                *flags, "--solidify"], path)
            incompatible = "matching implementation was not found in the linker" in out
            outcomes.append({"case": name, "rc": rc, "should_land": should_land,
                             "host_incompatible": incompatible,
                             "expectation_met": not incompatible and (
                                 rc == 0 if should_land else
                                 rc != 0 and "must link its Entire session" in out)})
            rec.run(steps, "clear sandbox candidates", ["nool", "candidate", "clear"], path)
    result = {"host_compatible": not any(x["host_incompatible"] for x in outcomes),
              "enforcement_verified": all(x["expectation_met"] for x in outcomes),
              "outcomes": outcomes, "steps": steps}
    (policy / "host-probe.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "steps"}, indent=2))
    return 0 if result["enforcement_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
