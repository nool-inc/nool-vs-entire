"""Exercise authority and proof-obligation rejection against isolated repos."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from benchmark.run_benchmark import Recorder, make_sandbox, nool_init


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nool-governance-test-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(make_sandbox(self.temp.name, "repo"))
        steps = []
        nool_init(Recorder(self.temp.name), steps, str(self.repo))
        for step in steps:
            self.assertEqual(step["rc"], 0, step)

    def run_nool(self, *args, env=None, success=True):
        result = subprocess.run(["nool", *args], cwd=self.repo, env=env,
                                capture_output=True, text=True, timeout=180)
        output = result.stdout + result.stderr
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return result, output

    def config(self, before, after):
        path = self.repo / "nool.toml"
        text = path.read_text()
        self.assertIn(before, text)
        path.write_text(text.replace(before, after, 1))

    def test_ungranted_identity_cannot_land_code(self):
        _, key = self.run_nool("admin", "team", "key")
        key = key.strip()
        self.run_nool("admin", "team", "add", "--id", key, "--role", "admin")
        self.run_nool("admin", "contract", "grant", "--role", "editor")
        self.config("[governance]", f'[governance]\nissuer_keys = ["{key}"]')
        self.run_nool("propose", "--path", "nool.toml", "--kind", "config",
                      "--intent", "declare sandbox authority", "--justification", "test", "--solidify")
        with (self.repo / "src/auth.py").open("a") as f:
            f.write("\n# unauthorized sandbox edit\n")
        guest = os.environ.copy()
        guest["NOOL_IDENTITY_KEY"] = os.urandom(32).hex()
        result, output = self.run_nool("propose", "--path", "src/auth.py", "--intent", "guest edit",
                                       "--solidify", env=guest, success=False)
        self.assertEqual(result.returncode, 2, output)
        self.assertTrue(any(word in output.lower() for word in ("authoriz", "authority", "grant", "permission")), output)

    def test_missing_attestation_blocks_push_until_trusted_verdict(self):
        remote = Path(self.temp.name) / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.run_nool("push", str(remote))
        _, key = self.run_nool("admin", "team", "key")
        self.config("checker_keys = []", f'checker_keys = ["{key.strip()}"]')
        self.config('enforce = "warn"', 'enforce = "block"')
        self.config("[attestation.obligations]", '[attestation.obligations]\n"src/**" = ["sandbox-probe"]')
        self.run_nool("propose", "--path", "nool.toml", "--kind", "config", "--intent",
                      "require sandbox evidence", "--justification", "test", "--solidify")
        with (self.repo / "src/auth.py").open("a") as f:
            f.write("\n# proof obligation probe\n")
        self.run_nool("propose", "--path", "src/auth.py", "--intent", "sandbox change", "--solidify")
        _, output = self.run_nool("push", str(remote), success=False)
        self.assertIn("sandbox-probe", output)
        # This synthetic assertion exists only in the throwaway test repository.
        self.run_nool("attest", "record", "--from-head", "--checker", "sandbox-test",
                      "--assertion", "sandbox-probe", "--verdict", "pass", "--scope", "full",
                      "--environment", "local", "--detail", "Synthetic obligation wiring test")
        self.run_nool("push", str(remote))


if __name__ == "__main__":
    unittest.main()
