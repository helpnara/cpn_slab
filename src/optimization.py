"""제약·최적화 **예시** (인터뷰 설명용 데모).

⚠️ 여기 값·규칙은 모두 **가정한 예시**입니다. 현업 인터뷰에서 실제 목적·제약·수치로
대체하는 것이 목표이며(docs/OPTIMIZATION_SPEC.md), 대체 시 이 모듈을 OR-Tools
CP-SAT 등 정식 solver 구현으로 바꿉니다. 지금은 "최적화가 무엇을 하는지"를
현업에게 눈으로 보여 주기 위한 소규모 예시(브루트포스)입니다.

예시 문제: **캐스트 시퀀싱** — 한 턴디시로 연속 주조할 heat들의 주조 순서를 정한다.
- 제약(예시): 폭 전이 상한(coffin rule), 턴디시 수명(캐스트당 최대 heat)
- 목적(예시): 폭 증가 최소화 + 강종 전환 최소화 + 납기/우선순위 준수
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations
from typing import Optional


@dataclass(frozen=True)
class Heat:
    heat_no: str
    grade: str
    width: int   # 슬래브 폭(mm)
    due: int     # 목표 주조 순번(1=가장 급함) — 예시 우선순위


# 예시 데이터(가정값). 실제 heat 목록은 현업/ MES 데이터로 대체.
EXAMPLE_HEATS: list[Heat] = [
    Heat("H01", "SS400",  1250, 5),
    Heat("H02", "API5L",  1600, 2),
    Heat("H03", "SS400",  1250, 7),
    Heat("H04", "SUS304", 1050, 1),
    Heat("H05", "API5L",  1550, 4),
    Heat("H06", "SS400",  1450, 6),
    Heat("H07", "SUS304", 1000, 3),
    Heat("H08", "API5L",  1500, 8),
]


@dataclass
class Weights:
    width_up: float = 3.0     # 폭 '증가' 페널티 (coffin: 몰드 폭 확대는 비쌈)
    width_down: float = 0.2   # 폭 '감소' 페널티 (상대적으로 허용적)
    grade_change: float = 60.0  # 강종 전환 1회당 setup 페널티
    due: float = 8.0          # 납기/우선순위 위반 페널티


@dataclass
class Options:
    use_width: bool = True
    use_grade: bool = True
    use_due: bool = True
    enforce_max_jump: bool = True
    max_width_jump: int = 300   # 인접 슬래브 폭 변화 상한(mm) — 하드 제약(예시)
    max_heats_per_cast: int = 8  # 턴디시 수명(예시)


# ── 비용 구성요소 ────────────────────────────────────────────
def width_cost(seq: list[Heat], w: Weights) -> float:
    c = 0.0
    for a, b in zip(seq, seq[1:]):
        d = b.width - a.width
        c += w.width_up * d if d > 0 else w.width_down * (-d)
    return c


def grade_changes(seq: list[Heat]) -> int:
    return sum(1 for a, b in zip(seq, seq[1:]) if a.grade != b.grade)


def due_cost(seq: list[Heat]) -> float:
    # 급한(due 작은) heat이 목표 순번보다 뒤에 놓이면 페널티
    return float(sum(max(0, pos - h.due) for pos, h in enumerate(seq, start=1)))


def total_cost(seq: list[Heat], w: Weights, opt: Options) -> tuple[float, dict]:
    parts: dict[str, float] = {}
    if opt.use_width:
        parts["폭 전이"] = width_cost(seq, w)
    if opt.use_grade:
        parts["강종 전환"] = w.grade_change * grade_changes(seq)
    if opt.use_due:
        parts["납기"] = w.due * due_cost(seq)
    return sum(parts.values()), parts


def feasible(seq: list[Heat], opt: Options) -> bool:
    if len(seq) > opt.max_heats_per_cast:
        return False
    if opt.enforce_max_jump:
        for a, b in zip(seq, seq[1:]):
            if abs(b.width - a.width) > opt.max_width_jump:
                return False
    return True


@dataclass
class Result:
    sequence: list[Heat]
    cost: float
    parts: dict
    feasible: bool


def optimize(heats: list[Heat], w: Weights, opt: Options) -> Result:
    """소규모 브루트포스 예시. n<=8 가정(8! = 40,320)."""
    best: Optional[list[Heat]] = None
    best_c: Optional[float] = None
    best_parts: dict = {}
    any_feasible = False

    for perm in permutations(heats):
        seq = list(perm)
        if not feasible(seq, opt):
            continue
        any_feasible = True
        c, parts = total_cost(seq, w, opt)
        if best_c is None or c < best_c:
            best, best_c, best_parts = seq, c, parts

    if not any_feasible:  # 하드 제약이 너무 빡빡 → 제약 완화(예시)해 최소비용 제시
        relaxed = Options(**{**opt.__dict__, "enforce_max_jump": False})
        for perm in permutations(heats):
            seq = list(perm)
            c, parts = total_cost(seq, w, relaxed)
            if best_c is None or c < best_c:
                best, best_c, best_parts = seq, c, parts

    return Result(sequence=best or list(heats), cost=best_c or 0.0,
                  parts=best_parts, feasible=any_feasible)


def baseline(heats: list[Heat], w: Weights, opt: Options) -> Result:
    """입력(주어진) 순서 그대로의 기준선."""
    seq = list(heats)
    c, parts = total_cost(seq, w, opt)
    return Result(sequence=seq, cost=c, parts=parts, feasible=feasible(seq, opt))
