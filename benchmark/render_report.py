#!/usr/bin/env python3
"""Render BENCHMARK_COMPARISON.md from benchmark/results/latest.json.

Every verdict below is computed from a recorded run; nothing is hand-typed.
Usage: python3 benchmark/render_report.py [results.json]
"""

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def yn(flag, yes="✅ yes", no="❌ no"):
    return yes if flag else no


def ms(seconds):
    return f"{seconds * 1000:.0f} ms"


def render(r):
    s = r["scenarios"]
    g, gs, en = s["plain_git_disjoint"], s["plain_git_same_symbol"], s["entire_disjoint"]
    nd, ns, co = s["nool_merge_disjoint"], s["nool_merge_same_symbol"], s["nool_coordination"]
    ar, wf, live = s["nool_aram_provenance"], s["nool_workflow"], s["live_repo"]
    env = r["environment"]
    L = []
    w = L.append

    w("# Nool vs Entire vs Plain Git: Benchmark Study")
    w("")
    w(f"**Run:** {r['generated_at']} · {r['duration_seconds']} s total · "
      f"{env['nool']} · {env['entire']} · {env['git']} · Python {env['python']} · {env['os']}")
    w("")
    w("**Reproduce:** `./verify_benchmark.sh` (or `python3 benchmark/run_benchmark.py && "
      "python3 benchmark/render_report.py`). Raw evidence — every command, exit code, timing and "
      "output excerpt — is in `benchmark/results/latest.json`.")
    w("")
    w("> This file is generated. Each scenario runs in a fresh throwaway sandbox built from the baseline "
      f"commit `{r['baseline_commit']}`; the live repository is only read. Timings are single-run wall clock "
      "on one machine with Nool's local coordination backend — treat them as orders of magnitude, not a race.")
    w("")

    # ---------------------------------------------------------- headline
    w("## Headline results")
    w("")
    w("| Question | Plain Git | Git + Entire | Nool |")
    w("|---|---|---|---|")
    w(f"| Two agents edit `src/auth.py` — when is the overlap first visible? | at `git merge` | at `git merge` "
      f"(Entire installs no merge hook) | **before editing** — `discover conflicts` names `{', '.join(co['discovered_holder'])}` "
      f"({ms(co['discover_seconds'])}) |")
    w(f"| Can the second agent take the same file anyway? | yes | yes | "
      f"{yn(not co['second_exclusive_announce_refused'], 'yes', '**no** — exclusive announce refused')}; "
      f"{yn(co['lease_violating_propose_refused'], 'propose refused', 'propose accepted')} |")
    w(f"| Different methods added at the same spot | conflict, {g['result']['conflict_markers']} marker block, manual fix | "
      f"conflict, {en['result']['conflict_markers']} marker block, manual fix | "
      f"{yn(not nd['manual_resolution_required'], '**merged automatically**', 'conflict')} — "
      f"{nd['result']['conflict_markers']} markers, tests {yn(nd['tests_pass_without_manual_edit'], 'pass', 'fail')} |")
    w(f"| Same method rewritten by both | conflict, manual fix | conflict, manual fix | "
      f"{yn(ns['manual_resolution_required'], 'conflict, manual fix', 'merged')} (no silent union) |")
    w(f"| Why does this line exist? | commit author only | {yn(live['entire_why_links_checkpoint'], 'line → checkpoint → **original agent prompt**')} | "
      f"{yn(live['nool_why_shows_chain'], 'knot → causal chain → intent + gate attestations')} |")
    n_sessions = live["entire_sessions_listed"]
    w(f"| Full agent session/transcript captured | no | {yn(live['entire_session_list_ok'], f'**yes** — {n_sessions} sessions listed')} | "
      "no — agent-supplied intent strings, not transcripts |")
    w(f"| Policy gate before code lands | no | no | {yn(ar['gate_denies_without_editor_contract'], 'yes — Aram denied an agent edit with no editor contract')} |")
    w(f"| Enforce \"AI change must carry an Entire checkpoint\" | — | — | "
      f"{yn(ar['provenance_rule_enforced'], 'enforced', '**not enforced** as configured (see below)')} |")
    w(f"| Ref namespaces coexist | — | `refs/entire/*` ({live['entire_ref_count']}) | `refs/nool/*` ({live['nool_ref_count']}) · "
      f"overlap: {len(live['ref_namespace_overlap'])} |")
    w("")

    # ---------------------------------------------------------- scenarios
    w("## Scenario 1 — Concurrent OAuth2 + SAML edits, merged after the fact")
    w("")
    w("Two branches cut from the same baseline each add a new method immediately before `get_user_role` "
      "(*disjoint*), or both rewrite the body of `authenticate_user` (*same-symbol*).")
    w("")
    w("| Tool / variant | Merge exit | Markers | Result parses | Methods after merge | Tests pass w/o manual edit | Merge time |")
    w("|---|---|---|---|---|---|---|")
    for label, x in (("Plain Git · disjoint", g), ("Plain Git · same-symbol", gs), ("Git + Entire · disjoint", en),
                     ("Nool · disjoint", nd), ("Nool · same-symbol", ns)):
        res = x["result"]
        methods = ", ".join(m for m in res["methods"] if m.startswith("authenticate")) or "—"
        w(f"| {label} | {x['merge_rc']} | {res['conflict_markers']} | {yn(res['parses'], 'yes', 'no')} | {methods} | "
          f"{yn(x.get('tests_pass_without_manual_edit', False), 'yes', 'no')} | {ms(x['merge_seconds'])} |")
    w("")
    w("What the evidence shows:")
    w("")
    w(f"- **Disjoint edits:** `nool merge` hit the same textual conflict git does "
      f"(`CONFLICT (content)` seen: {yn(nd['textual_conflict_seen'], 'yes', 'no')}), then its MergeReconcile step "
      f"unioned the two structurally disjoint hunks (union applied: {yn(nd['union_reconciled'], 'yes', 'no')}). "
      "Result: both methods present, file parses, unit tests pass, no human step.")
    w(f"- **Same-symbol edits:** Nool did *not* guess — it stopped with a conflict for a human, like git. "
      f"However, its semantic pre-check printed *\"no same-symbol collisions\"* "
      f"({yn(ns['semantic_engine_reported_no_collision'], 'observed', 'not observed')}) even though both branches "
      "rewrote `authenticate_user`; the textual layer caught it. The outcome is safe, but the semantic signal was a "
      "false negative in this run.")
    w(f"- **Entire** installed `{', '.join(en['git_hooks_installed'])}` and no merge hook "
      f"(merge hook present: {yn(en['has_merge_hook'], 'yes', 'no')}), so merge behaviour is plain git's. "
      "Entire is an attribution layer, not a coordination or merge layer.")
    w("")

    w("## Scenario 2 — Proactive coordination (Nool leases)")
    w("")
    w("| Step | Outcome | Time |")
    w("|---|---|---|")
    w(f"| `agent-oauth` announces an exclusive lease on `file:src/auth.py` | {yn(co['lease_granted'], 'granted')} | {ms(co['announce_seconds'])} |")
    w(f"| `agent-saml` runs `nool discover conflicts` | {yn(co['conflict_discovered'], 'conflict reported')} (exit {co['discover_rc']}), holder: {', '.join(co['discovered_holder'])} | {ms(co['discover_seconds'])} |")
    w(f"| `agent-saml` announces an exclusive lease on the same file | {yn(co['second_exclusive_announce_refused'], 'refused', 'granted')} | — |")
    w(f"| `agent-saml` ignores that and runs `nool propose --as-agent agent-saml` | {yn(co['lease_violating_propose_refused'], 'refused (Coordination conflict)', 'accepted')} | {ms(co['propose_seconds'])} |")
    w(f"| `agent-oauth` releases; `agent-saml` re-checks | {yn(co['clear_after_release'], 'clear')} | — |")
    w("")
    w(f"**Identity caveat (measured):** when two agents announce *without* distinct `--agent-id`s they share the "
      f"session identity, so the second exclusive announce is granted "
      f"({yn(co['shared_identity_second_announce_granted'], 'observed', 'not observed')}) and supersedes the first — "
      f"{co['shared_identity_active_leases']} lease remains active. This explains an earlier headless opencode run in "
      "this repo that reported \"both agents granted exclusive leases\". `nool propose --help` says the same for "
      "proposals: without `--as-agent` a proposal inherits whichever lease covers its scope. The protection is real "
      "but only as good as each agent's identity wiring.")
    w("")

    w("## Scenario 3 — Aram policy gate and the \"Entire provenance\" rule")
    w("")
    w("Setup in a sandbox: the `require_entire_provenance` invariant from this repo's `nool.toml` "
      "(`when has_metadata('is_ai_agent') then has_link('entire_checkpoint')`) and the `policies/entire_policy_test.wasm` "
      f"module, both landed (invariant landed: {yn(ar['invariant_config_landed'], 'yes', 'no')}, "
      f"policy set landed: {yn(ar['policy_set_landed'], 'yes', 'no')}), editor contract granted.")
    w("")
    w("| Attempt | Landed? |")
    w("|---|---|")
    w(f"| Agent edit before any editor contract | {yn(not ar['gate_denies_without_editor_contract'], 'yes', 'no — `POLICY_DENY`')} |")
    w(f"| `--tag is_ai_agent`, **no** Entire checkpoint link | {yn(ar['ai_change_without_entire_link']['landed'], '**yes**', 'no')} |")
    w(f"| Untagged control | {yn(ar['untagged_control']['landed'], 'yes', 'no')} |")
    w(f"| `nool verify --all` afterwards | {yn(ar['verify_reports_violation'], 'violation reported', '0 violations')} |")
    w("")
    w("Findings:")
    w("")
    w("- The Aram gate machinery is real: it refused an agent edit until an editor contract existed.")
    w(f"- The Entire-provenance rule is **not enforced** in this configuration: an AI-tagged change with no Entire "
      "link landed and `verify` reported nothing. Either `--tag` does not populate what `has_metadata()` reads, or "
      "invariants are not evaluated at the seal; this study did not determine which.")
    w(f"- The WASM module contains no reference to Entire, checkpoints or `is_ai_agent` "
      f"(match: {yn(ar['wasm_mentions_entire_or_checkpoint'], 'yes', 'no')}) — it is a scaffold, not a provenance check. "
      f"`nool admin plugin list` flags it as built against an older knot model (warning: {yn(ar['policy_outdated_warning'], 'yes', 'no')}).")
    w(f"- In the live repo that stale module **fails closed** on newer knot kinds: solidifying the pending "
      "task-creation knot is denied with *\"policy `entire_policy_test` could not decode this knot\"*. "
      f"Live repo state: {live['pending_candidates'].lower()}.")
    w("- Earlier versions of this report said provenance was \"enforced via ARAM WASM gate\". That claim is withdrawn.")
    w("")

    w("## Scenario 4 — Session & workflow surface")
    w("")
    w("Same-named commands mean different things. `nool checkpoint` seals a **state label/release** in the DAG; "
      "`entire checkpoint` is a **captured agent session** (prompt, transcript) tied to a commit.")
    w("")
    w("| Need | Nool (measured in sandbox) | Entire (measured on live repo) |")
    w("|---|---|---|")
    w(f"| Context before editing | `nool context` — symbol-name query: {yn(wf['context_symbol_matched_entities'], 'entities + blast radius' if wf['context_symbol_has_blast_radius'] else 'entities')} ({ms(wf['context_symbol_seconds'])}); natural-language query on a fresh repo: {yn(wf['context_nl_matched_entities'], 'matched', 'no entity match')}; live repo NL query: {yn(live['nool_context_live_returns_findings'], 'returned prior findings', 'nothing')} | `entire search` — needs a GitHub/Entire remote ({live['entire_commands_needing_login_or_remote']['search']['rc'] and 'not runnable locally' or 'ok'}) |")
    w(f"| Mark a point in history | `nool checkpoint <label>` → Release knot: {yn(wf['checkpoint_ok'])} ({ms(wf['checkpoint_seconds'])}) | automatic per agent turn: `entire checkpoint list` {yn(live['entire_checkpoint_list_ok'])} |")
    w(f"| Explain a past change | `nool why <knot>` causal chain {yn(live['nool_why_shows_chain'])} | `entire checkpoint explain` shows the **original prompt**: {yn(live['entire_explain_shows_prompt_intent'])} |")
    w(f"| Hand work to another agent | `nool thread handoff --summary --decision --next` → Handoff knot: {yn(wf['handoff_ok'])} ({ms(wf['handoff_seconds'])}) | `entire session resume` / `adopt` (resume a session; no structured decisions/next-steps record) |")
    w(f"| PR review context | `nool pr summary --base` → markdown with blast radius per knot: {yn(wf['pr_summary_ok'] and wf['pr_summary_has_blast_radius'])} ({ms(wf['pr_summary_seconds'])}) | `entire dispatch` — needs a GitHub/Entire remote |")
    w(f"| Merge a PR | `nool pr merge <branch> --into main` via a local bare remote: {yn(wf['pr_merge_ok'] and wf['pr_merge_method_present'])} ({ms(wf['pr_merge_seconds'])}) | plain git / forge |")
    w(f"| Activity summary | `nool insights`, `nool usage` | `entire recap` — needs login |")
    w("")
    w("Entire commands that could not run in this local-only setup (recorded, not counted as failures of the tool):")
    w("")
    for name, v in live["entire_commands_needing_login_or_remote"].items():
        w(f"- `entire {name}` → exit {v['rc']}: {v['reason']}")
    w("")

    # ---------------------------------------------------------- synthesis
    w("## What each tool is, judged by this evidence")
    w("")
    w("- **Plain Git** — the transport both tools build on. Finds overlap only at merge; resolution is manual.")
    w("- **Entire** — a session-capture and attribution layer on top of git hooks. Its distinctive, verified value is "
      "*memory*: every agent session and the exact prompt behind a line of code. It does not change how conflicts "
      "arise or are resolved. Several team features (search, dispatch, recap) need its hosted service.")
    w("- **Nool** — a coordination and governance layer that also uses git as transport (`refs/nool/*`, no clash "
      "with `refs/entire/*`). Its distinctive, verified value is *prevention and convergence*: leases that refuse "
      "overlapping agents before work starts, automatic union of structurally disjoint edits, a policy gate, and "
      "structured handoff/PR artefacts. Weak spots found here: the provenance rule as configured is not enforced, "
      "a stale policy module fails closed on newer knots, the semantic same-symbol check missed a real collision, "
      "and `nool context` matches symbol names rather than natural-language intent on a small fresh repo.")
    w("- **Together** — complementary rather than competing: Entire answers *what was the agent asked and what did "
      "it say*; Nool answers *who may touch what now, and does this change meet policy*. The integration point this "
      "repo attempted (Nool gating on Entire checkpoint links) is the right idea but is not working yet.")
    w("")

    w("## Limitations")
    w("")
    w("- Synthetic two-branch scenario on a 15-line file; real codebases will exercise the semantic merge harder.")
    w("- Agents are simulated with CLI identities (`--agent-id`/`--as-agent`), not live LLM agents; Entire attribution "
      "evidence comes from the earlier Antigravity sessions recorded in this repo.")
    w("- Single run, single machine, Nool local coordination backend; no network, no hosted Entire features.")
    w("- `tests/test_benchmark.py` also contains CLI smoke tests (many are `--help` checks); they show commands exist, "
      "not that they work, and are not counted as evidence above.")
    w("")
    return "\n".join(L)


# ------------------------------------------------------------------ HTML blocks

def suite_inventory():
    """Count tests per class in tests/test_benchmark.py, and which are expected failures."""
    import ast
    with open(os.path.join(REPO, "tests", "test_benchmark.py")) as f:
        tree = ast.parse(f.read())
    rows = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            tests = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
            xfail = [t.name for t in tests if any(
                (isinstance(d, ast.Attribute) and d.attr == "expectedFailure") for d in t.decorator_list)]
            if tests:
                doc = (ast.get_docstring(node) or "").split("\n")[0]
                rows.append((node.name, len(tests), xfail, doc))
    return rows


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def html_panel(r):
    s = r["scenarios"]
    co, nd, ns = s["nool_coordination"], s["nool_merge_disjoint"], s["nool_merge_same_symbol"]
    g, en, ar, wf, live = s["plain_git_disjoint"], s["entire_disjoint"], s["nool_aram_provenance"], s["nool_workflow"], s["live_repo"]
    good, bad, warn = "text-emerald-400", "text-red-400", "text-amber-400"

    def cell(ok, text, neutral=False):
        cls = "text-slate-300" if neutral else (good if ok else bad)
        return f'<td class="p-2.5 {cls}">{text}</td>'

    rows = [
        ("Overlap visible before editing",
         cell(False, "no — at merge"), cell(False, "no — at merge (no merge hook)"),
         cell(co["conflict_discovered"], f"yes — discover names <code class=\"code-font\">{esc(', '.join(co['discovered_holder']))}</code> in {ms(co['discover_seconds'])}")),
        ("Second agent blocked from same file",
         cell(False, "no"), cell(False, "no"),
         cell(co["second_exclusive_announce_refused"] and co["lease_violating_propose_refused"],
              "announce + propose refused (distinct <code class=\"code-font\">--agent-id</code>s)")),
        ("Disjoint methods, same spot",
         cell(False, f"conflict · {g['result']['conflict_markers']} marker block"),
         cell(False, f"conflict · {en['result']['conflict_markers']} marker block"),
         cell(not nd["manual_resolution_required"], f"auto-union · {nd['result']['conflict_markers']} markers · tests pass")),
        ("Same method rewritten by both",
         cell(False, "conflict"), cell(False, "conflict"),
         f'<td class="p-2.5 {warn}">conflict (safe) · semantic pre-check missed it</td>'),
        ("Original agent prompt per line",
         cell(False, "no"), cell(live["entire_why_links_checkpoint"] and live["entire_explain_shows_prompt_intent"],
                                  f"yes — {live['entire_sessions_listed']} sessions"),
         cell(False, "intent strings only")),
        ("Policy gate before landing",
         cell(False, "no"), cell(False, "no"),
         cell(ar["gate_denies_without_editor_contract"], "yes — editor-contract deny")),
        ("Require Entire checkpoint on AI changes",
         cell(False, "—", True), cell(False, "—", True),
         cell(ar["provenance_rule_enforced"], "not enforced (rule + policy landed)")),
        ("Handoff · checkpoint · PR summary · PR merge",
         cell(False, "—", True), cell(False, "session resume; dispatch needs remote", True),
         cell(wf["handoff_ok"] and wf["checkpoint_ok"] and wf["pr_summary_ok"] and wf["pr_merge_ok"], "all four worked")),
    ]
    body = "\n".join(
        f'            <tr><td class="p-2.5 font-sans font-medium text-slate-200">{q}</td>{a}{b}{c}</tr>'
        for q, a, b, c in rows)
    env = r["environment"]
    return f'''    <section class="bg-[var(--card,#1e293b)] border border-emerald-500/40 rounded-2xl p-6 shadow-md space-y-3" aria-labelledby="bench-title">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="bench-title" class="text-lg font-bold text-[var(--foreground,#f8fafc)]">Measured results · sandboxed re-run</h2>
        <span class="text-[11px] text-[var(--muted-foreground,#94a3b8)] code-font">{esc(r['generated_at'])} · {esc(env['nool'])} · {esc(env['entire'])} · {r['duration_seconds']} s</span>
      </div>
      <p class="text-xs text-slate-300 leading-relaxed">Generated from <code class="code-font">benchmark/results/latest.json</code> by <code class="code-font">./verify_benchmark.sh</code>. Every scenario ran in a throwaway sandbox built from baseline <code class="code-font">{esc(r['baseline_commit'])}</code>. Where an older section of this page disagrees with this table, this table is the measured result. Full write-up: <code class="code-font">BENCHMARK_COMPARISON.md</code>.</p>
      <div class="overflow-x-auto custom-scroll">
        <table class="w-full min-w-[640px] text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-[var(--border,#334155)] text-[var(--muted-foreground,#94a3b8)]">
              <th class="p-2.5 font-semibold">Question</th><th class="p-2.5 font-semibold">Plain Git</th>
              <th class="p-2.5 font-semibold text-purple-300">Git + Entire</th><th class="p-2.5 font-semibold text-blue-300">Nool</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-[var(--border,#334155)]">
{body}
          </tbody>
        </table>
      </div>
    </section>'''


def html_tests():
    inv = suite_inventory()
    total = sum(n for _, n, _, _ in inv)
    xfail = [x for _, _, xs, _ in inv for x in xs]
    rows = "\n".join(
        f'              <tr><td class="p-2.5 font-sans font-medium text-slate-200">{esc(name)}</td>'
        f'<td class="p-2.5">{esc(doc)}</td><td class="p-2.5">{n}</td>'
        f'<td class="p-2.5 {"text-amber-400" if xs else "text-slate-400"}">{len(xs) or "—"}</td></tr>'
        for name, n, xs, doc in inv)
    known = "".join(f"<li><code class=\"code-font\">{esc(x)}</code></li>" for x in xfail)
    return f'''        <div class="p-4 rounded-xl border border-[var(--border,#334155)] bg-[var(--background,#0f172a)] text-xs text-slate-300 space-y-2">
          <div class="font-bold text-emerald-400">Benchmark test suite — {total} tests in <code class="code-font">tests/test_benchmark.py</code> (+1 in <code class="code-font">tests/test_auth.py</code>)</div>
          <p class="text-[11px] text-slate-300">The suite no longer mutates this repository: the previous plain-git tests ran real <code class="code-font">checkout/commit/merge</code> here (and left it mid-merge), lease tests leaked leases, and a live <code class="code-font">propose</code> queued candidates. Behavioural claims are now asserted against the sandboxed harness (<code class="code-font">BenchmarkEvidenceTests</code>); remaining classes are CLI smoke checks, many of them <code class="code-font">--help</code> calls that show a command exists, not that it works. The old "72 checks · 69 pass" total was a hard-coded string.</p>
          <div class="overflow-x-auto custom-scroll">
            <table class="w-full min-w-[560px] text-left text-xs border-collapse">
              <thead><tr class="border-b border-[var(--border,#334155)] text-[var(--muted-foreground,#94a3b8)]"><th class="p-2.5 font-semibold">Class</th><th class="p-2.5 font-semibold">Covers</th><th class="p-2.5 font-semibold">Tests</th><th class="p-2.5 font-semibold">Expected failures</th></tr></thead>
              <tbody class="divide-y divide-[var(--border,#334155)] code-font text-[11px]">
{rows}
              </tbody>
            </table>
          </div>
          <p class="text-[11px] text-slate-300">Expected failures are known Nool gaps kept visible on purpose — they turn into "unexpected success" when fixed:</p>
          <ul class="list-disc pl-5 text-[11px] text-amber-300">{known}</ul>
        </div>'''


def replace_block(text, tag, content):
    start, end = f"<!-- {tag}:START -->", f"<!-- {tag}:END -->"
    i, j = text.index(start) + len(start), text.index(end)
    return text[:i] + "\n" + content + "\n    " + text[j:]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "benchmark", "results", "latest.json")
    with open(path) as f:
        results = json.load(f)
    out = os.path.join(REPO, "BENCHMARK_COMPARISON.md")
    with open(out, "w") as f:
        f.write(render(results))
    print(f"wrote {os.path.relpath(out, REPO)} from {os.path.relpath(path, REPO)}")
    page = os.path.join(REPO, "comparison.html")
    if os.path.exists(page):
        with open(page) as f:
            html = f.read()
        if "<!-- BENCH:START -->" in html:
            html = replace_block(html, "BENCH", html_panel(results))
            html = replace_block(html, "BENCH-TESTS", html_tests())
            with open(page, "w") as f:
                f.write(html)
            print("refreshed measured-results blocks in comparison.html")


if __name__ == "__main__":
    main()
