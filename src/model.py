"""도메인 모델 — 강종(Color) / Place / 경로(Route).

기존 프로토타입 legacy/cpn_slab.html 의 GRADES / STAGES / stagesFor 를
파이썬으로 이식한 것입니다. 데이터 주도 원칙을 유지해, 모델 변경은 이 파일에서
시작합니다. (참고: docs/ARCHITECTURE.md)
"""
from __future__ import annotations

from dataclasses import dataclass

INF = float("inf")


@dataclass(frozen=True)
class Grade:
    """강종(Color set). route 에 따라 정련 경로가 분기된다."""
    id: str
    color: str
    route: str   # "LF" | "RH" | "DIRECT"
    label: str


@dataclass(frozen=True)
class Stage:
    """Place(공정 위치). proc=처리 체류 스텝, cap=동시 수용 용량."""
    id: str
    label: str
    proc: int
    cap: float


GRADES: list[Grade] = [
    Grade("SUS304", "#c084fc", "LF",     "스테인리스"),
    Grade("SS400",  "#34d399", "DIRECT", "일반구조용"),
    Grade("API5L",  "#f59e0b", "RH",     "파이프라인강"),
]

STAGES: list[Stage] = [
    Stage("ld",      "전로 OUT",   1, INF),
    Stage("lf_wait", "정련 대기",   1, 3),
    Stage("lf",      "LF 정련",    3, 1),
    Stage("rh",      "RH 탈가스",  4, 1),
    Stage("tundish", "턴디시",     1, 1),
    Stage("mold",    "몰드",       2, 1),
    Stage("cooling", "2차 냉각대", 3, 4),
    Stage("yard",    "슬래브 야드", 1, INF),
]

# 강종별 Place 시퀀스 (lf_wait 이후가 강종에 따라 분기)
ROUTES: dict[str, list[str]] = {
    "LF":     ["ld", "lf_wait", "lf", "tundish", "mold", "cooling", "yard"],
    "RH":     ["ld", "lf_wait", "rh", "tundish", "mold", "cooling", "yard"],
    "DIRECT": ["ld", "lf_wait", "tundish", "mold", "cooling", "yard"],
}

GRADE_BY_ID: dict[str, Grade] = {g.id: g for g in GRADES}
STAGE_BY_ID: dict[str, Stage] = {s.id: s for s in STAGES}


def stages_for(route: str) -> list[str]:
    return ROUTES[route]


def temp_for(stage_id: str, rng=None) -> int:
    """Place 기준 대표 온도(℃). 상태가 아닌 재계산값."""
    base = {"ld": 1650, "lf": 1580, "rh": 1580, "tundish": 1545, "mold": 1520}
    if stage_id in base:
        return base[stage_id]
    if stage_id == "cooling":
        jitter = rng.randint(0, 199) if rng else 100
        return 1100 + jitter
    return 900
