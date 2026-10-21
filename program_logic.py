#!/usr/bin/env python3
"""rnd-program-logic — 사업 논리모형·성과지표 설계 점검기

사업의 투입–활동–산출–결과 사슬과 성과지표·목표치를 설계서(YAML)에 적으면,
지표 적합성·끊긴 고리·목표치 근거 유무를 기계 점검해
점검표 + 지표표 + 논리모형 그림(SVG) + 「지어내지 않은 것」 절을 낸다.

  python3 program_logic.py init --out program.yaml
  python3 program_logic.py check program.yaml --out out     # → out/check.json
  python3 program_logic.py render program.yaml --out out    # → out/logic_model.svg/.html, figure_spec.json
  python3 program_logic.py report program.yaml --out out    # → out/report.md (+ check·render)
  python3 program_logic.py run program.yaml --out out
  python3 program_logic.py evidence                         # 점검 항목이 따르는 지침·조문과 확인 상태
  python3 program_logic.py selftest

표준 라이브러리만 쓴다. PyYAML이 있으면 그것으로 읽고, 없으면 내장 소형 파서를 쓴다.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.1.1"

# ---------------------------------------------------------------------------
# 0. YAML (policy-did 와 같은 부분집합 파서)
# ---------------------------------------------------------------------------


def load_yaml(text: str):
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ImportError:
        return _MiniYaml(text).parse()


class _MiniYaml:
    """매핑·목록·스칼라·따옴표·주석·인라인 [a, b]·{k: v}. 앵커·다중행 블록은 없음."""

    def __init__(self, text: str):
        self.lines = []
        for raw in text.splitlines():
            s = _strip_comment(raw).rstrip()
            if s.strip() == "" or s.strip() == "---":
                continue
            indent = len(s) - len(s.lstrip(" "))
            self.lines.append((indent, s.strip()))
        self.i = 0

    def parse(self):
        if not self.lines:
            return {}
        return self._block(self.lines[0][0])

    def _block(self, indent):
        if self.i >= len(self.lines):
            return None
        if self.lines[self.i][1].startswith("- "):
            return self._list(indent)
        return self._map(indent)

    def _map(self, indent):
        out = {}
        while self.i < len(self.lines):
            ind, s = self.lines[self.i]
            if ind < indent:
                break
            if ind > indent:
                raise ValueError(f"YAML 들여쓰기 오류: {s!r}")
            if s.startswith("- "):
                break
            key, val = _split_kv(s)
            self.i += 1
            if val == "":
                if self.i < len(self.lines) and self.lines[self.i][0] > indent:
                    out[key] = self._block(self.lines[self.i][0])
                elif self.i < len(self.lines) and self.lines[self.i][0] == indent and self.lines[self.i][1].startswith("- "):
                    out[key] = self._list(indent)
                else:
                    out[key] = None
            else:
                out[key] = _scalar(val)
        return out

    def _list(self, indent):
        out = []
        while self.i < len(self.lines):
            ind, s = self.lines[self.i]
            if ind < indent or not s.startswith("- "):
                break
            if ind > indent:
                raise ValueError(f"YAML 들여쓰기 오류: {s!r}")
            body = s[2:].strip()
            self.i += 1
            if body == "":
                out.append(self._block(self.lines[self.i][0]) if self.i < len(self.lines) else None)
            elif _looks_kv(body):
                sub_indent = indent + 2
                self.lines.insert(self.i, (sub_indent, body))
                out.append(self._map(sub_indent))
            else:
                out.append(_scalar(body))
        return out


def _strip_comment(s: str) -> str:
    inq = None
    for k, ch in enumerate(s):
        if inq:
            if ch == inq:
                inq = None
        elif ch in "\"'":
            inq = ch
        elif ch == "#" and (k == 0 or s[k - 1] in " \t"):
            return s[:k]
    return s


def _looks_kv(s: str) -> bool:
    if s.startswith(("[", "{", "\"", "'")):
        return False
    return bool(re.match(r"^[^:]+?:(\s|$)", s))


def _split_kv(s: str):
    m = re.match(r"^(.+?):(?:\s+(.*))?$", s)
    if not m:
        raise ValueError(f"YAML 'key: value' 형식이 아님: {s!r}")
    key = m.group(1).strip().strip("\"'")
    if re.fullmatch(r"[-+]?\d+", key):   # 연도 같은 정수 키는 PyYAML 처럼 int 로
        key = int(key)
    return key, (m.group(2) or "").strip()


def _scalar(v: str):
    if v == "":
        return None
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [] if inner == "" else [_scalar(x.strip()) for x in _split_inline(inner)]
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        out = {}
        for part in _split_inline(inner):
            if part.strip():
                k, val = _split_kv(part.strip())
                out[k] = _scalar(val)
        return out
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", "none"):
        return None
    if re.fullmatch(r"[-+]?\d+", v):
        return int(v)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", v):
        return float(v)
    return v


def _split_inline(s: str):
    out, cur, depth, inq = [], "", 0, None
    for ch in s:
        if inq:
            cur += ch
            if ch == inq:
                inq = None
        elif ch in "\"'":
            inq = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


# ---------------------------------------------------------------------------
# 1. 근거 대장 — 점검 항목마다 어느 지침의 어느 항목을 따르는지
#    status: "확인" = 원문을 직접 읽고 대조한 날짜가 있음 / "확인 필요" = 원문 미확보(지어내지 않음)
# ---------------------------------------------------------------------------

EVIDENCE = {
    "LAW6": {
        "label": "「국가연구개발사업 등의 성과평가 및 성과관리에 관한 법률」 제6조 ①·②",
        "text": "사업 전략계획에 전략목표, 전략목표를 달성하기 위한 연차별·단계별 성과목표 및 성과지표, 평가계획이 들어가야 한다",
        "status": "확인", "checked": "2026-10-20", "how": "국가법령정보(법령ID 010090, 시행 2023-10-31) 조문 대조",
    },
    "LAW3": {
        "label": "같은 법 제3조 ①·⑤",
        "text": "평가는 성과 중심(①), 질적 성과지표에 가중치(⑤)",
        "status": "확인", "checked": "2026-10-20", "how": "국가법령정보 조문 대조",
    },
    "LAW12": {
        "label": "같은 법 제12조 ④",
        "text": "표준 성과지표에는 질적 성과지표가 포함되어야 한다",
        "status": "확인", "checked": "2026-10-20", "how": "국가법령정보 조문 대조",
    },
    "NFA85": {
        "label": "「국가재정법」 제85조의2 ①1",
        "text": "성과목표관리 = 성과목표·성과지표 등의 설정 및 그 달성을 위한 집행과정·결과의 관리",
        "status": "확인", "checked": "2026-10-20", "how": "국가법령정보(시행 2026-09-11) 조문 대조",
    },
    "G-III1": {
        "label": "과기정통부 「국가연구개발사업 성과목표·지표 설정 안내서」(6차) Ⅲ.1 사업 분석(논리모형) p.8~10",
        "text": "투입⟶과정⟶산출⟶결과의 인과관계를 전제로 구성요소 간 연계성을 고려; 활동별로 하나 이상의 산출; 단기 3년 이내·중기 3~5년·장기 6년 이후; 주변 여건(외부 환경)을 포함; '영향'은 효과성 분석의 대상",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조(목차 쪽수 기준)",
    },
    "G-III2": {
        "label": "같은 안내서 Ⅲ.2 R&D 사업 유형 결정 p.11",
        "text": "10개 사업유형(기초연구·단기산업·중장기산업·공공기술·지역·국방·인력양성·시설장비·성과확산·국제협력); 사업 분석을 거쳐 부처가 정하고 전략계획서 점검에서 확정",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V3-1": {
        "label": "같은 안내서 Ⅴ.3 성과지표 설정 주안점 ① p.33",
        "text": "성과목표와 연계·부합; 내역사업이 둘 이상이면 사업별 성과를 대표할 지표; 지나치게 일반화된 지표 지양",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V3-2": {
        "label": "같은 안내서 Ⅴ.3 ② p.34~36",
        "text": "사업유형별 핵심성과(초기/중기/장기); 기초연구 아닌 유형에서 논문 지표 가중치 과다 지양; 성과목표별 지표 2개 이상",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V3-3": {
        "label": "같은 안내서 Ⅴ.3 ③ p.37",
        "text": "계속사업은 산출단계와 결과단계 지표를 병행; 기한사업은 사전 계획된 지표를 진척에 따라 단계적으로",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V3-4": {
        "label": "같은 안내서 Ⅴ.3 ④ p.38",
        "text": "원칙적으로 질적 지표; 예산만 투입하면 달성되는 투입·과정지표 지양; 논문·특허·보고서 단순 건수 지양; 과반을 질적 지표로 권장",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V4-1": {
        "label": "같은 안내서 Ⅴ.4 측정방법 ① p.39",
        "text": "측정산식이 지표명·지표 개념에 부합하지 않는 경우 지양",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V4-2": {
        "label": "같은 안내서 Ⅴ.4 ② p.39",
        "text": "산식 세부항목이 투입·과정지표(위원회 구성·운영 건수 등)로 구성되면 적절한 성과지표로 볼 수 없음",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V4-3": {
        "label": "같은 안내서 Ⅴ.4 ③ p.39~40",
        "text": "객관적 측정; 지원받지 않은 대상까지 포함하는 산식 부적절; 수출액·수입대체 등은 외부요인을 제외한 순효과로 측정; 사업화 매출은 기여율 반영",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조(보완 사례 ③ 포함)",
    },
    "G-V4-4": {
        "label": "같은 안내서 Ⅴ.4 ④ 및 보완 사례 ④ p.41",
        "text": "정성 지표도 수치·등급으로 객관화; 서로 다른 성격의 지표를 단순 합한 복합지표 지양",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V5-1": {
        "label": "같은 안내서 Ⅴ.5 목표치 ① p.42",
        "text": "설정 근거(세계·국내 최고 수준, 현재 역량, 예산 등)를 반드시 제시; 과거 실적은 baseline으로만, 기계적 점증형 목표치는 주의",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V5-2": {
        "label": "같은 안내서 Ⅴ.5 ② p.42",
        "text": "도전적이되 달성 불가능한 목표치 지양; 사례·전문가 판단 등 근거 정보를 반드시 제시",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V5-3": {
        "label": "같은 안내서 Ⅴ.5 ③ p.42~43",
        "text": "적절성 6문답: 준거 기준(baseline)·현재 수준·경향치·예측 가능성·유사기관 목표치·조직 역량",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-V6": {
        "label": "같은 안내서 Ⅴ.6 성과지표의 수정 p.43",
        "text": "낮은 실적으로 인한 목표치 변경은 불가",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "G-APP3": {
        "label": "같은 안내서 부록3 설정 과정 예시 ④ 결과지표 도출 p.99~",
        "text": "결과지표는 산출과의 논리적 연관성 확인이 중요; 사업 효과보다 외부요인 효과가 더 크지 않아야; SMART 점검(명확성·측정가능성·원인성·신뢰성·적시성)",
        "status": "확인", "checked": "2026-10-20", "how": "안내서 추출본 원문 대조",
    },
    "PLAN5": {
        "label": "「제5차 국가연구개발 성과평가 기본계획(2026~2030)」(국가과학기술자문회의 심의회의 2025-10-30 의안 제1호 별지)",
        "text": "사업평가는 전략계획서(전략목표·성과목표·지표·평가계획)에 따른 목표달성도·성과우수성; R&D예산요구서 성과지표에 전략계획서 지표를 활용; 종료 후 효과성 분석",
        "status": "확인", "checked": "2026-10-20", "how": "의안 원문 추출본 대조(Ⅰ.1 사업평가, 전략 2 기획·추진·환류·종료)",
    },
    "KISTEP-NANO": {
        "label": "KISTEP 「나노융합2020사업」 특정평가 보고서(2019-10, 19-3) 제2장·제4장",
        "text": "평가이슈 ①사업기획 시 설정한 방향·내용의 반영과 변경의 적절성 ②성과목표·지표 달성도와 효율성·효과성 ③추진체계; 권고: 매출 지표는 동 사업의 직접적 수혜금액 반영, 객관적 성과지표로 개선, 목표치 설정에 쓴 과거 실적치의 타당성",
        "status": "확인", "checked": "2026-10-20", "how": "보고서 PDF 원문 대조(요약 ix, 제2장 p.17~22, 제3장 <표 3-10>, 제4장). 사업 1건의 평가 틀이지 특정평가 일반 지침이 아님",
    },
    "KISTEP-GEN": {
        "label": "KISTEP/과기정통부 특정평가 일반 지침·지표 점검 항목(「(가칭)국가연구개발 특정평가 세부 운영규정」 등)",
        "text": "제5차 기본계획이 '마련' 예정으로 적은 규정. 공개 원문을 확보하지 못함",
        "status": "확인 필요", "checked": None, "how": "확보되면 절·쪽을 적고 해당 점검 항목의 근거를 승격",
    },
    "FISCAL-SELF": {
        "label": "기획재정부 「재정사업 자율평가 지침」(연도별) 평가항목·지표",
        "text": "2023년 개편 공통평가 항목(사업계획 적정성·집행 효율성·성과달성도·환류)은 보도(뉴시스 2023-01-02)로만 확인. 세부 질문·배점 원문 미확보. 2026년부터 부처 자체평가는 폐지되고 통합 재정사업 성과평가로 바뀜(기획예산처 2026-01-27 국무회의 보고, 보도 기준) — 통합평가 세부 지표도 미확보",
        "status": "확인 필요", "checked": None, "how": "2차 자료(보도)뿐. 원문 확보 전까지 이 근거를 점검 항목의 1차 근거로 쓰지 않음",
    },
    "FISCAL-PLAN": {
        "label": "기획재정부 「재정사업 성과관리 기본계획(2022~2026)」",
        "text": "국가재정법 제85조의2에 따른 5년 기본계획. 원문 미확보",
        "status": "확인 필요", "checked": None, "how": "원문 확보 전까지 법 조문(NFA85)만 근거로 씀",
    },
}

# 점검 항목 정의: id → (제목, 근거 id 목록)
CHECKS = {
    "C1": ("전략목표·성과목표가 설계서에 있는가", ["LAW6", "PLAN5"]),
    "C2": ("사슬 다섯 칸(투입·활동·산출·결과 단기·결과 장기)이 비어 있지 않은가", ["G-III1", "NFA85"]),
    "C3": ("참조 ID가 실재하는가(uses/from/goal/measures)", ["G-III1"]),
    "C4": ("산출 없는 활동 — 활동이 어떤 산출로도 이어지지 않음", ["G-III1"]),
    "C5": ("결과 없는 산출 — 산출이 어떤 결과로도 이어지지 않음", ["G-III1", "G-APP3"]),
    "C6": ("전략목표 미연결 — 장기 결과가 성과목표(goal)에 닿지 않음 / 성과목표에 닿는 결과가 없음", ["LAW6", "G-V3-1"]),
    "C7": ("고아 노드 — 어느 상류에서도 오지 않는 산출·결과", ["G-III1"]),
    "C8": ("연결의 '그래서' 문장(because) — 산출→결과·결과→전략목표 연결에 논리 문장이 있는가", ["G-III1", "G-APP3"]),
    "C9": ("투입이 결과로 둔갑 — 결과 칸에 예산·과제 수·참여기관 수가 적혀 있음", ["G-V3-4", "LAW3"]),
    "C10": ("내역사업 분기 — 내역사업이 둘 이상인데 성과목표·지표가 내역을 구분하지 않음", ["G-V3-1"]),
    "C11": ("사업유형·수명 주기가 적혀 있는가(유형별 기대 성과 판단의 전제)", ["G-III2", "G-V3-2"]),
    "C12": ("주변 여건(외부 환경·동시 추진 사업)이 적혀 있는가", ["G-III1"]),
    "I1": ("지표가 사슬의 어느 노드를 재는지(measures) 밝히고, 단계 표기가 그 노드와 맞는가", ["G-V3-1", "G-V4-1"]),
    "I2": ("투입·과정 지표", ["G-V3-4"]),
    "I3": ("성과목표별 지표 2개 이상", ["G-V3-2"]),
    "I4": ("질적 지표 과반", ["G-V3-4", "LAW3", "LAW12"]),
    "I5": ("단순 건수 지표(논문·특허·보고서·참여 인원 수)", ["G-V3-4"]),
    "I6": ("결과 단계 지표의 유무(계속사업은 산출·결과 병행, 기한사업은 단계별)", ["G-V3-3"]),
    "I7": ("산식이 있는가 / 산식에 과정 항목(위원회·회의·운영 건수)이 섞였는가", ["G-V4-1", "G-V4-2"]),
    "I8": ("외부요인·직접 수혜 — 매출·수출·생산액 지표에 기여율·순효과 처리가 있는가", ["G-V4-3", "KISTEP-NANO"]),
    "I9": ("복합지표 — 성격이 다른 항목의 단순 합", ["G-V4-4"]),
    "I10": ("기초연구 아닌 유형의 논문 지표", ["G-V3-2"]),
    "T1": ("연차별·단계별 목표치가 있는가", ["LAW6", "G-V5-1"]),
    "T2": ("목표치 설정 근거(target_basis)가 있는가", ["G-V5-1", "G-V5-2"]),
    "T3": ("baseline(준거 기준)이 있는가", ["G-V5-3"]),
    "T4": ("기계적 점증형 목표치(등차·등비, '전년 실적 대비 n% 상향'식 근거)", ["G-V5-1", "KISTEP-NANO"]),
    "T5": ("낮은 실적을 이유로 목표치를 내린 이력", ["G-V6"]),
    "T6": ("목표치 근거의 출처(target_source)", ["G-V5-2"]),
}

# 판정 등급
ERROR, BROKEN, FAIL, WARN, UNVERIFIED, PASS, NA = "오류", "끊김", "부적정", "보완", "확인 필요", "적정", "해당 없음"
_ORDER = {ERROR: 0, BROKEN: 1, FAIL: 2, WARN: 3, UNVERIFIED: 4, PASS: 5, NA: 6}


@dataclass
class Finding:
    check: str
    level: str
    where: str
    message: str
    fix: str = ""

    def to_dict(self):
        title, ev = CHECKS[self.check]
        return {
            "check": self.check, "title": title, "level": self.level, "where": self.where,
            "message": self.message, "fix": self.fix,
            "evidence": [{"id": e, "label": EVIDENCE[e]["label"], "status": EVIDENCE[e]["status"]} for e in ev],
        }


# ---------------------------------------------------------------------------
# 2. 설계서
# ---------------------------------------------------------------------------

DESIGN_TEMPLATE = """# rnd-program-logic 설계서 — 사업이 돈을 성과로 바꾼다고 말하는 길을 칸마다 적는다.
# 여기 적지 않은 산출·결과·목표치는 보고서에 나오지 않는다. 모르는 값은 null 로 두면 [확인 필요]로 찍힌다.
name: 예시_사업명
agency: 소관 부처
period:
  start: {y0}
  end: {y1}
  type: 기한                 # 기한 | 계속
budget_total:
  value: null               # 숫자만. 문서에 없으면 null
  unit: 억원
  source: ""                # 문서명·쪽
program_type: null          # 안내서 Ⅲ.2 10유형: 기초연구 | 단기산업기술개발 | 중장기산업기술개발 | 공공기술개발 | 지역연구개발 | 국방기술개발 | 인력양성 | 시설장비구축 | 성과확산 | 국제협력
program_type_basis: ""      # 문서에 명시가 없고 추정이면 "[추정] 근거 문장"
lifecycle: null             # 초기(3년 이내) | 중기(3~5년) | 장기(6년 이상) — 안내서 Ⅲ.1

strategic_goal:
  text: ""                  # 전략목표 원문
  source: ""
performance_goals:          # 성과목표 — 전략목표를 달성하기 위한 연차별·단계별 목표(법 제6조②3)
  - id: G1
    text: ""
    source: ""

sub_programs: []            # 내역사업 이름. 둘 이상이면 지표·활동에 sub_program 을 적는다

chain:
  inputs:
    - id: I1
      text: ""              # 자금·인력·기반·축적 기술 등
      source: ""
  activities:
    - id: A1
      text: ""
      uses: [I1]            # 어떤 투입을 쓰는가
      sub_program: null
      source: ""
  outputs:
    - id: O1
      text: ""              # 활동의 직접적·즉각적 결과물
      from: [A1]
      source: ""
  outcomes_short:           # 단기 결과(3년 이내) — 산출이 누구에게 무엇을 바꾸는가
    - id: S1
      text: ""
      from: [O1]
      because: ""           # "O1이면 S1" 이라고 문서가 말하는 문장(원문). 없으면 비워 둔다 → 끊김 후보
      source: ""
  outcomes_long:            # 장기 결과(6년 이후)·전략목표에 닿는 변화
    - id: L1
      text: ""
      from: [S1]
      goal: G1              # 어느 성과목표에 닿는가
      because: ""
      source: ""

indicators:
  - id: K1
    name: ""
    stage: 산출              # 투입 | 과정 | 산출 | 결과
    measures: O1            # 사슬의 어느 노드를 재는가
    goal: G1
    kind: 질적               # 질적 | 양적
    formula: ""             # 측정산식 원문
    unit: ""
    data_source: ""
    baseline:
      year: null
      value: null
      source: ""
    targets:                # 연차별 목표치. 없으면 비워 둔다
      {y0}: null
    target_basis: ""        # 목표치 설정 근거(세계·국내 최고 수준, 역량, 예산, 로드맵…). 없으면 [확인 필요]
    target_source: ""
    external_factors: ""    # 환율·시장 등 외부요인과 그 처리(기여율·순효과)
    target_lowered_for_low_performance: false   # 낮은 실적 때문에 목표치를 내린 이력이 있으면 true
    weight: null

context:
  external_conditions: ""  # 사업 바깥의 중요한 여건(시장·규제·기술 추세)
  concurrent_programs: ""  # 같은 대상에 겹치는 다른 사업

sources:                    # 설계서에 쓴 문서 목록
  - id: D1
    title: ""
    date: ""
notes: ""
"""


@dataclass
class Node:
    id: str
    stage: str  # 투입/활동/산출/결과(단기)/결과(장기)
    text: str
    upstream: list = field(default_factory=list)
    goal: str | None = None
    because: str = ""
    source: str = ""
    sub_program: str | None = None


@dataclass
class Indicator:
    id: str
    name: str
    stage: str
    measures: str | None
    goal: str | None
    kind: str
    formula: str
    unit: str
    data_source: str
    baseline: dict
    targets: dict
    target_basis: str
    target_source: str
    external_factors: str
    lowered: bool
    weight: object
    sub_program: str | None = None


@dataclass
class Design:
    raw: dict
    name: str
    agency: str
    period: dict
    budget: dict
    program_type: str | None
    program_type_basis: str
    lifecycle: str | None
    strategic_goal: dict
    goals: list
    sub_programs: list
    nodes: dict  # id → Node
    indicators: list
    context: dict
    sources: list
    errors: list


STAGES = ["투입", "활동", "산출", "결과(단기)", "결과(장기)"]
_STAGE_KEYS = [("inputs", "투입", "uses"), ("activities", "활동", "uses"), ("outputs", "산출", "from"),
               ("outcomes_short", "결과(단기)", "from"), ("outcomes_long", "결과(장기)", "from")]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _lst(v) -> list:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [x for x in v if x is not None]
    return [v]


def load_design(path: Path) -> Design:
    raw = load_yaml(path.read_text(encoding="utf-8")) or {}
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ValueError("설계서 최상위는 매핑이어야 한다")
    chain = raw.get("chain") or {}
    nodes: dict[str, Node] = {}
    for key, stage, upkey in _STAGE_KEYS:
        items = chain.get(key) or []
        if not isinstance(items, list):
            errors.append(f"chain.{key} 는 목록이어야 한다")
            continue
        for k, it in enumerate(items):
            if not isinstance(it, dict):
                errors.append(f"chain.{key}[{k}] 는 매핑이어야 한다")
                continue
            nid = _s(it.get("id")) or f"{key[:1].upper()}{k + 1}"
            if nid in nodes:
                errors.append(f"노드 id 중복: {nid}")
            up = [] if stage == "투입" else [_s(x) for x in _lst(it.get(upkey))]
            nodes[nid] = Node(nid, stage, _s(it.get("text")), up, _s(it.get("goal")) or None,
                              _s(it.get("because")), _s(it.get("source")), _s(it.get("sub_program")) or None)
    goals = []
    for k, g in enumerate(raw.get("performance_goals") or []):
        if isinstance(g, dict):
            goals.append({"id": _s(g.get("id")) or f"G{k + 1}", "text": _s(g.get("text")), "source": _s(g.get("source")),
                          "sub_program": _s(g.get("sub_program")) or None})
        else:
            goals.append({"id": f"G{k + 1}", "text": _s(g), "source": "", "sub_program": None})
    inds = []
    for k, it in enumerate(raw.get("indicators") or []):
        if not isinstance(it, dict):
            errors.append(f"indicators[{k}] 는 매핑이어야 한다")
            continue
        bl = it.get("baseline") if isinstance(it.get("baseline"), dict) else {"value": it.get("baseline")}
        tg = it.get("targets") if isinstance(it.get("targets"), dict) else {}
        inds.append(Indicator(
            _s(it.get("id")) or f"K{k + 1}", _s(it.get("name")), _s(it.get("stage")), _s(it.get("measures")) or None,
            _s(it.get("goal")) or None, _s(it.get("kind")), _s(it.get("formula")), _s(it.get("unit")),
            _s(it.get("data_source")), bl or {}, {str(y): v for y, v in tg.items()},
            _s(it.get("target_basis")), _s(it.get("target_source")), _s(it.get("external_factors")),
            bool(it.get("target_lowered_for_low_performance")), it.get("weight"), _s(it.get("sub_program")) or None))
    for label, ids in (("성과목표", [g["id"] for g in goals]), ("지표", [i.id for i in inds])):
        seen_ids = set()
        for ident in ids:
            if ident in seen_ids:
                errors.append(f"{label} id 중복: {ident}")
            seen_ids.add(ident)
    sg = raw.get("strategic_goal")
    if not isinstance(sg, dict):
        sg = {"text": _s(sg), "source": ""}
    budget = raw.get("budget_total") if isinstance(raw.get("budget_total"), dict) else {"value": raw.get("budget_total")}
    return Design(raw, _s(raw.get("name")), _s(raw.get("agency")), raw.get("period") or {}, budget or {},
                  _s(raw.get("program_type")) or None, _s(raw.get("program_type_basis")), _s(raw.get("lifecycle")) or None,
                  sg, goals, [_s(x) for x in _lst(raw.get("sub_programs"))], nodes, inds,
                  raw.get("context") or {}, raw.get("sources") or [], errors)


# ---------------------------------------------------------------------------
# 3. 점검
# ---------------------------------------------------------------------------

_INPUT_AS_OUTCOME = re.compile(r"(예산|사업비|투입|과제\s*수|과제수|참여\s*기관|참여기관|지원\s*건수|지원기업\s*수|선정\s*과제)")
_SIMPLE_COUNT = re.compile(r"(논문|특허|보고서|참여\s*인원|참여인원|교육\s*인원|과제)\s*(건수|편수|수|건|편)$|(건수|편수)$")
_QUALITY_HINT = re.compile(r"(피인용|IF|영향력|SMART|등급|mrnIF|기술료|사업화\s*성공|매출|고용|활용도|만족도|순증|점유율|재현|검증\s*통과|진입|비율|률|%)")
_PROCESS_ITEM = re.compile(r"(위원회\s*(구성|운영)|회의\s*(개최|건수)|운영\s*건수|홍보\s*건수|설명회)")
_ACTIVITY_COUNT = re.compile(r"(컨설팅|지원)\s*건수")
_EXTERNAL_MONEY = re.compile(r"(매출|수출|생산액|수입대체|시장\s*규모)")
_NET_EFFECT = re.compile(r"(기여율|직접\s*수혜|순효과|순증|외부요인)")
_INCREMENTAL_BASIS = re.compile(r"(전년|전년도|직전|과거\s*실적|추세)[^。\n]{0,20}(상향|증가율|점증|적용|감안|대비)")
_PAPER = re.compile(r"논문")
_STAGE_OF_NODE = {"투입": "투입", "활동": "과정", "산출": "산출", "결과(단기)": "결과", "결과(장기)": "결과"}


def _targets_numeric(tg: dict) -> list[tuple[str, float]]:
    out = []
    for y, v in tg.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((str(y), float(v)))
    out.sort()
    return out


def _is_mechanical(vals: list[float]) -> str | None:
    if len(vals) < 3:
        return None
    diffs = [b - a for a, b in zip(vals, vals[1:])]
    if all(abs(d - diffs[0]) <= 1e-9 + 0.01 * abs(diffs[0]) for d in diffs) and diffs[0] != 0:
        return f"등차(+{diffs[0]:g}/년)"
    if all(v > 0 for v in vals):
        ratios = [b / a for a, b in zip(vals, vals[1:])]
        if all(abs(r - ratios[0]) <= 0.01 for r in ratios) and abs(ratios[0] - 1) > 1e-9:
            return f"등비(×{ratios[0]:.3g}/년)"
    return None


def run_checks(d: Design) -> list[Finding]:
    F: list[Finding] = []
    for e in d.errors:
        F.append(Finding("C3", ERROR, "설계서", e, "설계서 서식을 고친다"))
    nodes = d.nodes
    goal_ids = {g["id"] for g in d.goals}

    # C1 전략목표·성과목표
    if not _s(d.strategic_goal.get("text")):
        F.append(Finding("C1", UNVERIFIED, "strategic_goal", "전략목표 문장이 비어 있다", "문서의 전략목표 원문을 옮기고 출처를 적는다. 문서에 없으면 그대로 비워 두고 [확인 필요]로 남긴다"))
    else:
        F.append(Finding("C1", PASS, "strategic_goal", "전략목표 있음"))
    empty_goals = [g["id"] for g in d.goals if not g["text"]]
    if not d.goals:
        F.append(Finding("C1", BROKEN, "performance_goals", "성과목표가 하나도 없다", "전략목표를 달성하기 위한 연차별·단계별 성과목표를 적는다(법 제6조②3)"))
    elif empty_goals:
        F.append(Finding("C1", UNVERIFIED, ",".join(empty_goals), "본문이 빈 성과목표", "원문을 옮기거나 항목을 지운다"))
    else:
        F.append(Finding("C1", PASS, "performance_goals", f"성과목표 {len(d.goals)}개"))

    # C2 다섯 칸
    for _, stage, _ in _STAGE_KEYS:
        have = [n for n in nodes.values() if n.stage == stage and n.text]
        if not have:
            F.append(Finding("C2", BROKEN, stage, f"'{stage}' 칸이 비어 있다", "문서에서 해당 칸의 문장을 찾아 옮긴다. 문서에 없으면 그것이 발견이다 — 비워 두고 끊김으로 보고한다"))
    if not any(f.check == "C2" for f in F):
        F.append(Finding("C2", PASS, "chain", "다섯 칸 모두 채워짐"))

    # C3 참조
    bad = False
    for n in nodes.values():
        for u in n.upstream:
            if u not in nodes:
                bad = True
                F.append(Finding("C3", ERROR, n.id, f"상류 참조 '{u}' 가 없다", "id 를 맞춘다"))
        if n.goal and n.goal not in goal_ids:
            bad = True
            F.append(Finding("C3", ERROR, n.id, f"goal '{n.goal}' 이 performance_goals 에 없다", "id 를 맞춘다"))
    for k in d.indicators:
        if k.measures and k.measures not in nodes:
            bad = True
            F.append(Finding("C3", ERROR, k.id, f"measures '{k.measures}' 노드가 없다", "사슬 노드 id 를 맞춘다"))
        if k.goal and k.goal not in goal_ids:
            bad = True
            F.append(Finding("C3", ERROR, k.id, f"goal '{k.goal}' 이 performance_goals 에 없다", "id 를 맞춘다"))
    if not bad and not d.errors:
        F.append(Finding("C3", PASS, "ids", "참조 무결"))

    # 하류 지도
    down: dict[str, list[str]] = {i: [] for i in nodes}
    for n in nodes.values():
        for u in n.upstream:
            if u in down:
                down[u].append(n.id)

    def _down_stage(nid, stage):
        return [x for x in down.get(nid, []) if nodes[x].stage == stage]

    # C4 산출 없는 활동
    for n in nodes.values():
        if n.stage == "활동" and not _down_stage(n.id, "산출"):
            F.append(Finding("C4", BROKEN, n.id, f"활동 '{n.text[:30]}' 에서 나오는 산출이 없다(산출 없는 활동)", "이 활동이 무엇을 내놓는지 문서에서 찾아 outputs 에 적고 from 으로 잇는다. 문서에 없으면 끊김으로 둔다"))
    # C5 결과 없는 산출
    for n in nodes.values():
        if n.stage == "산출" and not (_down_stage(n.id, "결과(단기)") or _down_stage(n.id, "결과(장기)")):
            F.append(Finding("C5", BROKEN, n.id, f"산출 '{n.text[:30]}' 이 어떤 결과로도 이어지지 않는다(결과 없는 산출)", "이 산출이 누구에게 무엇을 바꾸는지(단기 결과)를 적고 from 으로 잇는다"))
    # C6 전략목표 미연결
    for n in nodes.values():
        if n.stage == "결과(장기)" and not n.goal:
            F.append(Finding("C6", BROKEN, n.id, f"장기 결과 '{n.text[:30]}' 가 어느 성과목표에도 닿지 않는다(전략목표 미연결)", "goal 에 성과목표 id 를 적는다. 어느 목표에도 안 닿으면 그 결과를 왜 추구하는지가 문서에 없는 것"))
        if n.stage == "결과(단기)" and not _down_stage(n.id, "결과(장기)") and not n.goal:
            F.append(Finding("C6", WARN, n.id, f"단기 결과 '{n.text[:30]}' 가 장기 결과·성과목표로 이어지지 않는다", "from 으로 잇거나 goal 을 적는다"))
    reached = {n.goal for n in nodes.values() if n.goal}
    for g in d.goals:
        if g["id"] not in reached:
            F.append(Finding("C6", BROKEN, g["id"], f"성과목표 '{g['text'][:30]}' 에 닿는 결과가 사슬에 없다", "이 목표를 이루는 결과 노드를 적거나, 목표가 사슬과 무관하면 그 사실을 보고한다"))
    # C7 고아
    for n in nodes.values():
        if n.stage in ("산출", "결과(단기)", "결과(장기)") and not n.upstream:
            F.append(Finding("C7", BROKEN, n.id, f"{n.stage} '{n.text[:30]}' 의 상류(from)가 비어 있다(고아 노드)", "어느 활동·산출에서 오는지 적는다. 문서에 없으면 그 결과는 사업의 산출로 설명되지 않는 것"))
        if n.stage == "활동" and not n.upstream:
            F.append(Finding("C7", WARN, n.id, f"활동 '{n.text[:30]}' 이 쓰는 투입(uses)이 비어 있다", "어떤 자금·인력·기반을 쓰는지 적는다"))
    # C8 because
    for n in nodes.values():
        if n.stage in ("결과(단기)", "결과(장기)") and n.upstream and not n.because:
            F.append(Finding("C8", WARN, n.id, f"{n.stage} '{n.text[:30]}' 로 이어지는 '그래서' 문장(because)이 없다", "문서에서 'A이면 B'를 말하는 문장을 찾아 원문으로 옮긴다. 없으면 연결은 설계자의 가정이라는 뜻 — 보고서에 그렇게 적힌다"))
    # C9 투입이 결과로 둔갑
    for n in nodes.values():
        if n.stage in ("결과(단기)", "결과(장기)") and _INPUT_AS_OUTCOME.search(n.text):
            F.append(Finding("C9", FAIL, n.id, f"결과 칸에 투입·과정 성격의 문구가 있다: '{n.text[:40]}'", "예산·과제 수·참여기관 수는 투입/활동 칸으로 옮기고, 결과 칸에는 그것이 바꾼 상태를 적는다"))
    # C10 내역사업
    if len(d.sub_programs) >= 2:
        acts_tagged = sum(1 for n in nodes.values() if n.stage == "활동" and n.sub_program)
        ind_tagged = sum(1 for k in d.indicators if k.sub_program)
        goal_tagged = sum(1 for g in d.goals if g.get("sub_program"))
        if len(d.goals) <= 1 and ind_tagged == 0:
            F.append(Finding("C10", WARN, "sub_programs", f"내역사업 {len(d.sub_programs)}개인데 성과목표 {len(d.goals)}개·내역 구분된 지표 0개 — 어느 내역의 성과인지 알 수 없다", "내역별 성과목표 또는 내역 표시(sub_program)를 단 지표를 둔다(안내서 Ⅴ.3①: 원칙은 사업 분리)"))
        elif acts_tagged == 0:
            F.append(Finding("C10", WARN, "chain.activities", f"내역사업 {len(d.sub_programs)}개인데 활동에 sub_program 표시가 없다", "활동마다 어느 내역인지 적는다"))
        else:
            F.append(Finding("C10", PASS, "sub_programs", f"내역 {len(d.sub_programs)}개, 내역 표시 활동 {acts_tagged}·지표 {ind_tagged}·목표 {goal_tagged}"))
    # C11 유형·수명
    if not d.program_type:
        F.append(Finding("C11", UNVERIFIED, "program_type", "사업유형이 없다 — 유형별 기대 성과·논문 지표 판단(I10)을 할 수 없다", "안내서 Ⅲ.2 10유형 중 하나를 적는다. 문서에 명시가 없으면 program_type_basis 에 '[추정] 근거 문장'"))
    elif d.program_type and not d.program_type_basis:
        F.append(Finding("C11", WARN, "program_type", f"사업유형 '{d.program_type}' 의 근거(문서 명시인지 추정인지)가 없다", "program_type_basis 에 문서 문장 또는 [추정] 표시"))
    else:
        F.append(Finding("C11", PASS, "program_type", f"사업유형 {d.program_type}"))
    if not d.lifecycle:
        F.append(Finding("C11", UNVERIFIED, "lifecycle", "수명 주기(초기/중기/장기)가 없다", "사업 개시 후 경과 연수로 적는다(초기 3년 이내·중기 3~5·장기 6년 이상)"))
    # C12 주변 여건
    if not _s(d.context.get("external_conditions")):
        F.append(Finding("C12", WARN, "context.external_conditions", "주변 여건(외부 환경)이 비어 있다 — 안내서는 이를 빼면 '불완전하고 부정확한 예측'이 된다고 적는다", "시장·규제·기술 추세 중 결과에 영향을 주는 것을 적는다"))
    else:
        F.append(Finding("C12", PASS, "context", "주변 여건 있음"))

    # ---- 지표 ----
    if not d.indicators:
        F.append(Finding("I1", BROKEN, "indicators", "성과지표가 하나도 없다", "성과목표마다 2개 이상의 지표를 적는다(법 제6조②3, 안내서 Ⅴ.3②)"))
    per_goal: dict[str, int] = {g["id"]: 0 for g in d.goals}
    quality = 0
    outcome_level = 0
    for k in d.indicators:
        if k.goal in per_goal:
            per_goal[k.goal] += 1
        # I1 measures·단계 일치
        if not k.measures:
            F.append(Finding("I1", WARN, k.id, f"지표 '{k.name}' 이 사슬의 어느 노드를 재는지(measures)가 없다", "재는 산출·결과 노드 id 를 적는다. 어느 노드도 재지 않으면 지표가 사슬 밖에 있는 것"))
        elif k.measures in nodes:
            want = _STAGE_OF_NODE[nodes[k.measures].stage]
            if k.stage and k.stage != want:
                F.append(Finding("I1", WARN, k.id, f"단계 표기 '{k.stage}' 가 재는 노드 {k.measures}({nodes[k.measures].stage})와 다르다", f"stage 를 '{want}' 로 고치거나 measures 를 바꾼다"))
        if not k.goal:
            F.append(Finding("I1", WARN, k.id, f"지표 '{k.name}' 이 어느 성과목표를 재는지(goal)가 없다", "goal 에 성과목표 id"))
        # I2 투입·과정
        if k.stage in ("투입", "과정"):
            F.append(Finding("I2", FAIL, k.id, f"'{k.name}' 은 {k.stage}지표 — 예산만 투입하면 달성되는 지표는 성과지표로 쓰지 않는다", "이 지표가 가리키는 산출·결과를 재는 지표로 바꾼다. 관리용으로 필요하면 성과지표 표 밖에 둔다"))
        # I4 질적 집계
        kind = k.kind
        if not kind:
            kind = "질적" if _QUALITY_HINT.search(k.name + " " + k.formula) else "양적"
            F.append(Finding("I4", UNVERIFIED, k.id, f"'{k.name}' 의 질적/양적 구분(kind)이 없어 이름·산식으로 '{kind}' 으로 보았다", "kind 를 적는다"))
        if kind == "질적":
            quality += 1
        if k.stage == "결과" or (k.measures in nodes and nodes[k.measures].stage.startswith("결과")):
            outcome_level += 1
        # I5 단순 건수
        if kind == "양적" and _SIMPLE_COUNT.search(k.name.replace(" ", "")) and not _QUALITY_HINT.search(k.name + k.formula):
            F.append(Finding("I5", WARN, k.id, f"'{k.name}' 은 단순 건수 지표로 읽힌다", "건수 대신 질(피인용·등급·활용·이전·매출 기여)을 재는 지표인지 확인한다. 안내서는 단순 건수 지표를 지양"))
        # I7 산식
        if not k.formula:
            F.append(Finding("I7", UNVERIFIED, k.id, f"'{k.name}' 의 측정산식이 없다", "산식 원문을 적는다. 문서에 없으면 [확인 필요]"))
        else:
            if _PROCESS_ITEM.search(k.formula):
                F.append(Finding("I7", FAIL, k.id, f"'{k.name}' 산식에 과정 항목이 섞여 있다: {k.formula[:60]}", "위원회·회의·운영 건수 같은 과정 항목을 산식에서 뺀다"))
            elif _ACTIVITY_COUNT.search(k.formula) and k.stage != "산출":
                F.append(Finding("I7", WARN, k.id, f"'{k.name}' 산식이 활동 건수(지원·컨설팅 건수)로 읽힌다", "산출인지 과정인지 확인하고, 결과를 재려면 그 지원이 바꾼 상태를 잰다"))
            # 이름–산식 어긋남의 간이 신호: 이름은 '활용도'인데 산식은 '만족도' 등
            pairs = [("활용도", "만족도"), ("성공", "우수"), ("개선효과", "부담비율")]
            for a, b in pairs:
                if a in k.name and b in k.formula and a not in k.formula:
                    F.append(Finding("I7", FAIL, k.id, f"'{k.name}' 의 이름({a})과 산식({b})이 다른 것을 잰다", "이름을 산식에 맞추거나 산식을 이름에 맞춘다(안내서 Ⅴ.4①)"))
        # I8 외부요인·직접 수혜
        if _EXTERNAL_MONEY.search(k.name + " " + k.formula):
            if not (_NET_EFFECT.search(k.formula) or _NET_EFFECT.search(k.external_factors)):
                F.append(Finding("I8", WARN, k.id, f"'{k.name}' 은 매출·수출·생산액 계열인데 기여율·직접 수혜·순효과 처리가 산식에도 external_factors 에도 없다", "사업의 직접적 수혜분만 세는 기여율 또는 순효과 산식을 적는다. 특정평가는 매출 지표에 '동 사업의 직접적인 수혜금액 반영'을 요구한 이력이 있다"))
        # I9 복합지표
        if (" + " in k.formula or "+" in k.formula) and ("및" in k.name or " + " in k.name):
            F.append(Finding("I9", WARN, k.id, f"'{k.name}' 은 성격이 다른 항목의 합으로 보인다", "각 항목을 개별 지표로 나눈다"))
        # I10 논문
        if _PAPER.search(k.name) and d.program_type and d.program_type != "기초연구":
            F.append(Finding("I10", WARN, k.id, f"기초연구가 아닌 유형({d.program_type})에 논문 지표 '{k.name}'", "가중치가 높지 않은지 확인한다"))
        # T1~T6
        nums = _targets_numeric(k.targets)
        if not k.targets or all(v is None for v in k.targets.values()):
            F.append(Finding("T1", UNVERIFIED, k.id, f"'{k.name}' 의 연차별 목표치가 없다", "문서의 목표치를 연도별로 적는다. 문서에 없으면 [확인 필요]로 남긴다 — 지어내지 않는다"))
        if not k.target_basis:
            F.append(Finding("T2", UNVERIFIED, k.id, f"'{k.name}' 의 목표치 설정 근거가 없다", "세계·국내 최고 수준, 역량, 예산, 로드맵 등 근거 문장을 적는다. 안내서는 근거 제시를 '반드시'로 적는다"))
        else:
            if _INCREMENTAL_BASIS.search(k.target_basis):
                F.append(Finding("T4", WARN, k.id, f"'{k.name}' 의 목표치 근거가 전년 실적·추세 대비 상향식이다: '{k.target_basis[:50]}'", "과거 실적은 baseline 으로만 쓰고, 도달해야 할 수준(최고 수준·로드맵)에서 목표치를 끌어온다"))
            if not k.target_source:
                F.append(Finding("T6", WARN, k.id, f"'{k.name}' 의 목표치 근거에 출처가 없다", "근거 문장의 문서·쪽을 적는다"))
        bl = k.baseline or {}
        if bl.get("value") is None:
            F.append(Finding("T3", UNVERIFIED, k.id, f"'{k.name}' 의 baseline 이 없다", "준거가 될 기준값과 연도·출처를 적는다(안내서 6문답의 첫째)"))
        mech = _is_mechanical([v for _, v in nums])
        if mech:
            F.append(Finding("T4", WARN, k.id, f"'{k.name}' 의 연차별 목표치가 {mech} 로 기계적 점증형이다: {', '.join(f'{y}={v:g}' for y, v in nums)}", "연도별 도달 근거(로드맵·단계 목표)를 적거나 목표치 유형(상승형·지속형·시한형)을 밝힌다"))
        if k.lowered:
            F.append(Finding("T5", FAIL, k.id, f"'{k.name}' 은 낮은 실적을 이유로 목표치를 내린 이력이 있다", "안내서 Ⅴ.6: 낮은 실적으로 인한 목표치 변경은 불가. 변경 사유를 재검토한다"))
    # I3 성과목표별 2개
    for gid, cnt in per_goal.items():
        if cnt < 2:
            F.append(Finding("I3", WARN, gid, f"성과목표 {gid} 의 지표가 {cnt}개(2개 이상 권장)", "목표 달성도를 읽을 수 있는 지표를 더 둔다"))
    if d.indicators:
        n = len(d.indicators)
        ratio = quality / n
        if ratio < 0.5:
            F.append(Finding("I4", WARN, "indicators", f"질적 지표 {quality}/{n}({ratio:.0%}) — 과반 권장에 못 미친다", "단순 건수 지표를 질을 재는 지표로 바꾼다"))
        else:
            F.append(Finding("I4", PASS, "indicators", f"질적 지표 {quality}/{n}({ratio:.0%})"))
        # I6 결과 지표
        ptype = _s(d.period.get("type"))
        if outcome_level == 0:
            F.append(Finding("I6", WARN, "indicators", "결과 단계를 재는 지표가 없다(산출 지표만)", "계속사업이면 산출·결과 지표 병행, 기한사업이면 단계별로 결과 지표를 둔다"))
        else:
            F.append(Finding("I6", PASS, "indicators", f"결과 단계 지표 {outcome_level}개" + (f" ({ptype}사업)" if ptype else "")))
    return F


def overall(findings: list[Finding]) -> str:
    levels = {f.level for f in findings}
    if ERROR in levels:
        return "ERROR"
    if BROKEN in levels or FAIL in levels:
        return "FAIL"
    if WARN in levels or UNVERIFIED in levels:
        return "WARN"
    return "PASS"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def check_to_dict(d: Design, design_path: Path, findings: list[Finding]) -> dict:
    counts = {}
    for f in findings:
        counts[f.level] = counts.get(f.level, 0) + 1
    unverified = [f for f in findings if f.level == UNVERIFIED]
    return {
        "tool": f"rnd-program-logic {__version__}",
        "design": str(design_path), "design_sha": _sha(design_path), "checked_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "program": d.name, "status": overall(findings), "counts": counts,
        "findings": [f.to_dict() for f in sorted(findings, key=lambda f: (_ORDER[f.level], f.check, f.where))],
        "unverified": [{"check": f.check, "where": f.where, "message": f.message} for f in unverified],
        "evidence": {k: {**v} for k, v in EVIDENCE.items()},
        "honesty": HONESTY,
    }


HONESTY = [
    "입력(설계서)에 없는 산출·결과·목표치·법령 조항을 메우지 않는다. 빈 칸은 [확인 필요]로 남는다.",
    "'끊김'은 설계서에 연결이 적혀 있지 않다는 뜻이지 사업에 논리가 없다는 판정이 아니다. 문서에 있는데 옮기지 않았을 수 있다.",
    "점검 항목마다 따르는 지침·조문을 적고, 원문을 확인하지 못한 근거는 '확인 필요'로 표시한다. 재정사업 자율평가 지침·재정사업 성과관리 기본계획·특정평가 일반 지침은 원문 미확보다.",
    "대체 지표·목표치 숫자를 제안하지 않는다. 수정 제안은 '무엇이 빠졌는가'까지다.",
    "기계 점검이 보는 것은 글자다. 이름·산식·근거의 뜻이 맞는지는 사람이 본다.",
]


def print_check(res: dict):
    print(f"[rnd-program-logic] {res['program']}  판정 {res['status']}  " + " ".join(f"{k} {v}" for k, v in res["counts"].items()))
    for f in res["findings"]:
        if f["level"] == PASS:
            continue
        print(f"  {f['level']:<5} {f['check']:<4} {f['where']:<14} {f['message']}")


# ---------------------------------------------------------------------------
# 4. 그림 — SVG 직접 생성(doc-figure 코드 렌더와 같은 방식: 글자는 코드가 그린다)
# ---------------------------------------------------------------------------

_SVG_CSS = """
.title{font:700 20px 'Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;fill:#1b2a4a}
.sub{font:13px sans-serif;fill:#5b6b85}
.hdr{font:700 14px sans-serif;fill:#fff}
.node{font:12px sans-serif;fill:#1f2937}
.nid{font:700 11px sans-serif;fill:#1b2a4a}
.chip{font:10px sans-serif;fill:#1b2a4a}
.goal{font:12px sans-serif;fill:#1b2a4a}
.cap{font:12px sans-serif;fill:#374151}
.foot{font:11px sans-serif;fill:#6b7280}
.badge{font:700 10px sans-serif;fill:#b91c1c}
"""


def _esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def _wrap(text: str, width_chars: int) -> list[str]:
    text = _s(text)
    if not text:
        return ["(비어 있음)"]
    out, cur = [], ""
    # 한글은 2칸, 그 밖은 1칸으로 어림
    def w(s):
        return sum(2 if ord(c) > 0x2E7F else 1 for c in s)
    for word in re.split(r"(\s+)", text):
        if not word:
            continue
        if w(cur + word) > width_chars and cur.strip():
            out.append(cur.rstrip())
            cur = word.lstrip()
        else:
            cur += word
        while w(cur) > width_chars:  # 띄어쓰기 없는 긴 조각
            cut = 0
            acc = 0
            for i, c in enumerate(cur):
                acc += 2 if ord(c) > 0x2E7F else 1
                if acc > width_chars:
                    cut = i
                    break
            out.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip():
        out.append(cur.rstrip())
    return out or [""]


def render_svg(d: Design, findings: list[Finding], title: str | None = None) -> str:
    broken_nodes = {f.where for f in findings if f.level == BROKEN and f.where in d.nodes}
    unverified_count = sum(1 for f in findings if f.level == UNVERIFIED)
    col_w, gap, left, top = 190, 34, 24, 96
    line_h, pad = 16, 8
    cols = {s: [n for n in d.nodes.values() if n.stage == s] for s in STAGES}
    ind_by_node: dict[str, list[str]] = {}
    for k in d.indicators:
        if k.measures:
            ind_by_node.setdefault(k.measures, []).append(k.id)
    # 노드 배치
    pos: dict[str, tuple[float, float, float, float]] = {}
    col_heights = []
    for ci, s in enumerate(STAGES):
        y = top + 36
        x = left + ci * (col_w + gap)
        for n in cols[s]:
            lines = _wrap(n.text, 28)
            chips = ind_by_node.get(n.id, [])
            h = pad * 2 + 14 + line_h * len(lines) + (14 if chips else 0)
            pos[n.id] = (x, y, col_w, h)
            y += h + 14
        col_heights.append(y)
    # 성과목표 띠
    goal_lines = []
    for g in d.goals:
        goal_lines.extend(_wrap(f"{g['id']} {g['text']}", 150))
    body_bottom = max(col_heights + [top + 120])
    goal_y = body_bottom + 10
    goal_h = 18 + 15 * max(1, len(goal_lines)) + 10
    sg_lines = _wrap("전략목표: " + (_s(d.strategic_goal.get("text")) or "(비어 있음 — [확인 필요])"), 150)
    sg_h = 15 * len(sg_lines) + 12
    total_w = left * 2 + 5 * col_w + 4 * gap
    total_h = goal_y + goal_h + sg_h + 70
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" font-family="sans-serif">',
           f"<style>{_SVG_CSS}</style>",
           f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>',
           '<defs><marker id="ar" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1b2a4a"/></marker>'
           '<marker id="arb" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#b91c1c"/></marker></defs>']
    t = title or f"{d.name} 논리모형"
    out.append(f'<text class="title" x="{left}" y="36">{_esc(t)}</text>')
    sub = f"투입 → 활동 → 산출 → 결과(단기) → 결과(장기)·성과목표 · 설계서에 적힌 것만 그림"
    out.append(f'<text class="sub" x="{left}" y="58">{_esc(sub)}</text>')
    # 열 머리
    for ci, s in enumerate(STAGES):
        x = left + ci * (col_w + gap)
        out.append(f'<rect x="{x}" y="{top}" width="{col_w}" height="26" rx="4" fill="#1b2a4a"/>')
        out.append(f'<text class="hdr" x="{x + col_w / 2}" y="{top + 18}" text-anchor="middle">{_esc(s)}</text>')
        if not cols[s]:
            out.append(f'<rect x="{x}" y="{top + 36}" width="{col_w}" height="40" rx="4" fill="none" stroke="#b91c1c" stroke-dasharray="5 4"/>')
            out.append(f'<text class="badge" x="{x + col_w / 2}" y="{top + 60}" text-anchor="middle">비어 있음 — 끊김</text>')
    # 연결선
    for n in d.nodes.values():
        if n.id not in pos:
            continue
        x2, y2, w2, h2 = pos[n.id]
        for u in n.upstream:
            if u not in pos:
                continue
            x1, y1, w1, h1 = pos[u]
            sx, sy, ex, ey = x1 + w1, y1 + h1 / 2, x2, y2 + h2 / 2
            mx = (sx + ex) / 2
            dashed = ' stroke-dasharray="4 3"' if not n.because and n.stage.startswith("결과") else ""
            out.append(f'<path d="M{sx},{sy} C{mx},{sy} {mx},{ey} {ex},{ey}" fill="none" stroke="#1b2a4a" stroke-width="1.4"{dashed} marker-end="url(#ar)"/>')
    # 노드
    for n in d.nodes.values():
        x, y, w, h = pos[n.id]
        broken = n.id in broken_nodes
        stroke = "#b91c1c" if broken else "#1b2a4a"
        fill = "#fff5f5" if broken else ("#eef2f8" if n.stage.startswith("결과") else "#ffffff")
        dash = ' stroke-dasharray="6 4"' if broken else ""
        out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>')
        head = n.id + (f" · {n.sub_program}" if n.sub_program else "") + (f" → {n.goal}" if n.goal else "")
        out.append(f'<text class="nid" x="{x + pad}" y="{y + pad + 10}">{_esc(head)}</text>')
        if broken:
            out.append(f'<text class="badge" x="{x + w - pad}" y="{y + pad + 10}" text-anchor="end">끊김</text>')
        yy = y + pad + 10 + line_h
        for ln in _wrap(n.text, 28):
            out.append(f'<text class="node" x="{x + pad}" y="{yy}">{_esc(ln)}</text>')
            yy += line_h
        chips = ind_by_node.get(n.id, [])
        if chips:
            cx = x + pad
            for c in chips:
                cw = 8 + 7 * len(c)
                out.append(f'<rect x="{cx}" y="{yy - 10}" width="{cw}" height="13" rx="6" fill="#dbe4f3"/>')
                out.append(f'<text class="chip" x="{cx + cw / 2}" y="{yy}" text-anchor="middle">{_esc(c)}</text>')
                cx += cw + 4
    # 성과목표·전략목표 띠
    out.append(f'<rect x="{left}" y="{goal_y}" width="{total_w - 2 * left}" height="{goal_h}" rx="5" fill="#f3f6fb" stroke="#1b2a4a"/>')
    out.append(f'<text class="nid" x="{left + pad}" y="{goal_y + 16}">성과목표</text>')
    yy = goal_y + 32
    for ln in goal_lines or ["(없음 — 끊김)"]:
        out.append(f'<text class="goal" x="{left + pad}" y="{yy}">{_esc(ln)}</text>')
        yy += 15
    sy = goal_y + goal_h + 6
    out.append(f'<rect x="{left}" y="{sy}" width="{total_w - 2 * left}" height="{sg_h}" rx="5" fill="#1b2a4a"/>')
    yy = sy + 16
    for ln in sg_lines:
        out.append(f'<text class="hdr" x="{left + pad}" y="{yy}" font-weight="400">{_esc(ln)}</text>')
        yy += 15
    # 범례·정직성
    fy = sy + sg_h + 20
    out.append(f'<line x1="{left}" y1="{fy - 4}" x2="{left + 30}" y2="{fy - 4}" stroke="#1b2a4a" stroke-width="1.4" marker-end="url(#ar)"/>')
    out.append(f'<text class="foot" x="{left + 36}" y="{fy}">연결(설계서의 uses/from)</text>')
    out.append(f'<line x1="{left + 200}" y1="{fy - 4}" x2="{left + 230}" y2="{fy - 4}" stroke="#1b2a4a" stroke-width="1.4" stroke-dasharray="4 3"/>')
    out.append(f'<text class="foot" x="{left + 236}" y="{fy}">연결은 있으나 \'그래서\' 문장(because) 없음</text>')
    out.append(f'<rect x="{left + 520}" y="{fy - 12}" width="22" height="12" fill="#fff5f5" stroke="#b91c1c" stroke-dasharray="6 4"/>')
    out.append(f'<text class="foot" x="{left + 548}" y="{fy}">끊김(산출 없는 활동·결과 없는 산출·목표 미연결·고아)</text>')
    out.append(f'<text class="foot" x="{left}" y="{fy + 18}">{_esc(f"자료: 설계서 {d.name}. 지표 칩(K…)은 그 노드를 잰다고 설계서가 밝힌 것. [확인 필요] {unverified_count}건은 보고서 5절. rnd-program-logic {__version__}")}</text>')
    out.append("</svg>")
    return "\n".join(out)


def figure_spec(d: Design) -> dict:
    """doc-figure `structure-block` 스펙 — 같은 내용을 doc-figure 프리셋으로 다시 그릴 때 쓴다."""
    layers = []
    for s in STAGES:
        boxes = [{"title": n.id + (f" → {n.goal}" if n.goal else ""), "desc": n.text} for n in d.nodes.values() if n.stage == s]
        layers.append({"label": s.replace("(", "\n("), "boxes": boxes or [{"title": "(비어 있음)", "desc": "끊김"}]})
    return {"template": "structure-block", "preset": "gov-navy", "title": f"{d.name} 논리모형",
            "subtitle": "투입 → 활동 → 산출 → 결과(단기) → 결과(장기)", "layers": layers,
            "caption": f"[그림] {d.name} 논리모형 — 설계서에 적힌 것만. 자료: rnd-program-logic"}


# ---------------------------------------------------------------------------
# 5. 보고서
# ---------------------------------------------------------------------------


def _md(s) -> str:
    return _s(s).replace("|", "\\|").replace("\n", " ")


def _fmt_targets(tg: dict) -> str:
    if not tg:
        return "—"
    parts = []
    for y, v in sorted(tg.items()):
        parts.append(f"{y}: {v if v is not None else '[확인 필요]'}")
    return ", ".join(parts)


def build_report(d: Design, res: dict, findings: list[Finding], svg_name: str) -> str:
    nodes = d.nodes
    L = []
    L.append(f"# 사업 논리모형·성과지표 점검 — {d.name}")
    L.append("")
    L.append(f"판정 **{res['status']}** · " + " · ".join(f"{k} {v}" for k, v in res["counts"].items()) + f" · 설계서 sha {res['design_sha']} · {res['checked_at']} · rnd-program-logic {__version__}")
    L.append("")
    L.append("## 0. 기본 칸")
    L.append("")
    L.append("| 소관 | 기간(기한/계속) | 총사업비 | 사업유형 | 수명 주기 | 내역사업 |")
    L.append("|---|---|---|---|---|---|")
    p = d.period or {}
    per = f"{_s(p.get('start')) or '?'}~{_s(p.get('end')) or '?'} ({_s(p.get('type')) or '[확인 필요]'})"
    bv = d.budget.get("value")
    bud = f"{bv:,} {_s(d.budget.get('unit'))}".strip() if isinstance(bv, (int, float)) else "[확인 필요]"
    if isinstance(bv, (int, float)) and _s(d.budget.get("source")):
        bud += f" ({_md(d.budget.get('source'))})"
    pt = d.program_type or "[확인 필요]"
    if d.program_type and d.program_type_basis:
        pt += f" — {_md(d.program_type_basis)}"
    L.append(f"| {_md(d.agency) or '[확인 필요]'} | {per} | {bud} | {pt} | {d.lifecycle or '[확인 필요]'} | {', '.join(d.sub_programs) or '—'} |")
    L.append("")
    L.append(f"전략목표: {_md(d.strategic_goal.get('text')) or '[확인 필요]'}" + (f" ({_md(d.strategic_goal.get('source'))})" if _s(d.strategic_goal.get("source")) else ""))
    L.append("")
    for g in d.goals:
        L.append(f"- {g['id']} {_md(g['text']) or '[확인 필요]'}" + (f" ({_md(g['source'])})" if g["source"] else ""))
    L.append("")
    L.append("## 1. 사슬 표 (설계서에 적힌 문장 그대로)")
    L.append("")
    L.append("| 칸 | id | 문장 | 상류 | 출처 |")
    L.append("|---|---|---|---|---|")
    for s in STAGES:
        rows = [n for n in nodes.values() if n.stage == s]
        if not rows:
            L.append(f"| {s} | — | (비어 있음 — 끊김) | | |")
        for n in rows:
            up = ", ".join(n.upstream) if n.upstream else "—"
            if n.goal:
                up += f" → {n.goal}"
            L.append(f"| {s} | {n.id} | {_md(n.text) or '(비어 있음)'} | {up} | {_md(n.source) or '—'} |")
    L.append("")
    L.append("## 2. 연결 판정")
    L.append("")
    L.append("| 연결 | 설계서의 '그래서' 문장(because) | 판정 |")
    L.append("|---|---|---|")
    broken_ids = {f.where for f in findings if f.level == BROKEN}
    for n in nodes.values():
        for u in n.upstream:
            if u not in nodes:
                continue
            verdict = "끊김" if (n.id in broken_ids or u in broken_ids) else ("연결됨" if (n.because or not n.stage.startswith("결과")) else "연결은 있으나 근거 문장 없음")
            L.append(f"| {u} {nodes[u].stage} → {n.id} {n.stage} | {_md(n.because) or '—'} | {verdict} |")
        if n.goal:
            L.append(f"| {n.id} → 성과목표 {n.goal} | {_md(n.because) or '—'} | {'연결됨' if n.goal in {g['id'] for g in d.goals} else '오류'} |")
    L.append("")
    L.append("## 3. 점검표")
    L.append("")
    L.append("| 항목 | 판정 | 위치 | 내용 | 근거 지침 | 수정 제안 |")
    L.append("|---|---|---|---|---|---|")
    for f in res["findings"]:
        ev = "; ".join(f"{e['label']}" + (" **[확인 필요]**" if e["status"] != "확인" else "") for e in f["evidence"])
        L.append(f"| {f['check']} {_md(f['title'])} | {f['level']} | {_md(f['where'])} | {_md(f['message'])} | {_md(ev)} | {_md(f['fix']) or '—'} |")
    L.append("")
    L.append("## 4. 지표표")
    L.append("")
    L.append("| 지표 | 성과목표 | 재는 노드 | 단계 | 질적/양적 | 산식 | 목표치 | baseline | 목표치 근거 | 외부요인 처리 | 지표 판정 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    per_ind = {}
    for f in findings:
        if f.where in {k.id for k in d.indicators} and f.level in (FAIL, WARN, UNVERIFIED, ERROR):
            per_ind.setdefault(f.where, []).append(f)
    for k in d.indicators:
        fs = per_ind.get(k.id, [])
        worst = min(fs, key=lambda f: _ORDER[f.level]).level if fs else PASS
        codes = ", ".join(sorted({f.check for f in fs})) if fs else "—"
        node = f"{k.measures} ({nodes[k.measures].stage})" if k.measures in nodes else (k.measures or "—")
        bl = k.baseline or {}
        blt = f"{bl.get('value')} ({bl.get('year')})" if bl.get("value") is not None else "[확인 필요]"
        basis = _md(k.target_basis) if k.target_basis else "[확인 필요]"
        if k.target_basis and k.target_source:
            basis += f" ({_md(k.target_source)})"
        L.append(f"| {k.id} {_md(k.name)} | {k.goal or '—'} | {node} | {k.stage or '—'} | {k.kind or '(미기재)'} | {_md(k.formula) or '[확인 필요]'} | {_md(_fmt_targets(k.targets))} | {blt} | {basis} | {_md(k.external_factors) or '—'} | {worst} ({codes}) |")
    if not d.indicators:
        L.append("| (없음) | | | | | | | | | | 끊김 |")
    L.append("")
    L.append("## 5. 지어내지 않은 것 — 입력에 없어 [확인 필요]로 남긴 것")
    L.append("")
    unv = res["unverified"]
    if unv:
        for u in unv:
            L.append(f"- [확인 필요] {u['check']} {u['where']}: {u['message']}")
    else:
        L.append("- 없음")
    L.append("")
    L.append("근거 지침 가운데 원문을 확인하지 못한 것:")
    L.append("")
    for k, v in EVIDENCE.items():
        if v["status"] != "확인":
            L.append(f"- [확인 필요] {v['label']} — {v['text']}")
    L.append("")
    L.append("## 6. 논리모형 그림")
    L.append("")
    L.append(f"![논리모형]({svg_name})")
    L.append("")
    L.append("## 7. 근거 표 — 점검 항목이 따르는 지침·조문")
    L.append("")
    L.append("| 근거 | 내용(요지) | 확인 상태 | 확인 방법 |")
    L.append("|---|---|---|---|")
    for k, v in EVIDENCE.items():
        st = f"확인 {v['checked']}" if v["status"] == "확인" else "**확인 필요**"
        L.append(f"| {_md(v['label'])} | {_md(v['text'])} | {st} | {_md(v['how'])} |")
    L.append("")
    L.append("## 8. 정직성 규칙 (이 도구가 지키는 것)")
    L.append("")
    for h in HONESTY:
        L.append(f"- {h}")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------


def _out_dir(args, design_path: Path) -> Path:
    out = Path(args.out) if getattr(args, "out", None) else design_path.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    return out


def cmd_init(args):
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"이미 있음: {out} (--force 로 덮어쓰기)")
        return 1
    y = _dt.date.today().year + 1
    out.write_text(DESIGN_TEMPLATE.format(y0=y, y1=y + 4), encoding="utf-8")
    print(f"→ {out}")
    return 0


def _load(args):
    p = Path(args.design)
    if not p.exists():
        print(f"설계서 없음: {p}")
        raise SystemExit(2)
    return p, load_design(p)


def cmd_check(args):
    p, d = _load(args)
    out = _out_dir(args, p)
    findings = run_checks(d)
    res = check_to_dict(d, p, findings)
    (out / "check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if not getattr(args, "quiet", False):
        print_check(res)
        print(f"→ {out / 'check.json'}")
    return 0 if res["status"] in ("PASS", "WARN") else 3


def cmd_render(args):
    p, d = _load(args)
    out = _out_dir(args, p)
    findings = run_checks(d)
    svg = render_svg(d, findings)
    (out / "logic_model.svg").write_text(svg, encoding="utf-8")
    page = f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>{_esc(d.name)} 논리모형</title></head><body style='margin:16px;background:#fff'>{svg}</body></html>"
    (out / "logic_model.html").write_text(page, encoding="utf-8")
    (out / "figure_spec.json").write_text(json.dumps(figure_spec(d), ensure_ascii=False, indent=2), encoding="utf-8")
    if not getattr(args, "quiet", False):
        print(f"→ {out / 'logic_model.svg'}, logic_model.html, figure_spec.json")
    return 0


def cmd_report(args):
    p, d = _load(args)
    out = _out_dir(args, p)
    findings = run_checks(d)
    res = check_to_dict(d, p, findings)
    (out / "check.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    svg = render_svg(d, findings)
    (out / "logic_model.svg").write_text(svg, encoding="utf-8")
    (out / "logic_model.html").write_text(f"<!doctype html><html lang='ko'><head><meta charset='utf-8'></head><body style='margin:16px;background:#fff'>{svg}</body></html>", encoding="utf-8")
    (out / "figure_spec.json").write_text(json.dumps(figure_spec(d), ensure_ascii=False, indent=2), encoding="utf-8")
    md = build_report(d, res, findings, "logic_model.svg")
    (out / "report.md").write_text(md, encoding="utf-8")
    if not getattr(args, "quiet", False):
        print_check(res)
        print(f"→ {out / 'report.md'}, check.json, logic_model.svg/.html, figure_spec.json")
    return 0 if res["status"] in ("PASS", "WARN") else 3


def cmd_evidence(_args):
    print("점검 항목 → 근거 (상태)")
    for cid, (title, evs) in CHECKS.items():
        print(f"  {cid:<4} {title}")
        for e in evs:
            v = EVIDENCE[e]
            st = f"확인 {v['checked']}" if v["status"] == "확인" else "확인 필요"
            print(f"        - {v['label']}  [{st}]")
    print("\n원문 미확보(확인 필요):")
    for k, v in EVIDENCE.items():
        if v["status"] != "확인":
            print(f"  - {v['label']}: {v['text']}")
    return 0


def cmd_selftest(_args):
    import unittest

    sys.argv = [sys.argv[0]]
    here = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(here / "tests"), pattern="test_*.py")
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if res.wasSuccessful() else 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="program_logic.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"rnd-program-logic {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="설계서 서식")
    p.add_argument("--out", default="program.yaml")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    for name, fn, h in (("check", cmd_check, "점검 → check.json"), ("render", cmd_render, "논리모형 그림(SVG/HTML)+doc-figure 스펙"),
                        ("report", cmd_report, "점검표·지표표·그림·확인 필요 절 → report.md"), ("run", cmd_report, "report 와 같음")):
        p = sub.add_parser(name, help=h)
        p.add_argument("design")
        p.add_argument("--out")
        p.add_argument("--quiet", action="store_true")
        p.set_defaults(fn=fn)
    sub.add_parser("evidence", help="점검 항목별 근거 지침과 확인 상태").set_defaults(fn=cmd_evidence)
    sub.add_parser("selftest", help="자체 점검").set_defaults(fn=cmd_selftest)
    args = ap.parse_args(argv)
    rc = args.fn(args)
    raise SystemExit(rc or 0)


if __name__ == "__main__":
    main()
