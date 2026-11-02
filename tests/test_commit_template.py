"""Behavioral checks of the repository's effective Nool commit policy.

Requires the same licensed Enterprise CLI as the benchmark. Message-file
checks use temporary files; no proposals, commits, or hooks are changed.
"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


def command(*args):
    return subprocess.run(
        ["nool", "commit-template", *args], cwd=REPO,
        capture_output=True, text=True, timeout=30,
    )


class CommitTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = command("check", "--json")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.policy = json.loads(result.stdout)
        result = command("render", "--dry-run", "--type", "docs",
                         "--subject", "verify commit policy", "--json")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.message = json.loads(result.stdout)["message"]

    def validate_message(self, message, *, valid, diagnostic=""):
        with tempfile.TemporaryDirectory(prefix="commit-policy-test-") as temp:
            path = Path(temp) / "message.txt"
            path.write_text(message)
            result = command("validate", "--message-file", str(path), "--json")
        output = result.stdout + result.stderr
        if valid:
            self.assertEqual(result.returncode, 0, output)
            self.assertEqual(json.loads(result.stdout)["status"], "valid")
        else:
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn(diagnostic, output)

    def with_subject(self, subject):
        return subject + "\n" + self.message.split("\n", 1)[1]

    def test_repository_policy_blocks_invalid_messages(self):
        self.assertEqual(self.policy["status"], "valid")
        self.assertEqual(self.policy["validation"], "Block")
        self.assertIn(str(REPO / "nool.toml"), self.policy["template_source"])

    def test_rendered_template_is_accepted(self):
        self.assertEqual(self.message.splitlines()[0], "docs: verify commit policy")
        self.validate_message(self.message, valid=True)

    def test_documented_types_are_accepted(self):
        for kind in ("feat", "fix", "docs", "test", "refactor", "perf", "build", "ci", "chore", "revert"):
            with self.subTest(kind=kind):
                self.validate_message(self.with_subject(f"{kind}: verify policy"), valid=True)

    def test_unknown_and_missing_types_are_rejected(self):
        for subject in ("unknown: verify policy", "verify policy"):
            with self.subTest(subject=subject):
                self.validate_message(self.with_subject(subject), valid=False,
                                      diagnostic="not allowed")

    def test_subject_length_boundary(self):
        self.validate_message(self.with_subject("docs: " + "x" * 66), valid=True)
        self.validate_message(self.with_subject("docs: " + "x" * 67), valid=False,
                              diagnostic="maximum is 72")

    def test_required_nool_trailers_cannot_be_removed(self):
        for key in ("Nool-Knot-ID", "Nool-Intent", "Nool-Policy-Version",
                    "Nool-Policy-Hash", "Nool-Template-Hash"):
            with self.subTest(trailer=key):
                message = "".join(line for line in self.message.splitlines(True)
                                  if not line.startswith(key + ":"))
                self.validate_message(message, valid=False, diagnostic=key)

    def test_duplicate_identity_is_rejected(self):
        identity = next(line for line in self.message.splitlines(True)
                        if line.startswith("Nool-Knot-ID:"))
        self.validate_message(self.message + identity, valid=False,
                              diagnostic="more than once")

    def test_oversized_message_is_rejected(self):
        self.validate_message(self.message + "x" * 65536, valid=False,
                              diagnostic="maximum is 65536")

    def test_latest_commit_has_valid_signed_knot_identity(self):
        result = command("validate", "--commit", "HEAD", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["status"], "valid")
        self.assertEqual(len(data["results"]), 1)
        self.assertTrue(data["results"][0]["embedded_knot"])


if __name__ == "__main__":
    unittest.main()
