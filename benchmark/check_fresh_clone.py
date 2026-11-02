#!/usr/bin/env python3
"""Verify committed HEAD in an independent clone, with newly generated evidence."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[1]


def main():
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    with tempfile.TemporaryDirectory(prefix="nool-study-clone-") as root:
        clone = Path(root) / "repo"
        subprocess.run(["git", "clone", "--quiet", "--no-local", "--single-branch",
                        str(REPO), str(clone)], check=True)
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=clone, text=True).strip()
        if actual != revision:
            raise RuntimeError("source HEAD changed during cloning; retry against a stable revision")
        # The runbook creates its own evidence, so original-checkout results cannot
        # disguise missing state. Only committed files are tested in the clone.
        result = subprocess.run(["./verify_benchmark.sh"], cwd=clone, capture_output=True,
                                text=True, timeout=900)
    output = result.stdout + result.stderr
    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_commit": revision,
        "exit_code": result.returncode,
        "passed": result.returncode == 0,
        "scope": "committed HEAD; independent local clone; fresh benchmark evidence",
        "output": output,
    }
    dest = REPO / "benchmark/results/fresh-clone.json"
    dest.write_text(json.dumps(report, indent=2) + "\n")
    print(output[-6000:])
    print(f"Fresh-clone verification {'passed' if report['passed'] else 'failed'} for {revision}")
    print(f"Evidence: {dest.relative_to(REPO)}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
