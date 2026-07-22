"""개선 what-if (D: Prescriptive).

C(원인 분석)에서 병목(몰드)의 최대 지연 원인이 **강종 전환 셋업**으로 나왔습니다.
여기서는 같은 heat 집합을 **주조 순서만 바꿔**(캐스트 시퀀싱) 재시뮬레이션하여,
전환 최소화가 병목·리드타임·처리량에 주는 개선 효과를 정량화합니다.

결정론적(무작위 제거) 스케줄러로 기준(도착순)과 개선(강종 그룹핑)을 같은 조건에서
비교하므로, 차이는 오롯이 '순서 결정'에서 옵니다. 실제로는 납기·폭 제약이 붙으면
개선폭이 줄며, 그 트레이드오프가 '제약·최적화' 단계의 몫입니다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .model import GRADE_BY_ID, GRADES, STAGE_BY_ID, stages_for

PROC_MINUTES = 6      # proc 1스텝당 처리시간(분)
SETUP_GRADE = 9       # 강종 전환 셋업(분, 결정론적 예시)
SETUP_WIDTH = 5       # 폭 전환 셋업(분)
INTERARRIVAL = 21     # 도착 간격(분)
INF = float("inf")


@dataclass
class Heat:
    heat_no: str
    grade: str
    width: int


def heats_from_log(df: pd.DataFrame) -> list[Heat]:
    """이벤트 로그에서 heat 목록(강종·폭)을 도착순으로 추출."""
    first = df.sort_values("enter_time").groupby("heat_no", sort=False)
    out = []
    for hid, sub in first:
        width = int(sub["width_mm"].iloc[0]) if "width_mm" in sub.columns else 1200
        out.append(Heat(str(hid), str(sub["grade"].iloc[0]), width))
    return out


def order_by(policy: str, heats: list[Heat], window: int = 8) -> list[Heat]:
    gorder = {g.id: i for i, g in enumerate(GRADES)}
    if policy == "grade":       # 전체 강종 그룹핑(전환 최소화 상한)
        return sorted(heats, key=lambda h: gorder.get(h.grade, 99))
    if policy == "window":      # 윈도우 내 강종 그룹핑(도착순 크게 안 흔듦)
        out: list[Heat] = []
        for i in range(0, len(heats), window):
            out.extend(sorted(heats[i:i + window], key=lambda h: gorder.get(h.grade, 99)))
        return out
    return list(heats)          # arrival (도착순, 기준)


def simulate(ordered: list[Heat], start: str = "2026-06-01 06:00",
             interarrival: float = INTERARRIVAL) -> dict:
    t0 = pd.Timestamp(start)
    free: dict[str, list[pd.Timestamp]] = {
        s.id: [t0] * (1 if s.cap == INF else int(s.cap)) for s in
        [STAGE_BY_ID[k] for k in STAGE_BY_ID]}
    last_grade: dict[int, str] = {}
    last_width: dict[int, int] = {}
    grade_changes = 0
    setup_total = 0.0
    mold_proc_sum = 0.0
    leads, arrivals, exits = [], [], []

    def earliest(sid: str) -> int:
        return min(range(len(free[sid])), key=lambda k: free[sid][k])

    for i, h in enumerate(ordered):
        arrival = t0 + pd.Timedelta(minutes=interarrival * i)
        ready = arrival
        for idx, sid in enumerate(stages_for(GRADE_BY_ID[h.grade].route)):
            stg = STAGE_BY_ID[sid]
            infinite = stg.cap == INF
            slot = 0 if infinite else earliest(sid)
            start_t = ready if infinite else max(ready, free[sid][slot])
            proc = PROC_MINUTES * stg.proc
            if sid == "mold" and not infinite:
                pg = last_grade.get(slot)
                if pg is not None and pg != h.grade:
                    proc += SETUP_GRADE; setup_total += SETUP_GRADE; grade_changes += 1
                elif pg is not None and abs(last_width.get(slot, h.width) - h.width) > 200:
                    proc += SETUP_WIDTH; setup_total += SETUP_WIDTH
                mold_proc_sum += proc
            proc_end = start_t + pd.Timedelta(minutes=proc)
            move = (max(proc_end, free["mold"][earliest("mold")])
                    if sid == "tundish" else proc_end)
            exit_t = move
            if not infinite:
                free[sid][slot] = exit_t
                if sid == "mold":
                    last_grade[slot] = h.grade
                    last_width[slot] = h.width
            ready = exit_t
        leads.append((ready - arrival).total_seconds() / 60)
        arrivals.append(arrival)
        exits.append(ready)

    span_min = (max(exits) - t0).total_seconds() / 60
    ev = sorted([(a, 1) for a in arrivals] + [(e, -1) for e in exits])
    wip = peak = 0
    for _, d in ev:
        wip += d
        peak = max(peak, wip)
    return {
        "grade_changes": grade_changes,
        "setup_min": setup_total,
        "avg_lead_min": sum(leads) / len(leads),
        "throughput_per_h": len(ordered) / (span_min / 60),
        "mold_util_pct": min(mold_proc_sum / span_min * 100, 100.0),
        "wip_peak": peak,
    }


def compare(df: pd.DataFrame, window: int = 8) -> dict:
    """로그의 heat들로 기준(도착순) vs 개선(윈도우/전체 그룹핑) KPI 비교."""
    heats = heats_from_log(df)
    return {
        "n_heats": len(heats),
        "window": window,
        "baseline": simulate(order_by("arrival", heats)),
        "windowed": simulate(order_by("window", heats, window)),
        "grouped": simulate(order_by("grade", heats)),
    }
