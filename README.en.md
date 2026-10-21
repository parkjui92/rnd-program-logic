# rnd-program-logic — logic-model and indicator design checker for government R&D programs

Write how a program claims to turn money into results in five boxes (input → activity → output → outcome → performance goal). The tool finds the empty boxes and broken links, checks whether each indicator measures an output or outcome rather than spending, and whether each target has a stated basis, then emits a **checklist, an indicator table and a logic-model figure**. One Python file, nothing to install.

Korean README (the working language of the reports): [README.md](README.md)

## Why

Program documents for government R&D are full of activities ("we support, we promote") but rarely say what comes out (outputs) or what that changes for whom (outcomes). Indicators default to what is easy to count (papers, projects), and the basis for a target is often just "10% above last year". Evaluators then write exactly that in their findings. In one special-evaluation report all seven target-basis lines read "n% above last year's result", and the evaluators called the basis inadequate.

Drawing the five boxes by hand does reveal the gaps, but a person has to spot them and look up, every time, which guideline item they violate. This tool codifies that procedure: a person fills the boxes from the documents; the tool finds empty boxes, broken links and unfounded targets and reports them with the guideline item. It never fills in what the documents do not say.

> **Terms** — A *logic model* draws a program as inputs (money, people) → activities (what is done) → outputs (direct products of the activity) → outcomes (the change those outputs cause). "n prototypes" is an output; "supply contracts won by firms that used them" is an outcome. Performance indicators should measure outputs or outcomes; budget execution rates or meeting counts measure inputs and process and are not performance indicators.

## Start with a complete example

Use Python 3.10 or newer; no API key, network connection, or LLM is needed after downloading.

```bash
git clone https://github.com/parkjui92/rnd-program-logic.git
cd rnd-program-logic
python3 program_logic.py report examples/synthetic/program.yaml --out out/first-look
```

Open `out/first-look/report.md`, `logic_model.html`, and `check.json`. The synthetic example deliberately includes defects, so FAIL and exit code 3 are expected. The `open` command below is macOS-specific; other systems can open the files in a file manager.

Use this before a program-design meeting, when revising indicators, or when applying the same checklist to several programs. Its strength is traceable, repeatable rule checks with guideline references. A person must transcribe the source documents into YAML and assess meaning; the tool does not ingest PDF/HWP or certify program quality. Goal, node, and indicator IDs must be unique within their respective lists. Use different output folders to preserve revisions.

## How

```bash
curl -O https://raw.githubusercontent.com/parkjui92/rnd-program-logic/main/program_logic.py
python3 program_logic.py init --out program.yaml       # 1) get the design template
#   … fill program.yaml from the program documents (snippet below)
python3 program_logic.py report program.yaml --out out  # 2) checklist, indicator table, figure
open out/report.md out/logic_model.html                 # 3) read
```

A design file looks like this. Copy the documents' own sentences into each box with a page reference; link boxes with `uses` / `from` / `goal`; put the document's "so that" sentence in `because`; say which box an indicator measures in `measures`.

```yaml
name: example_materials_commercialisation
period: {start: 2027, end: 2031, type: 기한}
program_type: 중장기산업기술개발
performance_goals:
  - {id: G1, text: "core gap technologies pass customer validation", source: "p.1"}
chain:
  inputs:
    - {id: I1, text: "KRW 24bn/yr, industry–academia researchers", source: "p.3"}
  activities:
    - {id: A1, text: "call, selection and funding of gap-technology projects", uses: [I1], source: "p.5"}
    - {id: A3, text: "results exchange meetings", uses: [I1], source: "p.6"}     # no output → broken
  outputs:
    - {id: O2, text: "technologies that passed customer validation", from: [A1], source: "p.5"}
  outcomes_short:
    - {id: S1, text: "first supply contract of participating firms", from: [O2],
       because: "validated technologies enter the customer's quality-approval process", source: "p.7"}
  outcomes_long:
    - {id: L2, text: "domestic supply of core gap technologies", from: [S1], goal: G1, because: "", source: "p.8"}
indicators:
  - id: K2
    name: customer validation pass rate
    stage: 산출          # output
    measures: O2
    goal: G1
    kind: 질적           # qualitative
    formula: "passed / started × 100"
    baseline: {year: 2025, value: 40, source: "peer program"}
    targets: {2028: 45, 2029: 50, 2030: 60, 2031: 70}
    target_basis: "best peer-program result 70% and participants' capacity"
    target_source: "p.9"
  - id: K5
    name: firms entering supply chains
    stage: 결과          # outcome
    measures: L1
    kind: 양적           # quantitative
    targets: {2028: 5, 2029: 6, 2030: 7, 2031: 8}
    target_basis: "10% above last year"                                           # mechanical → improve
```

The checklist in `out/report.md` (excerpt; verdicts and basis are printed in Korean):

| Item | Verdict | Where | Finding | Basis | Suggested fix |
|---|---|---|---|---|---|
| C4 activity with no output | 끊김 broken | A3 | no output follows "results exchange meetings" | MSIT Guide (6th) III.1 p.8–10 | find what this activity produces and add it to `outputs`; if the document says nothing, leave it broken |
| I2 input/process indicator | 부적정 unfit | K1 | "budget execution rate" measures input | Guide V.3 ④ p.38 | replace with an indicator of the output/outcome it points to |
| T4 mechanical increment | 보완 improve | K5 | targets +1/yr; basis "10% above last year" | Guide V.5 ① p.42 | use past results as baseline only; derive targets from the level to be reached |
| T2 target basis | 확인 필요 to verify | K6 | no stated basis | Guide V.5 ①·② | add the basis sentence; if absent, leave `[확인 필요]` — do not invent |

The indicator table lists, per indicator: goal, measured node, stage, qualitative/quantitative, formula, yearly targets, baseline, target basis, external-factor handling, verdict. The figure draws the five columns; broken nodes get a red dashed outline, links without a "so that" sentence are dashed, indicator chips sit under the node they measure.

![example figure](examples/nano2020/out/logic_model.svg)

| Command | Does |
|---|---|
| `init --out program.yaml` | design template with field-by-field comments |
| `check program.yaml --out out` | checks only → `check.json`; exit 3 on any broken link / unfit indicator |
| `render program.yaml --out out` | figure only → `logic_model.svg/.html` + `figure_spec.json` ([doc-figure](https://github.com/parkjui92/doc-figure) spec) |
| `report program.yaml --out out` | everything → `report.md` (`run` is the same) |
| `evidence` | each check's statute/guideline item and its verification status |

## What it does not do

- **It never fills in what the input lacks.** Missing outputs, outcomes, targets or bases stay `[확인 필요]`; empty boxes are drawn empty. No replacement indicators or target numbers are proposed.
- **"Broken" is a fact about the design file, not a judgment about the program.**
- **It reads characters.** Whether a name and a formula measure the same thing in meaning, or whether an indicator fits the program type's expected outcome domain, is for a person. A contribution-rate term in a formula passes the rule; whether it truly isolates the program's direct benefit is not judged.
- Achievement and effect estimation: [policy-did](https://github.com/parkjui92/policy-did). Source existence: [fact-verify](https://github.com/parkjui92/fact-verify). Reading documents to fill the boxes: the `program-logic-check` skill in [rnd-eval-skills](https://github.com/parkjui92/rnd-eval-skills), whose broken-link types and indicator questions this tool turns into rules.

## Checks and basis

| Group | Items | Basis (verified against original text, 2026-10-20) |
|---|---|---|
| Chain C1–C12 | goals present · five boxes · references resolve · **activity with no output** · **output with no outcome** · **outcome not linked to a goal** · orphan nodes · "so that" sentence · **inputs written as outcomes** · **sub-program split** · program type / life-cycle · external conditions | Act on Performance Evaluation and Management of National R&D Programs art. 6(1)(2); National Finance Act art. 85-2(1)1; MSIT Guide to Performance Goals and Indicators (6th ed.) III.1, III.2; 5th Basic Plan for R&D Performance Evaluation (2025-10-30) |
| Indicators I1–I10 | measured node & stage · input/process (**unfit**) · ≥2 per goal · majority qualitative · simple counts · outcome-level indicators · formula / process items in formula (**unfit**) / name–formula mismatch · contribution-rate or net-effect for sales/export · composite indicators · paper indicators outside basic research | Guide V.3 ①–④, V.4 ①–④, Appendix 3; Act art. 3(5), 12(4); KISTEP special evaluation of Nano-Convergence 2020 (2019) |
| Targets T1–T6 | yearly targets · stated basis · baseline · **mechanical increments** · lowered after poor results (**unfit**) · source of basis | Guide V.5 ①–③, V.6 |

**Not verified** and never used as primary basis: the Ministry of Finance fiscal-program self-evaluation guideline items (replaced by an integrated external evaluation in 2026, per press), the 2022–2026 Fiscal Program Performance Management Basic Plan, and a general special-evaluation guideline. Design decisions are in [docs/design.md](docs/design.md) (Korean).

## Examples

- `examples/synthetic/` — fictitious program with 11 planted defects; all caught, no false positives on clean nodes (tests).
- `examples/nano2020/` — a **real public program**, Nano-Convergence 2020 (MSIT/MOTIE, 2012–2020), reconstructed solely from KISTEP's special-evaluation report (2019-10; pages in `sources.md`). 4 broken, 14 improve, 5 to-verify; the evaluators flagged the same target-basis problem.

## Honesty rules (printed in every report)

1. Nothing missing from the input is filled in. 2. "Broken" is a fact, not a judgment. 3. Every check carries its basis and that basis's verification status. 4. No replacement indicators or target numbers. 5. The machine reads characters; meaning is for a person. 6. The design file's sha is written into every output.

## Status and limits

The initial release passed 20 tests (`python3 program_logic.py selftest`); both examples run end to end. Character-level rules only; the impact box is not drawn; the built-in YAML parser reads a subset (PyYAML is used when present). MIT.
