import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import program_logic as pl


class TestDuplicateIDs(unittest.TestCase):
    def test_duplicate_goals_and_indicators_are_reported(self):
        text = """name: example
performance_goals:
  - {id: G1, text: first}
  - {id: G1, text: second}
indicators:
  - {id: K1, name: first}
  - {id: K1, name: second}
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "design.yaml"; p.write_text(text)
            d = pl.load_design(p)
            self.assertIn("성과목표 id 중복: G1", d.errors)
            self.assertIn("지표 id 중복: K1", d.errors)
            self.assertTrue(any(f.check == "C3" and f.level == pl.ERROR for f in pl.run_checks(d)))
