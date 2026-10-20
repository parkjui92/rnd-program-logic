import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import program_logic as pl  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "examples" / "synthetic" / "program.yaml"
NANO = ROOT / "examples" / "nano2020" / "program.yaml"


def _run(args):
    try:
        pl.main(args)
    except SystemExit as e:
        if e.code is None:
            return 0
        return e.code if isinstance(e.code, int) else 1
    return 0


def _findings(path: Path):
    d = pl.load_design(path)
    return d, pl.run_checks(d)


def _has(fs, check, level=None, where=None):
    for f in fs:
        if f.check == check and (level is None or f.level == level) and (where is None or f.where == where):
            return True
    return False


class TestMiniYaml(unittest.TestCase):
    def test_subset(self):
        text = """
name: 예시
n: 3
quoted: "a: b # not comment"
list: [1, 2, 서울]
targets:
  2027: 95
  2028: null
items:
  - id: K1
    kind: 질적
    baseline: {year: 2025, value: 4.5}
"""
        d = pl._MiniYaml(text).parse()
        self.assertEqual(d["name"], "예시")
        self.assertEqual(d["quoted"], "a: b # not comment")
        self.assertEqual(d["list"], [1, 2, "서울"])
        self.assertEqual(d["targets"], {2027: 95, 2028: None})  # 정수 키는 int (PyYAML 과 같게)
        self.assertEqual(d["items"][0]["baseline"]["value"], 4.5)

    def test_parity_with_pyyaml_if_available(self):
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("PyYAML 없음")
        for p in (SYN, NANO):
            t = p.read_text(encoding="utf-8")
            self.assertEqual(yaml.safe_load(t), pl._MiniYaml(t).parse(), p.name)

    def test_template_parses_with_mini(self):
        text = pl.DESIGN_TEMPLATE.format(y0=2027, y1=2031)
        d = pl._MiniYaml(text).parse()
        self.assertIn("chain", d)
        self.assertEqual(d["indicators"][0]["targets"], {2027: None})


class TestChecksSynthetic(unittest.TestCase):
    """합성 설계서에 심은 결함을 전부 잡는가."""

    @classmethod
    def setUpClass(cls):
        cls.d, cls.fs = _findings(SYN)

    def test_broken_links(self):
        self.assertTrue(_has(self.fs, "C4", pl.BROKEN, "A3"))   # 산출 없는 활동
        self.assertTrue(_has(self.fs, "C5", pl.BROKEN, "O3"))   # 결과 없는 산출
        self.assertTrue(_has(self.fs, "C6", pl.BROKEN, "G3"))   # 목표에 닿는 결과 없음
        self.assertTrue(_has(self.fs, "C8", pl.WARN, "S2"))     # because 없음
        self.assertTrue(_has(self.fs, "C9", pl.FAIL, "L1"))     # 참여기관 수가 결과 칸에

    def test_indicator_rules(self):
        self.assertTrue(_has(self.fs, "I2", pl.FAIL, "K1"))     # 투입지표
        self.assertTrue(_has(self.fs, "I7", pl.FAIL, "K3"))     # 위원회 운영 건수
        self.assertTrue(_has(self.fs, "I8", pl.WARN, "K4"))     # 매출인데 기여율 없음
        self.assertTrue(_has(self.fs, "I3", pl.WARN, "G3"))     # 목표별 지표 2개 미만

    def test_target_rules(self):
        self.assertTrue(_has(self.fs, "T4", pl.WARN, "K5"))     # 등차 + 전년 실적 10% 상향
        self.assertTrue(_has(self.fs, "T4", pl.WARN, "K4"))     # 등차 100/년
        self.assertTrue(_has(self.fs, "T1", pl.UNVERIFIED, "K6"))
        self.assertTrue(_has(self.fs, "T2", pl.UNVERIFIED, "K6"))
        self.assertTrue(_has(self.fs, "T3", pl.UNVERIFIED, "K6"))
        self.assertFalse(_has(self.fs, "T4", None, "K2"))      # 근거가 최고 수준·역량인 지표는 걸리지 않는다

    def test_no_false_positive_on_clean_nodes(self):
        self.assertFalse(_has(self.fs, "C4", None, "A1"))
        self.assertFalse(_has(self.fs, "C5", None, "O2"))
        self.assertFalse(_has(self.fs, "C9", None, "L2"))
        self.assertFalse(_has(self.fs, "I2", None, "K2"))

    def test_overall_fail(self):
        self.assertEqual(pl.overall(self.fs), "FAIL")


class TestChecksEdge(unittest.TestCase):
    def _design(self, text):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p.yaml"
            p.write_text(text, encoding="utf-8")
            return _findings(p)

    def test_clean_design_passes_or_warns_only(self):
        text = """
name: 깨끗한_예시
agency: 부처
period: {start: 2027, end: 2031, type: 기한}
program_type: 성과확산
program_type_basis: "문서 2쪽 명시"
lifecycle: 초기
strategic_goal: {text: "전략목표", source: "문서 1쪽"}
performance_goals:
  - {id: G1, text: "목표1", source: "문서 1쪽"}
chain:
  inputs: [{id: I1, text: "자금", source: "s"}]
  activities: [{id: A1, text: "지원", uses: [I1], source: "s"}]
  outputs: [{id: O1, text: "검증 통과 기술", from: [A1], source: "s"}]
  outcomes_short: [{id: S1, text: "첫 공급계약", from: [O1], because: "통과하면 승인 절차로", source: "s"}]
  outcomes_long: [{id: L1, text: "국산 공급", from: [S1], goal: G1, because: "계약이 쌓이면", source: "s"}]
indicators:
  - {id: K1, name: 검증 통과율, stage: 산출, measures: O1, goal: G1, kind: 질적, formula: "통과/착수×100", unit: "%", data_source: d, baseline: {year: 2025, value: 40, source: s}, targets: {2028: 45, 2029: 55, 2030: 70}, target_basis: "세계 최고 수준 70%", target_source: "문서 9쪽"}
  - {id: K2, name: 공급계약 체결 기업 비율, stage: 결과, measures: S1, goal: G1, kind: 질적, formula: "계약 기업/참여 기업", unit: "%", data_source: d, baseline: {year: 2025, value: 10, source: s}, targets: {2029: 20, 2030: 35, 2031: 45}, target_basis: "유사사업 상위 사례", target_source: "문서 9쪽"}
context: {external_conditions: "시장 여건", concurrent_programs: ""}
"""
        d, fs = self._design(text)
        self.assertNotIn(pl.BROKEN, {f.level for f in fs})
        self.assertNotIn(pl.FAIL, {f.level for f in fs})
        self.assertNotIn(pl.ERROR, {f.level for f in fs})
        self.assertIn(pl.overall(fs), ("PASS", "WARN"))

    def test_bad_reference_is_error(self):
        text = """
name: x
performance_goals: [{id: G1, text: g}]
chain:
  inputs: [{id: I1, text: a}]
  activities: [{id: A1, text: b, uses: [I9]}]
  outputs: [{id: O1, text: c, from: [A1]}]
  outcomes_short: [{id: S1, text: d, from: [O1]}]
  outcomes_long: [{id: L1, text: e, from: [S1], goal: G7}]
indicators: [{id: K1, name: n, stage: 산출, measures: O9, goal: G1}]
"""
        d, fs = self._design(text)
        errs = [f for f in fs if f.level == pl.ERROR]
        self.assertEqual(len(errs), 3)
        self.assertEqual(pl.overall(fs), "ERROR")

    def test_empty_stage_is_broken_and_drawn(self):
        text = """
name: x
performance_goals: [{id: G1, text: g}]
chain:
  inputs: [{id: I1, text: a}]
  activities: [{id: A1, text: b, uses: [I1]}]
  outputs: []
  outcomes_short: []
  outcomes_long: []
indicators: []
"""
        d, fs = self._design(text)
        self.assertTrue(_has(fs, "C2", pl.BROKEN, "산출"))
        self.assertTrue(_has(fs, "I1", pl.BROKEN, "indicators"))
        svg = pl.render_svg(d, fs)
        self.assertIn("비어 있음 — 끊김", svg)

    def test_mechanical_detection(self):
        self.assertTrue(pl._is_mechanical([10, 12, 14]).startswith("등차"))
        self.assertTrue(pl._is_mechanical([100, 120, 144]).startswith("등비"))
        self.assertIsNone(pl._is_mechanical([10, 15, 17]))
        self.assertIsNone(pl._is_mechanical([10, 12]))
        self.assertIsNone(pl._is_mechanical([5, 5, 5]))

    def test_lowered_target_is_fail(self):
        text = """
name: x
performance_goals: [{id: G1, text: g}]
chain:
  inputs: [{id: I1, text: a}]
  activities: [{id: A1, text: b, uses: [I1]}]
  outputs: [{id: O1, text: c, from: [A1]}]
  outcomes_short: [{id: S1, text: d, from: [O1], because: e}]
  outcomes_long: [{id: L1, text: e, from: [S1], goal: G1, because: f}]
indicators: [{id: K1, name: n, stage: 산출, measures: O1, goal: G1, kind: 질적, formula: f, targets: {2027: 3}, target_basis: 로드맵, target_source: s, baseline: {value: 1, year: 2025}, target_lowered_for_low_performance: true}]
"""
        d, fs = self._design(text)
        self.assertTrue(_has(fs, "T5", pl.FAIL, "K1"))

    def test_name_formula_mismatch(self):
        text = """
name: x
performance_goals: [{id: G1, text: g}]
chain:
  inputs: [{id: I1, text: a}]
  activities: [{id: A1, text: b, uses: [I1]}]
  outputs: [{id: O1, text: c, from: [A1]}]
  outcomes_short: [{id: S1, text: d, from: [O1], because: e}]
  outcomes_long: [{id: L1, text: e, from: [S1], goal: G1, because: f}]
indicators: [{id: K1, name: 수요기관 업무 활용도, stage: 결과, measures: S1, goal: G1, kind: 질적, formula: "담당자 만족도 5점 척도 100점 환산", targets: {2027: 80}, target_basis: 사례, target_source: s, baseline: {value: 70, year: 2025}}]
"""
        d, fs = self._design(text)
        self.assertTrue(_has(fs, "I7", pl.FAIL, "K1"))


class TestEvidence(unittest.TestCase):
    def test_every_check_has_evidence_and_every_evidence_has_status(self):
        for cid, (title, evs) in pl.CHECKS.items():
            self.assertTrue(evs, cid)
            for e in evs:
                self.assertIn(e, pl.EVIDENCE, f"{cid} → {e}")
        for k, v in pl.EVIDENCE.items():
            self.assertIn(v["status"], ("확인", "확인 필요"), k)
            if v["status"] == "확인":
                self.assertTrue(v["checked"], f"{k}: 확인이면 날짜가 있어야 한다")
            else:
                self.assertIsNone(v["checked"])

    def test_unverified_evidence_is_flagged_in_report(self):
        d, fs = _findings(SYN)
        res = pl.check_to_dict(d, SYN, fs)
        md = pl.build_report(d, res, fs, "logic_model.svg")
        self.assertIn("재정사업 자율평가 지침", md)
        self.assertIn("**확인 필요**", md)
        for h in pl.HONESTY:
            self.assertIn(h, md)


class TestOutputs(unittest.TestCase):
    def test_report_sections_and_files(self):
        with tempfile.TemporaryDirectory() as td:
            rc = _run(["report", str(NANO), "--out", td, "--quiet"])
            self.assertEqual(rc, 3)  # FAIL(끊김) → 3
            out = Path(td)
            for f in ("report.md", "check.json", "logic_model.svg", "logic_model.html", "figure_spec.json"):
                self.assertTrue((out / f).exists(), f)
            md = (out / "report.md").read_text(encoding="utf-8")
            for sec in ("## 0. 기본 칸", "## 1. 사슬 표", "## 2. 연결 판정", "## 3. 점검표", "## 4. 지표표",
                        "## 5. 지어내지 않은 것", "## 6. 논리모형 그림", "## 7. 근거 표", "## 8. 정직성 규칙"):
                self.assertIn(sec, md)
            self.assertIn("[확인 필요]", md)
            res = json.loads((out / "check.json").read_text(encoding="utf-8"))
            self.assertEqual(res["status"], "FAIL")
            self.assertEqual(len(res["design_sha"]), 16)
            self.assertTrue(res["unverified"])
            spec = json.loads((out / "figure_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["template"], "structure-block")
            self.assertEqual(len(spec["layers"]), 5)

    def test_svg_contains_nodes_indicators_and_broken_marks(self):
        d, fs = _findings(SYN)
        svg = pl.render_svg(d, fs)
        self.assertTrue(svg.startswith("<svg"))
        for nid in d.nodes:
            self.assertIn(f">{nid}", svg)
        self.assertIn("K2", svg)
        self.assertIn("끊김", svg)
        self.assertIn("[확인 필요]", svg)
        self.assertNotIn("<script", svg)

    def test_init_and_check_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "program.yaml"
            self.assertEqual(_run(["init", "--out", str(p)]), 0)
            self.assertEqual(_run(["init", "--out", str(p)]), 1)  # 덮어쓰기 거부
            rc = _run(["check", str(p), "--out", td, "--quiet"])
            res = json.loads((Path(td) / "check.json").read_text(encoding="utf-8"))
            self.assertIn(res["status"], ("FAIL", "WARN"))  # 빈 서식은 통과하지 않는다
            self.assertIn(rc, (0, 3))

    def test_wrap_korean(self):
        lines = pl._wrap("가" * 40, 28)
        self.assertTrue(all(sum(2 for _ in ln) <= 28 for ln in lines))
        self.assertEqual("".join(lines), "가" * 40)
        self.assertEqual(pl._wrap("", 10), ["(비어 있음)"])


if __name__ == "__main__":
    unittest.main()
