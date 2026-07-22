"""데이터 계층 (A1 스키마·감사 / A2 로더·샘플).

과거 물류 이벤트 로그의 **표준 스키마**를 정의하고, 로드·검증(데이터 감사)과
가시화·병목 분석용 파생지표를 계산합니다. 실데이터가 들어오기 전이라도 형식을
확정하고 데모를 돌릴 수 있도록 현실적인 **샘플 로그 생성기**를 포함합니다.

표준 스키마 — "공정 방문(stage-visit)" 롱 포맷 (1행 = heat 1개의 공정 1회 통과):
    heat_no      : 케이스 ID (예: H0001)
    grade        : 강종 (SUS304/SS400/API5L …)
    width_mm     : 슬래브 폭(mm)
    thickness_mm : 두께(mm)
    stage        : 공정 위치 (model.STAGES의 id 또는 라벨)
    enter_time   : 공정 진입 시각 (ISO datetime)
    exit_time    : 공정 이탈 시각 (ISO datetime)
    equipment    : (선택) 설비 식별 (예: MOLD-1)
    reason_code  : (선택) 지연/사유 코드
    due_date     : (선택) 납기 (ISO datetime)

체류시간 dwell = exit_time - enter_time (대기+처리 포함).
"""
from __future__ import annotations

import io
import random
from typing import Optional, Union

import pandas as pd

from .model import GRADES, STAGE_BY_ID, STAGES, stages_for

REQUIRED_COLUMNS = ["heat_no", "grade", "stage", "enter_time", "exit_time"]
OPTIONAL_COLUMNS = ["width_mm", "thickness_mm", "equipment", "reason_code", "due_date"]
ALL_COLUMNS = REQUIRED_COLUMNS[:2] + ["width_mm", "thickness_mm"] + \
    ["stage", "enter_time", "exit_time", "equipment", "reason_code", "due_date"]

# stage id 또는 한국어 라벨 → 표준 id
_STAGE_LOOKUP = {s.id: s.id for s in STAGES}
_STAGE_LOOKUP.update({s.label: s.id for s in STAGES})

_REASONS = ["설비점검", "래들지연", "온도조정", "폭변경셋업", "크레인대기", ""]
_PROC_MINUTES = 6  # proc 1스텝당 기준 처리시간(분)


# ══════════════════════════════════════════════════════════════
#  샘플 생성 (A2) — 설비 용량 경합으로 실제 병목이 찍히도록 스케줄링
# ══════════════════════════════════════════════════════════════
def generate_sample_event_log(n_heats: int = 120, start: str = "2026-06-01 06:00",
                              interarrival_min: float = 13.0, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    t0 = pd.Timestamp(start)
    grade_ids = [g.id for g in GRADES]
    weights = [0.34, 0.4, 0.26]

    # 설비 용량 슬롯의 다음 가용 시각
    free: dict[str, list[pd.Timestamp]] = {}
    for s in STAGES:
        cap = 1 if s.cap == float("inf") else int(s.cap)
        free[s.id] = [t0] * cap  # inf 공정은 실질 무경합(슬롯 재사용 안 해도 무방)

    rows = []
    for i in range(1, n_heats + 1):
        heat = f"H{i:04d}"
        grade = rng.choices(grade_ids, weights)[0]
        width = rng.choice([1000, 1050, 1250, 1450, 1500, 1550, 1600])
        thick = rng.randint(200, 300)
        arrival = t0 + pd.Timedelta(minutes=interarrival_min * (i - 1)
                                    + rng.uniform(-2, 2))
        due = arrival + pd.Timedelta(hours=rng.uniform(4, 10))
        ready = arrival
        for sid in stages_for(GRADES[grade_ids.index(grade)].route):
            stg = STAGE_BY_ID[sid]
            infinite = stg.cap == float("inf")
            enter = ready
            if infinite:
                start_t = ready
                slot = 0
            else:
                slot = min(range(len(free[sid])), key=lambda k: free[sid][k])
                start_t = max(ready, free[sid][slot])
            proc = _PROC_MINUTES * stg.proc * rng.uniform(0.8, 1.3)
            reason = ""
            if rng.random() < 0.08:  # 간헐 지연
                proc += rng.uniform(10, 40)
                reason = rng.choice(_REASONS[:-1])
            exit_t = start_t + pd.Timedelta(minutes=proc)
            if not infinite:
                free[sid][slot] = exit_t
            rows.append({
                "heat_no": heat, "grade": grade, "width_mm": width, "thickness_mm": thick,
                "stage": sid, "enter_time": enter, "exit_time": exit_t,
                "equipment": f"{sid.upper()}-{slot + 1}", "reason_code": reason,
                "due_date": due,
            })
            ready = exit_t
    df = pd.DataFrame(rows, columns=ALL_COLUMNS)
    return df


# ══════════════════════════════════════════════════════════════
#  로드 & 검증 (A1 데이터 감사)
# ══════════════════════════════════════════════════════════════
def load_event_log(source: Union[str, io.IOBase, pd.DataFrame]) -> pd.DataFrame:
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    for col in ("enter_time", "exit_time", "due_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "stage" in df.columns:
        df["stage"] = df["stage"].map(lambda v: _STAGE_LOOKUP.get(str(v).strip(), v))
    return df


def validate(df: pd.DataFrame) -> list[dict]:
    """데이터 감사 — 문제 목록 반환 [{level, msg}]."""
    issues: list[dict] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        issues.append({"level": "error", "msg": f"필수 컬럼 누락: {missing}"})
        return issues  # 필수 컬럼 없으면 이후 검증 불가

    n = len(df)
    for col in ("enter_time", "exit_time"):
        nulls = int(df[col].isna().sum())
        if nulls:
            issues.append({"level": "warn", "msg": f"{col} 파싱 실패/결측 {nulls}건"})
    bad_order = int((df["exit_time"] < df["enter_time"]).sum())
    if bad_order:
        issues.append({"level": "error", "msg": f"exit_time < enter_time 인 행 {bad_order}건"})
    unknown = sorted(set(df["stage"]) - set(s.id for s in STAGES))
    if unknown:
        issues.append({"level": "warn", "msg": f"미정의 공정(stage): {unknown}"})
    for col in OPTIONAL_COLUMNS:
        if col not in df.columns:
            issues.append({"level": "info", "msg": f"선택 컬럼 없음: {col}"})
    if not issues:
        issues.append({"level": "info", "msg": f"검증 통과 · {n}행 · heat {df['heat_no'].nunique()}건"})
    return issues


# ══════════════════════════════════════════════════════════════
#  파생 지표 (Phase B/C 씨앗)
# ══════════════════════════════════════════════════════════════
def with_dwell(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dwell_min"] = (out["exit_time"] - out["enter_time"]).dt.total_seconds() / 60
    return out


def lead_times(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("heat_no")
    lead = (g["exit_time"].max() - g["enter_time"].min()).dt.total_seconds() / 60
    grade = g["grade"].first()
    return pd.DataFrame({"heat_no": lead.index, "grade": grade.values,
                         "lead_min": lead.values})


def stage_dwell(df: pd.DataFrame) -> pd.DataFrame:
    d = with_dwell(df)
    agg = d.groupby("stage")["dwell_min"].agg(["mean", "median", "count"]).reset_index()
    order = {s.id: i for i, s in enumerate(STAGES)}
    agg["_o"] = agg["stage"].map(order).fillna(999)
    agg["label"] = agg["stage"].map(lambda s: STAGE_BY_ID[s].label if s in STAGE_BY_ID else s)
    return agg.sort_values("_o").drop(columns="_o").reset_index(drop=True)


def bottleneck_ranking(df: pd.DataFrame) -> pd.DataFrame:
    agg = stage_dwell(df).sort_values("mean", ascending=False).reset_index(drop=True)
    return agg


def wip_timeline(df: pd.DataFrame) -> pd.DataFrame:
    ev = pd.concat([
        pd.DataFrame({"t": df["enter_time"], "d": 1}),
        pd.DataFrame({"t": df["exit_time"], "d": -1}),
    ]).sort_values("t")
    ev["wip"] = ev["d"].cumsum()
    return ev[["t", "wip"]].reset_index(drop=True)


def throughput(df: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    done = df.groupby("heat_no")["exit_time"].max()
    tp = done.dt.floor(freq).value_counts().sort_index()
    return pd.DataFrame({"time": tp.index, "completed": tp.values})


if __name__ == "__main__":
    # 샘플 CSV 재생성:  python -m src.data
    sample = generate_sample_event_log()
    sample.to_csv("data/sample_event_log.csv", index=False)
    print(f"wrote data/sample_event_log.csv  ({len(sample)} rows, "
          f"{sample['heat_no'].nunique()} heats)")
