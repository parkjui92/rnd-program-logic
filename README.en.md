# rnd-program-logic — logic-model and indicator design checker for government R&D programs

Write a program's **input → activity → output → short-term outcome → long-term outcome / performance goal** chain and its indicators and targets in a YAML design file. The tool checks broken links, indicator fitness and whether each target has a stated basis, and emits a **checklist + indicator table + logic-model figure (SVG) + a "nothing invented" section**. Every check names the statute article or guideline section it follows; guidelines whose original text could not be verified are marked **[확인 필요] (to be verified)**.

Standard library only. No install, no API key, no browser.

```bash
python3 program_logic.py init --out program.yaml
python3 program_logic.py check program.yaml --out out    # → out/check.json (exit 3 if any broken link / unfit indicator)
python3 program_logic.py render program.yaml --out out   # → out/logic_model.svg/.html + figure_spec.json
python3 program_logic.py report program.yaml --out out   # → out/report.md
python3 program_logic.py evidence
python3 program_logic.py selftest
```

Korean README: [README.md](README.md). Korean is the working language of the reports and checks; this file summarises the design.

## What it checks

| Group | Items | Basis (verified against original text, 2026-10-20) |
|---|---|---|
| Chain C1–C12 | goals present · five boxes filled · references resolve · **activity with no output** · **output with no outcome** · **outcome not linked to a goal** · orphan nodes · "so that" sentence (`because`) on links · **inputs written as outcomes** · **sub-program split** · program type / life-cycle · external conditions | Act on Performance Evaluation and Management of National R&D Programs art. 6(1)(2); National Finance Act art. 85-2(1)1; MSIT Guide to Performance Goals and Indicators (6th ed.) III.1 (logic model), III.2 (program types); 5th Basic Plan for R&D Performance Evaluation (2025-10-30) |
| Indicators I1–I10 | measured node & stage match · input/process indicators (**unfit**) · ≥2 indicators per goal · majority qualitative · simple counts · outcome-level indicators · formula present / process items in formula (**unfit**) / name–formula mismatch · sales/export indicators need contribution-rate or net-effect · composite indicators · paper indicators outside basic research | Guide V.3 ①–④, V.4 ①–④, Appendix 3; Act art. 3(5), art. 12(4); KISTEP special evaluation of the Nano-Convergence 2020 program (2019) |
| Targets T1–T6 | yearly targets · stated basis · baseline · **mechanical increments** (arithmetic/geometric, "n% above last year") · lowered after poor results (**unfit**) · source of the basis | Guide V.5 ①–③, V.6 |

Verdicts: `오류` error (design unreadable) · `끊김` broken link · `부적정` unfit (what the guide says "cannot be regarded as a performance indicator") · `보완` improve · `확인 필요` not in input · `적정` fine.

**Not verified** and therefore never used as primary basis: the Ministry of Finance "self-evaluation of fiscal programs" guideline items (the self-evaluation itself was replaced by an integrated external evaluation in 2026, per press), the 2022–2026 Fiscal Program Performance Management Basic Plan, and a general KISTEP special-evaluation guideline.

## Outputs

`report.md` (basic facts · chain table with sources · link verdicts · **checklist with basis and fix suggestion** · **indicator table** · **nothing-invented section** · figure · evidence table with verification status · honesty rules), `logic_model.svg/.html` (five columns; broken nodes in red dashed outline, links without a "so that" sentence dashed, indicator chips under the node they measure), `figure_spec.json` (a [doc-figure](https://github.com/parkjui92/doc-figure) `structure-block` spec), `check.json`.

## Examples

- `examples/synthetic/` — a fictitious program with 11 planted defects; all are caught, clean nodes raise nothing (tests).
- `examples/nano2020/` — a **real public program**, Nano-Convergence 2020 (MSIT/MOTIE, 2012–2020), reconstructed solely from KISTEP's special-evaluation report (2019-10; page references in `sources.md`). 4 broken links, 14 improve, 5 to-verify. Every target basis in the report's table 3-10 reads "n% above last year's result", so T4 fires on five indicators — the evaluators flagged the same spot.

## Honesty rules (printed in every report)

1. Nothing missing from the input is filled in; it stays `[확인 필요]`. Empty boxes are drawn empty.
2. "Broken" is a fact about the design file, not a judgment about the program.
3. Each check carries its basis and that basis's verification status; unverified guidelines are never primary basis.
4. No replacement indicators or target numbers are proposed.
5. The machine reads characters. A contribution-rate term in a formula passes the rule; whether it truly isolates the program's direct benefit is for a person to judge.
6. The design file's sha is written into every output.

## Limits

Character-level rules only (no semantic check of name–formula fit or type-specific outcome domains); no achievement or effect estimation (see [policy-did](https://github.com/parkjui92/policy-did)); no source-existence checking (see [fact-verify](https://github.com/parkjui92/fact-verify)); the impact box is not drawn; the built-in YAML parser reads a subset (PyYAML is used when present).

MIT.
