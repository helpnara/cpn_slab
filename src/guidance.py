"""라우팅 가이던스 (E: Decision support · 데모).

신규 슬래브가 들어왔을 때, 현재 공정 상태·강종 전환·납기를 고려해 **이동 방향(정련
경로)과 주조 조치**를 추천하고 **근거·예상 영향**을 제시하는 의사결정 지원 데모입니다.

규칙 기반(설명 가능)으로 시작합니다 — human-in-the-loop 신뢰 확보가 목적이며, 최종
결정은 현업(오퍼레이터)이 합니다. 실제 제약·가중치는 인터뷰로 확정하고, 이후
`src/optimization.py`(OR-Tools CP-SAT)로 승급합니다. (docs/DEV_PLAN.md D2/E1)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import GRADE_BY_ID, GRADES
from .whatif import SETUP_GRADE, SETUP_WIDTH

ROUTE_LABEL = {"LF": "LF 정련", "RH": "RH 탈가스", "DIRECT": "직행(정련 생략)"}
MOLD_SERVICE_MIN = 12.0


@dataclass
class Recommendation:
    route: str
    route_label: str
    action: str
    setup_min: float
    est_wait_min: float
    rationale: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)


def est_wait(util_pct: float, service_min: float = MOLD_SERVICE_MIN) -> float:
    """대략적 대기 추정(M/M/1 근사) — 가동률이 높을수록 급증."""
    u = min(max(util_pct / 100.0, 0.0), 0.98)
    return u / (1 - u) * service_min


def recommend(grade: str, width: int, prev_width: int, current_mold_grade: str,
              queue_grades: list[str], mold_util: float, urgent: bool) -> Recommendation:
    g = GRADE_BY_ID.get(grade)
    route = g.route if g else "DIRECT"
    route_label = ROUTE_LABEL.get(route, route)
    route_reason = f"Guard: 강종 {grade} → {route_label} (강종별 필수 경로)"

    same_as_current = grade == current_mold_grade and bool(current_mold_grade)
    setup_now = 0.0
    if grade != current_mold_grade and current_mold_grade:
        setup_now = SETUP_GRADE
    elif same_as_current and abs((prev_width or width) - width) > 200:
        setup_now = SETUP_WIDTH

    same_in_queue = queue_grades.count(grade)
    wait = est_wait(mold_util)
    rationale = [route_reason]
    alternatives: list[dict] = []

    if same_as_current and setup_now == 0:
        action = "지금 몰드 슬롯에 즉시 주조"
        rationale.append(f"현재 몰드 강종과 동일({grade}) → 전환 셋업 0분")
    elif urgent:
        action = "즉시 주조 (납기 우선)"
        rationale.append("납기 임박 → 셋업을 감수하고 즉시 배정")
        if setup_now:
            rationale.append(f"전환 셋업 {setup_now:.0f}분 발생(감수)")
        alternatives.append({"대안": "동일 강종과 묶어 대기", "전환셋업(분)": 0.0,
                             "비고": "셋업은 없으나 납기 위험"})
    elif setup_now > 0 and same_in_queue >= 1:
        action = f"동일 강종({grade})과 묶어 주조 (대기)"
        rationale.append(f"대기열에 동일 강종 {same_in_queue}건 → 묶으면 전환 셋업 {setup_now:.0f}분 회피")
        rationale.append("단, 묶기까지 대기 발생 — 납기 여유 있을 때 유리")
        alternatives.append({"대안": "즉시 주조", "전환셋업(분)": setup_now,
                             "비고": "셋업 발생·병목 부담↑"})
    else:
        action = "즉시 주조"
        rationale.append("묶을 동일 강종이 대기열에 없어 즉시 배정" if setup_now
                         else "전환 없음 → 즉시 배정")
        if setup_now:
            rationale.append(f"전환 셋업 {setup_now:.0f}분")

    if mold_util >= 85:
        rationale.append(f"⚠ 몰드 가동률 {mold_util:.0f}% (병목) → 예상 대기 약 {wait:.0f}분")

    return Recommendation(route, route_label, action, setup_now, wait, rationale, alternatives)
