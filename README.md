# Nool vs Entire vs Plain Git

A reproducible, local benchmark of agent coordination, merge behavior,
session attribution, and policy gates. The study compares plain Git,
Git with Entire, and Nool using concurrent edits to a small Python
authentication service.

Start with the [benchmark report](BENCHMARK_COMPARISON.md) for measured
results and caveats, or open [comparison.html](comparison.html) locally
for the visual comparison. Every recorded command, exit code, timing,
and output excerpt is in [latest.json](benchmark/results/latest.json).

## Findings from the recorded run

| Capability | Plain Git | Git + Entire | Nool |
|---|---|---|---|
| Detect overlapping agents before editing | No | No | Yes, with distinct agent identities and leases |
| Merge the tested disjoint method additions | Manual conflict resolution | Manual conflict resolution | Automatic merge; tests pass |
| Handle conflicting rewrites of the same method | Stops with conflict | Stops with conflict | Stops with conflict |
| Attribute code to recorded agent prompts | No | Yes | Records intent and causal history rather than transcripts |
| Gate changes before landing | No | No | Yes, via Aram |
| Require an Entire checkpoint for AI-tagged edits | — | — | Not enforced by the benchmark configuration |

These results support complementary roles: Entire captures agent sessions,
while Nool coordinates work and governs changes. They do not establish a
general performance ranking.

## Run the benchmark

The recorded environment used Nool **7.23.0** with Enterprise features,
Entire CLI **0.12.2**, Git **2.50.1**, and Python **3.11.2** on macOS arm64.
Have `nool`, `entire`, `git`, and `python3` available on your `PATH`, with
a Git identity configured for commits in the temporary repositories.
Nool scenarios that require licensed features need the corresponding edition
and license. The Python code uses the standard library.

Clone the complete history: the harness reads baseline commit `53866f8`.

```sh
git clone https://github.com/nool-inc/nool-vs-entire.git
cd nool-vs-entire
./verify_benchmark.sh
```

The runbook executes scenarios in temporary repositories, regenerates the
Markdown report and measured sections of the HTML comparison, and runs the
test suite. It reads the live checkout for session and repository evidence;
the sandboxed scenarios do not edit its application code. Generated reports
and JSON evidence are written into this checkout.

To run the pieces separately:

```sh
python3 benchmark/run_benchmark.py
python3 benchmark/render_report.py
BENCH_REUSE_RESULTS=1 python3 -m unittest tests.test_auth tests.test_benchmark tests.test_commit_template
```

The last verified run completed **90 tests with two expected failures**:
the unenforced provenance rule and a semantic same-symbol collision check
that missed a conflict later caught by the textual merge layer.

## Repository guide

| Path | Purpose |
|---|---|
| [BENCHMARK_COMPARISON.md](BENCHMARK_COMPARISON.md) | Generated findings, scenario details, and limitations |
| [comparison.html](comparison.html) | Visual comparison with generated measurement blocks |
| [benchmark/](benchmark/) | Scenario runner, report renderer, and raw results |
| [verify_benchmark.sh](verify_benchmark.sh) | End-to-end verification runbook |
| [tests/](tests/) | Authentication tests, CLI smoke checks, and evidence assertions |
| [src/auth.py](src/auth.py) | Small authentication fixture used by the study |
| [policies/](policies/) | Original policy scaffold measured by the benchmark |
| [policies-src/entire_provenance/](policies-src/entire_provenance/) | Development provenance policy and compatibility evidence |

## Commit-message policy

The repository's `[commit]` section in [nool.toml](nool.toml) uses Nool's
Enterprise commit-template enforcement. Nool renders subjects as
`<type>: <subject>`, limits them to 72 characters, and requires its identity
and policy trailers. Invalid messages block solidification.

Allowed types are `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`,
`ci`, `chore`, and `revert`. Supply a typed intent when landing work:

```sh
nool propose --path README.md --intent "docs: clarify benchmark setup" --solidify
nool commit-template check
nool commit-template render --dry-run --type docs --subject "clarify benchmark setup"
nool commit-template validate --commit HEAD
python3 -m unittest tests.test_commit_template -v
```

An intent without a recognized type is rendered with Nool's default `chore`
type. The full intent remains in the Nool trailers. The rule applies to new
commits; existing history has not been rewritten.

Entire's existing `commit-msg` hook is preserved. Do not force-install Nool's
optional hook over it. Nool enforces this policy on its own commit path;
external Git commits need a separate CI/server check using
`nool commit-template validate --range <base>..<head>` with an Enterprise
installation. No GitHub branch-protection rule is configured by this change.

## Playbooks

For worked examples and measured outcomes, see the
[playbook case studies](docs/PLAYBOOK_CASE_STUDIES.md).

Use the `verified-change` code playbook to start a guided implementation:

```sh
nool code --playbook verified-change "Describe the change to implement"
```

Its plan covers scope, implementation, regression tests, benchmark evidence,
documentation, and commit validation. Its required completion checks run
`./verify_benchmark.sh`, validate the commit policy and current `HEAD`, and
check diff whitespace. These checks require the benchmark's licensed tools.
The benchmark check regenerates reports and evidence in the session checkout.
The playbook does not automatically push changes.

For deterministic commit checks without starting a model session:

```sh
nool playbook plan commit-preflight
nool playbook run commit-preflight
```

This two-step command playbook checks the effective template, then validates
`HEAD`, stopping on the first failure. It does not run tests, land changes,
or validate an uncommitted draft message. Use the full verification runbook
for tests and `commit-template validate --message-file <path>` for drafts.

Two additional command playbooks make investigations repeatable:

```sh
nool playbook run policy-audit
nool playbook run study-review
```

`policy-audit` checks the commit policy, runs structural invariants, and lists
policy compatibility warnings. A successful run does not mean those warnings
are resolved or that Entire provenance is enforced. `study-review` validates
`HEAD` and renders Nool review context since the original benchmark-study
knot `7d6dccc0`. Both inspect state without editing application files.

To verify that committed `HEAD` reproduces in an independent local clone:

```sh
python3 benchmark/check_fresh_clone.py
```

This runs the complete runbook with fresh evidence inside a temporary clone
and writes [fresh-clone.json](benchmark/results/fresh-clone.json). Uncommitted
edits and the original checkout's benchmark results are not used by the clone.
It uses local Git transport; it does not test GitHub permissions or hosted
Entire features. Clone-specific unavailable checks may be reported as skips.

Commit-writing guidance follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
and [Chris Beams' guide](https://cbea.ms/git-commit/): use a specific action
in the subject and explain the reason in a body separated by a blank line.
For example:

```text
fix: reject checkpoint IDs outside the ULID range

The previous check accepted values too large to represent a ULID.
Validate the leading character before accepting a checkpoint reference.
```

The repository uses a 72-character subject cap. Its typed template is a
subset of Conventional Commits; it does not implement every scope or
breaking-change notation in that specification.

## Limits and integration status

The benchmark uses a synthetic two-branch workload on a small file and
simulates agents with CLI identities. Timings are single-run measurements
on one machine with Nool's local coordination backend. Some tests only
check CLI command availability; the report distinguishes those from
behavioral evidence.

Entire's session and prompt findings come from sessions recorded in the
original working repository. A fresh Git clone may not contain its local
session state or custom `refs/entire/*` refs, so attribution evidence can
differ or be unavailable on a new run. Hosted search, dispatch, and recap
were not evaluated in this local setup.

The original provenance policy is a scaffold and does not enforce the
checkpoint requirement. The development replacement builds and passes seven
Rust unit tests, but requires a compatible Nool host and SDK before its
integration can be verified. Its Cargo dependencies currently reference a
local development worktree. See the [policy status and reproduction notes](policies-src/entire_provenance/README.md)
before attempting to build or enable it.

Edit [benchmark/render_report.py](benchmark/render_report.py) when changing
generated report text, then regenerate the reports from the recorded evidence.
