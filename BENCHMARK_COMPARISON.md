# Nool vs Entire vs Plain Git: Benchmark Study

**Run:** 2026-11-02T05:03:07Z · 19.8 s total · nool 7.23.0 · Entire CLI 0.12.2 · git version 2.50.1 (Apple Git-155) · Python 3.11.2 · Darwin 25.6.0 arm64

**Reproduce:** `./verify_benchmark.sh` (or `python3 benchmark/run_benchmark.py && python3 benchmark/render_report.py`). Raw evidence — every command, exit code, timing and output excerpt — is in `benchmark/results/latest.json`.

> This file is generated. Each scenario runs in a fresh throwaway sandbox built from the baseline commit `53866f8`; the live repository is only read. Timings are single-run wall clock on one machine with Nool's local coordination backend — treat them as orders of magnitude, not a race.

## Headline results

| Question | Plain Git | Git + Entire | Nool |
|---|---|---|---|
| Two agents edit `src/auth.py` — when is the overlap first visible? | at `git merge` | at `git merge` (Entire installs no merge hook) | **before editing** — `discover conflicts` names `agent-oauth` (15 ms) |
| Can the second agent take the same file anyway? | yes | yes | **no** — exclusive announce refused; propose refused |
| Different methods added at the same spot | conflict, 1 marker block, manual fix | conflict, 1 marker block, manual fix | **merged automatically** — 0 markers, tests pass |
| Same method rewritten by both | conflict, manual fix | conflict, manual fix | conflict, manual fix (no silent union) |
| Why does this line exist? | commit author only | line → checkpoint → **original agent prompt** | knot → causal chain → intent + gate attestations |
| Full agent session/transcript captured | no | **yes** — 5 sessions listed | no — agent-supplied intent strings, not transcripts |
| Policy gate before code lands | no | no | yes — Aram denied an agent edit with no editor contract |
| Enforce "AI change must carry an Entire checkpoint" | — | — | **not enforced** as configured (see below) |
| Ref namespaces coexist | — | `refs/entire/*` (5) | `refs/nool/*` (9) · overlap: 0 |

## Scenario 1 — Concurrent OAuth2 + SAML edits, merged after the fact

Two branches cut from the same baseline each add a new method immediately before `get_user_role` (*disjoint*), or both rewrite the body of `authenticate_user` (*same-symbol*).

| Tool / variant | Merge exit | Markers | Result parses | Methods after merge | Tests pass w/o manual edit | Merge time |
|---|---|---|---|---|---|---|
| Plain Git · disjoint | 1 | 1 | no | — | no | 26 ms |
| Plain Git · same-symbol | 1 | 1 | no | — | no | 25 ms |
| Git + Entire · disjoint | 1 | 1 | no | — | no | 24 ms |
| Nool · disjoint | [0, 0] | 0 | yes | authenticate_user, authenticate_oauth, authenticate_saml | yes | 181 ms |
| Nool · same-symbol | [0, 1] | 1 | no | — | no | 151 ms |

What the evidence shows:

- **Disjoint edits:** `nool merge` hit the same textual conflict git does (`CONFLICT (content)` seen: yes), then its MergeReconcile step unioned the two structurally disjoint hunks (union applied: yes). Result: both methods present, file parses, unit tests pass, no human step.
- **Same-symbol edits:** Nool did *not* guess — it stopped with a conflict for a human, like git. However, its semantic pre-check printed *"no same-symbol collisions"* (observed) even though both branches rewrote `authenticate_user`; the textual layer caught it. The outcome is safe, but the semantic signal was a false negative in this run.
- **Entire** installed `commit-msg, post-commit, post-rewrite, pre-push, prepare-commit-msg` and no merge hook (merge hook present: no), so merge behaviour is plain git's. Entire is an attribution layer, not a coordination or merge layer.

## Scenario 2 — Proactive coordination (Nool leases)

| Step | Outcome | Time |
|---|---|---|
| `agent-oauth` announces an exclusive lease on `file:src/auth.py` | granted | 17 ms |
| `agent-saml` runs `nool discover conflicts` | conflict reported (exit 3), holder: agent-oauth | 15 ms |
| `agent-saml` announces an exclusive lease on the same file | refused | — |
| `agent-saml` ignores that and runs `nool propose --as-agent agent-saml` | refused (Coordination conflict) | 45 ms |
| `agent-oauth` releases; `agent-saml` re-checks | clear | — |

**Identity caveat (measured):** when two agents announce *without* distinct `--agent-id`s they share the session identity, so the second exclusive announce is granted (observed) and supersedes the first — 1 lease remains active. This explains an earlier headless opencode run in this repo that reported "both agents granted exclusive leases". `nool propose --help` says the same for proposals: without `--as-agent` a proposal inherits whichever lease covers its scope. The protection is real but only as good as each agent's identity wiring.

## Scenario 3 — Aram policy gate and the "Entire provenance" rule

Setup in a sandbox: the `require_entire_provenance` invariant from this repo's `nool.toml` (`when has_metadata('is_ai_agent') then has_link('entire_checkpoint')`) and the `policies/entire_policy_test.wasm` module, both landed (invariant landed: yes, policy set landed: yes), editor contract granted.

| Attempt | Landed? |
|---|---|
| Agent edit before any editor contract | no — `POLICY_DENY` |
| `--tag is_ai_agent`, **no** Entire checkpoint link | **yes** |
| Untagged control | yes |
| `nool verify --all` afterwards | 0 violations |

Findings:

- The Aram gate machinery is real: it refused an agent edit until an editor contract existed.
- The Entire-provenance rule is **not enforced** in this configuration: an AI-tagged change with no Entire link landed and `verify` reported nothing. Either `--tag` does not populate what `has_metadata()` reads, or invariants are not evaluated at the seal; this study did not determine which.
- The WASM module contains no reference to Entire, checkpoints or `is_ai_agent` (match: no) — it is a scaffold, not a provenance check. `nool admin plugin list` flags it as built against an older knot model (warning: yes).
- In the live repo that stale module **fails closed** on newer knot kinds: solidifying the pending task-creation knot is denied with *"policy `entire_policy_test` could not decode this knot"*. Live repo state: pending candidates: 1.
- Earlier versions of this report said provenance was "enforced via ARAM WASM gate". That claim is withdrawn.

## Scenario 4 — Session & workflow surface

Same-named commands mean different things. `nool checkpoint` seals a **state label/release** in the DAG; `entire checkpoint` is a **captured agent session** (prompt, transcript) tied to a commit.

| Need | Nool (measured in sandbox) | Entire (measured on live repo) |
|---|---|---|
| Context before editing | `nool context` — symbol-name query: entities + blast radius (17 ms); natural-language query on a fresh repo: no entity match; live repo NL query: returned prior findings | `entire search` — needs a GitHub/Entire remote (not runnable locally) |
| Mark a point in history | `nool checkpoint <label>` → Release knot: ✅ yes (116 ms) | automatic per agent turn: `entire checkpoint list` ✅ yes |
| Explain a past change | `nool why <knot>` causal chain ✅ yes | `entire checkpoint explain` shows the **original prompt**: ✅ yes |
| Hand work to another agent | `nool thread handoff --summary --decision --next` → Handoff knot: ✅ yes (72 ms) | `entire session resume` / `adopt` (resume a session; no structured decisions/next-steps record) |
| PR review context | `nool pr summary --base` → markdown with blast radius per knot: ✅ yes (18 ms) | `entire dispatch` — needs a GitHub/Entire remote |
| Merge a PR | `nool pr merge <branch> --into main` via a local bare remote: ✅ yes (454 ms) | plain git / forge |
| Activity summary | `nool insights`, `nool usage` | `entire recap` — needs login |

Entire commands that could not run in this local-only setup (recorded, not counted as failures of the tool):

- `entire recap` → exit 1: Not logged in. Run 'entire login' to authenticate.
- `entire dispatch` → exit 1: dispatch needs an origin remote on GitHub or Entire: remote not found (or pass --repos gh/<owner>/<repo> or et/<project>/<repo> to name the repo)
- `entire search` → exit 1: could not determine current repository for search (use --repo or --all-repos): get remote URL for "origin": remote "origin" not found

## What each tool is, judged by this evidence

- **Plain Git** — the transport both tools build on. Finds overlap only at merge; resolution is manual.
- **Entire** — a session-capture and attribution layer on top of git hooks. Its distinctive, verified value is *memory*: every agent session and the exact prompt behind a line of code. It does not change how conflicts arise or are resolved. Several team features (search, dispatch, recap) need its hosted service.
- **Nool** — a coordination and governance layer that also uses git as transport (`refs/nool/*`, no clash with `refs/entire/*`). Its distinctive, verified value is *prevention and convergence*: leases that refuse overlapping agents before work starts, automatic union of structurally disjoint edits, a policy gate, and structured handoff/PR artefacts. Weak spots found here: the provenance rule as configured is not enforced, a stale policy module fails closed on newer knots, the semantic same-symbol check missed a real collision, and `nool context` matches symbol names rather than natural-language intent on a small fresh repo.
- **Together** — complementary rather than competing: Entire answers *what was the agent asked and what did it say*; Nool answers *who may touch what now, and does this change meet policy*. The integration point this repo attempted (Nool gating on Entire checkpoint links) is the right idea but is not working yet.

## Limitations

- Synthetic two-branch scenario on a 15-line file; real codebases will exercise the semantic merge harder.
- Agents are simulated with CLI identities (`--agent-id`/`--as-agent`), not live LLM agents; Entire attribution evidence comes from the earlier Antigravity sessions recorded in this repo.
- Single run, single machine, Nool local coordination backend; no network, no hosted Entire features.
- `tests/test_benchmark.py` also contains CLI smoke tests (many are `--help` checks); they show commands exist, not that they work, and are not counted as evidence above.
