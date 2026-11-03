# Nool vs Entire vs Plain Git: Benchmark Study

**Run:** 2026-11-03T03:46:27Z · 25.3 s total · nool 7.24.0 · Entire CLI 0.12.2 · git version 2.50.1 (Apple Git-155) · Python 3.11.2 · Darwin 25.6.0 arm64

**Reproduce:** `./verify_benchmark.sh` (or `python3 benchmark/run_benchmark.py && python3 benchmark/render_report.py`). Raw evidence — every command, exit code, timing and output excerpt — is in `benchmark/results/latest.json`.

> This file is generated. Each scenario runs in a fresh throwaway sandbox built from the baseline commit `53866f8`; the live repository is only read. Timings are single-run wall clock on one machine with Nool's local coordination backend — treat them as orders of magnitude, not a race.

## Headline results

| Question | Plain Git | Git + Entire | Nool |
|---|---|---|---|
| Two agents edit `src/auth.py` — when is the overlap first visible? | at `git merge` | at `git merge` (Entire installs no merge hook) | **before editing** — `discover conflicts` names `agent-oauth` (17 ms) |
| Can the second agent take the same file anyway? | yes | yes | **no** — exclusive announce refused; propose refused |
| Different methods added at the same spot | conflict, 1 marker block, manual fix | conflict, 1 marker block, manual fix | **merged automatically** — 0 markers, tests pass |
| Same method rewritten by both | conflict, manual fix | conflict, manual fix | conflict, manual fix (no silent union) |
| Why does this line exist? | commit author only | line → checkpoint → **original agent prompt** | knot → causal chain → intent + gate attestations |
| Full agent session/transcript captured | no | **yes** — 6 sessions listed | no — agent-supplied intent strings, not transcripts |
| Policy gate before code lands | no | no | yes — Aram denied an agent edit with no editor contract |
| Enforce "AI change must carry an Entire checkpoint" | — | — | original invariant + scaffold: **not enforced**; evidence rule `ENTIRE-1`: push **held until a verified checkpoint is attested** (Scenario 5) |
| Ref namespaces coexist | — | `refs/entire/*` (5) | `refs/nool/*` (11) · overlap: 0 |

## Scenario 1 — Concurrent OAuth2 + SAML edits, merged after the fact

Two branches cut from the same baseline each add a new method immediately before `get_user_role` (*disjoint*), or both rewrite the body of `authenticate_user` (*same-symbol*).

| Tool / variant | Merge exit | Markers | Result parses | Methods after merge | Tests pass w/o manual edit | Merge time |
|---|---|---|---|---|---|---|
| Plain Git · disjoint | 1 | 1 | no | — | no | 30 ms |
| Plain Git · same-symbol | 1 | 1 | no | — | no | 29 ms |
| Git + Entire · disjoint | 1 | 1 | no | — | no | 29 ms |
| Nool · disjoint | [0, 0] | 0 | yes | authenticate_user, authenticate_oauth, authenticate_saml | yes | 197 ms |
| Nool · same-symbol | [0, 1] | 1 | no | — | no | 160 ms |

What the evidence shows:

- **Disjoint edits:** `nool merge` hit the same textual conflict git does (`CONFLICT (content)` seen: yes), then its MergeReconcile step unioned the two structurally disjoint hunks (union applied: yes). Result: both methods present, file parses, unit tests pass, no human step.
- **Same-symbol edits:** Nool did *not* guess — it stopped with a conflict for a human, like git. However, its semantic pre-check printed *"no same-symbol collisions"* (observed) even though both branches rewrote `authenticate_user`; the textual layer caught it. The outcome is safe, but the semantic signal was a false negative in this run.
- **Entire** installed `commit-msg, post-commit, post-rewrite, pre-push, prepare-commit-msg` and no merge hook (merge hook present: no), so merge behaviour is plain git's. Entire is an attribution layer, not a coordination or merge layer.

## Scenario 2 — Proactive coordination (Nool leases)

| Step | Outcome | Time |
|---|---|---|
| `agent-oauth` announces an exclusive lease on `file:src/auth.py` | granted | 20 ms |
| `agent-saml` runs `nool discover conflicts` | conflict reported (exit 3), holder: agent-oauth | 17 ms |
| `agent-saml` announces an exclusive lease on the same file | refused | — |
| `agent-saml` ignores that and runs `nool propose --as-agent agent-saml` | refused (Coordination conflict) | 50 ms |
| `agent-oauth` releases; `agent-saml` re-checks | clear | — |

**Identity caveat (measured):** when two agents announce *without* distinct `--agent-id`s they share the session identity, so the second exclusive announce is granted (observed) and supersedes the first — 1 lease remains active. This explains an earlier headless opencode run in this repo that reported "both agents granted exclusive leases". `nool propose --help` says the same for proposals: without `--as-agent` a proposal inherits whichever lease covers its scope. The protection is real but only as good as each agent's identity wiring.

## Scenario 3 — Aram policy gate and the "Entire provenance" rule

Setup in a sandbox: the `require_entire_provenance` invariant from this repo's `nool.toml` (`when has_metadata('is_ai_agent') then has_link('entire_checkpoint')`) and the preserved `benchmark/fixtures/legacy-policy/entire_policy_test.wasm` module, both landed (invariant landed: yes, policy set landed: yes), editor contract granted.

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
- The legacy module previously refused the live repository's newer Task payload. It is now preserved as an isolated benchmark fixture; current policy integration is reported separately in `policies-src/entire_provenance/README.md`. Current live policy outdated warning: no; no pending candidates..
- Earlier versions of this report said provenance was "enforced via ARAM WASM gate". That claim is withdrawn.

## Scenario 4 — Session & workflow surface

Same-named commands mean different things. `nool checkpoint` seals a **state label/release** in the DAG; `entire checkpoint` is a **captured agent session** (prompt, transcript) tied to a commit.

| Need | Nool (measured in sandbox) | Entire (measured on live repo) |
|---|---|---|
| Context before editing | `nool context` — symbol-name query: entities + blast radius (20 ms); natural-language query on a fresh repo: no entity match; live repo NL query: returned prior findings | `entire search` — needs a GitHub/Entire remote (ok) |
| Mark a point in history | `nool checkpoint <label>` → Release knot: ✅ yes (126 ms) | automatic per agent turn: `entire checkpoint list` ✅ yes |
| Explain a past change | `nool why <knot>` causal chain ✅ yes | `entire checkpoint explain` shows the **original prompt**: ✅ yes |
| Hand work to another agent | `nool thread handoff --summary --decision --next` → Handoff knot: ✅ yes (76 ms) | `entire session resume` / `adopt` (resume a session; no structured decisions/next-steps record) |
| PR review context | `nool pr summary --base` → markdown with blast radius per knot: ✅ yes (20 ms) | `entire dispatch` — needs a GitHub/Entire remote |
| Merge a PR | `nool pr merge <branch> --into main` via a local bare remote: ✅ yes (568 ms) | plain git / forge |
| Activity summary | `nool insights`, `nool usage` | `entire recap` — needs login |

Entire commands that could not run in this local-only setup (recorded, not counted as failures of the tool):

- `entire recap` → exit 0:   ℹ Labels require server analysis (may take a few minutes after committing).
- `entire dispatch` → exit 1: dispatch service returned status 502: "The origin web server returned an invalid or incomplete response to Cloudflare. This typically indicates the origin is ov
- `entire search` → exit 0: }

## Scenario 5 — Policy types on the released host

`benchmark/check_policy_types.py` copies this repository's policy files and checker into a sandbox and drives representative changes through them with **nool 7.24.0**. Raw output is in `benchmark/results/policy-types.json`.

| Case | Policy type | Expected | Exit | Met? |
|---|---|---|---|---|
| known-format secret | DSL SEC-1 (blocking) | refused | 2 | ✅ yes |
| high-entropy token | DSL SEC-2 (warning) | lands; receipt records a warning | 0 | ✅ yes |
| forbidden path | [rules] forbidden_paths | refused | 2 | ✅ yes |
| AI-tagged change without link | [invariants] require_entire_provenance | refused at propose | 0 | ⚠️ known gap |
| invariant audit after AI-tagged change | [invariants] require_entire_provenance | nool verify reports the violation | 0 | ⚠️ known gap |
| push without checkpoint attestation | DSL ENTIRE-1 (evidence) | held (pending evidence) | 3 | ✅ yes |
| checker without a checkpoint | entire-checkpoint checker | fail verdict | 1 | ✅ yes |
| push after failed attestation | DSL ENTIRE-1 (evidence) | refused | 3 | ✅ yes |
| checker with an overlapping checkpoint | entire-checkpoint checker | pass verdict | 0 | ✅ yes |
| push after checkpoint attestation | DSL ENTIRE-1 (evidence) | pushes | 0 | ✅ yes |

Findings:

- Path, content and evidence policies all enforce on the released host: `[rules] forbidden_paths` refuses writes to Entire's runtime state, DSL rule `SEC-1` refuses known-format credentials at propose, and `SEC-2` records a warning in the gate receipt (`nool policy stats` counts that warning as a pass).
- `ENTIRE-1` reads the evidence projection at `pre-push`. Without a trusted `entire-checkpoint` pass, `nool push` exits 3 (`EVIDENCE_PENDING`); a failed attestation does not satisfy it. Once `scripts/attest_entire_checkpoint.py` verifies a checkpoint ref whose recorded files overlap the commit and records a signed pass, the push goes through.
- The `require_entire_provenance` **invariant** is still not enforced on this host, even with `[gating] relational_controls = "block"`: the AI-tagged change landed and `nool verify --all` reported no violation. The repository keeps the invariant for comparison but relies on `ENTIRE-1`.
- Nool exports its commits through libgit2, so Entire's git hooks never add an `Entire-Checkpoint` trailer to them. The checker therefore also accepts an operator-supplied checkpoint ID, and it verifies the ID, the ref and the file overlap either way. It cannot prove that the session wrote those exact lines.

## What each tool is, judged by this evidence

- **Plain Git** — the transport both tools build on. Finds overlap only at merge; resolution is manual.
- **Entire** — a session-capture and attribution layer on top of git hooks. Its distinctive, verified value is *memory*: every agent session and the exact prompt behind a line of code. It does not change how conflicts arise or are resolved. Several team features (search, dispatch, recap) need its hosted service.
- **Nool** — a coordination and governance layer that also uses git as transport (`refs/nool/*`, no clash with `refs/entire/*`). Its distinctive, verified value is *prevention and convergence*: leases that refuse overlapping agents before work starts, automatic union of structurally disjoint edits, a policy gate, and structured handoff/PR artefacts. Weak spots found here: the provenance invariant is not enforced, the legacy fixture's policy module predates newer knots, the semantic same-symbol check missed a real collision, and `nool context` matches symbol names rather than natural-language intent on a small fresh repo.
- **Together** — complementary rather than competing: Entire answers *what was the agent asked and what did it say*; Nool answers *who may touch what now, and does this change meet policy*. The integration point this repo originally attempted failed with the legacy scaffold. On the released host it now works as an evidence rule: a trusted checker links each landed commit to an Entire checkpoint before `nool push` publishes it (Scenario 5).

## Limitations

- Synthetic two-branch scenario on a 15-line file; real codebases will exercise the semantic merge harder.
- Agents are simulated with CLI identities (`--agent-id`/`--as-agent`), not live LLM agents; Entire attribution evidence comes from the earlier Antigravity sessions recorded in this repo.
- Single run, single machine, Nool local coordination backend; no network, no hosted Entire features.
- `tests/test_benchmark.py` also contains CLI smoke tests (many are `--help` checks); they show commands exist, not that they work, and are not counted as evidence above.
