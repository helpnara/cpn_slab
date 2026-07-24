"""데이터 계층 (A1 스키마·감사 / A2 로더·샘플 / C 원인분석 지표).

과거 물류 이벤트 로그의 **표준 스키마**를 정의하고, 로드·검증(데이터 감사)과
가시화·병목·**원인 분석**용 파생지표를 계산합니다.

표준 스키마 — "공정 방문(stage-visit)" 롱 포맷 (1행 = heat 1개의 공정 1회 통과):
    heat_no, grade, width_mm, thickness_mm, stage,
    enter_time      : 공정 버퍼 진입(도착)
    start_time      : 처리 시작   (선택 · 있으면 대기/처리 분해 가능)
    proc_end_time   : 처리 완료   (선택 · 있으면 블로킹 분해 가능)
    exit_time       : 공정 이탈(반출)
    equipment, reason_code, due_date

시간 분해:  대기=start-enter,  처리=proc_end-start,  블로킹=exit-proc_end,  체류=exit-enter.
"""
from __future__ import annotations

import io
import random
from typing import Optional, Union

import pandas as pd

from .model import GRADES, STAGE_BY_ID, STAGES, stages_for

REQUIRED_COLUMNS = ["heat_no", "grade", "stage", "enter_time", "exit_time"]
OPTIONAL_COLUMNS = ["width_mm", "thickness_mm", "start_time", "proc_end_time",
                    "equipment", "reason_code", "due_date"]
ALL_COLUMNS = ["heat_no", "grade", "width_mm", "thickness_mm", "stage",
               "enter_time", "start_time", "proc_end_time", "exit_time",
               "equipment", "reason_code", "due_date"]
TIME_COLUMNS = ["enter_time", "start_time", "proc_end_time", "exit_time", "due_date"]

_STAGE_LOOKUP = {s.id: s.id for s in STAGES}
_STAGE_LOOKUP.update({s.label: s.id for s in STAGES})

_BREAKDOWN_REASONS = ["설비점검", "래들지연", "온도조정", "크레인대기"]
_PROC_MINUTES = 6  # proc 1스텝당 기준 처리시간(분)


# ══════════════════════════════════════════════════════════════
#  샘플 생성 (A2) — 용량 경합·블로킹·전환 셋업을 모델링해
#                    원인 분석(C)이 의미 있게 나오도록 함
# ══════════════════════════════════════════════════════════════
def generate_sample_event_log(n_heats: int = 120, start: str = "2026-06-01 06:00",
                              interarrival_min: float = 21.0, seed: int = 42) -> pd.DataFrame:
    rng = random.Random(seed)
    t0 = pd.Timestamp(start)
    grade_ids = [g.id for g in GRADES]
    route_of = {g.id: g.route for g in GRADES}
    weights = [0.34, 0.4, 0.26]

    free: dict[str, list[pd.Timestamp]] = {}
    last_job: dict[tuple, tuple] = {}  # (stage, slot) -> (grade, width)
    for s in STAGES:
        cap = 1 if s.cap == float("inf") else int(s.cap)
        free[s.id] = [t0] * cap

    def earliest_slot(sid: str) -> int:
        return min(range(len(free[sid])), key=lambda k: free[sid][k])

    rows = []
    for i in range(1, n_heats + 1):
        heat = f"H{i:04d}"
        grade = rng.choices(grade_ids, weights)[0]
        width = rng.choice([1000, 1050, 1250, 1450, 1500, 1550, 1600])
        thick = rng.randint(200, 300)
        arrival = t0 + pd.Timedelta(minutes=interarrival_min * (i - 1) + rng.uniform(-2, 2))
        due = arrival + pd.Timedelta(hours=rng.uniform(4, 10))
        route = stages_for(route_of[grade])
        ready = arrival
        for idx, sid in enumerate(route):
            stg = STAGE_BY_ID[sid]
            infinite = stg.cap == float("inf")
            enter = ready
            slot = 0 if infinite else earliest_slot(sid)
            start_t = ready if infinite else max(ready, free[sid][slot])

            proc = _PROC_MINUTES * stg.proc * rng.uniform(0.85, 1.25)
            reason = ""
            # 연주기(몰드) 전환 셋업 — 강종/폭 변경 시 처리시간 증가
            if sid == "mold" and not infinite:
                prev = last_job.get((sid, slot))
                if prev is not None and prev[0] != grade:
                    proc += rng.uniform(6, 12); reason = "강종전환셋업"
                elif prev is not None and abs(prev[1] - width) > 200:
                    proc += rng.uniform(3, 7); reason = "폭변경셋업"
            # 간헐 설비/공정 지연
            if rng.random() < 0.05:
                proc += rng.uniform(8, 25)
                reason = reason or rng.choice(_BREAKDOWN_REASONS)

            proc_end = start_t + pd.Timedelta(minutes=proc)
            # 블로킹 — 턴디시는 처리 완료 후 몰드가 빌 때까지 반출 대기(긴밀 결합).
            # 그 외 공정은 처리 완료 즉시 다음 버퍼로 이동(대기는 각 공정 큐에서 발생).
            if sid == "tundish":
                move = max(proc_end, free["mold"][earliest_slot("mold")])
            else:
                move = proc_end
            exit_t = move
            if not infinite:
                free[sid][slot] = exit_t
                last_job[(sid, slot)] = (grade, width)

            rows.append({
                "heat_no": heat, "grade": grade, "width_mm": width, "thickness_mm": thick,
                "stage": sid, "enter_time": enter, "start_time": start_t,
                "proc_end_time": proc_end, "exit_time": exit_t,
                "equipment": f"{sid.upper()}-{slot + 1}", "reason_code": reason, "due_date": due,
            })
            ready = exit_t
    return pd.DataFrame(rows, columns=ALL_COLUMNS)


# ══════════════════════════════════════════════════════════════
#  로드 & 검증 (A1)
# ══════════════════════════════════════════════════════════════
def load_event_log(source: Union[str, io.IOBase, pd.DataFrame]) -> pd.DataFrame:
    df = source.copy() if isinstance(source, pd.DataFrame) else pd.read_csv(source)
    for col in TIME_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "stage" in df.columns:
        df["stage"] = df["stage"].map(lambda v: _STAGE_LOOKUP.get(str(v).strip(), v))
    return df


def validate(df: pd.DataFrame) -> list[dict]:
    issues: list[dict] = []
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        issues.append({"level": "error", "msg": f"필수 컬럼 누락: {missing}"})
        return issues
    n = len(df)
    for col in ("enter_time", "exit_time"):
        nulls = int(df[col].isna().sum())
        if nulls:
            issues.append({"level": "warn", "msg": f"{col} 파싱 실패/결측 {nulls}건"})
    bad = int((df["exit_time"] < df["enter_time"]).sum())
    if bad:
        issues.append({"level": "error", "msg": f"exit_time < enter_time 인 행 {bad}건"})
    unknown = sorted(set(df["stage"]) - set(s.id for s in STAGES))
    if unknown:
        issues.append({"level": "warn", "msg": f"미정의 공정(stage): {unknown}"})
    has_decomp = {"start_time", "proc_end_time"}.issubset(df.columns)
    if not has_decomp:
        issues.append({"level": "info",
                       "msg": "start_time/proc_end_time 없음 → 대기·블로킹 분해 불가(체류시간만 분석)"})
    if not any(i["level"] in ("error", "warn") for i in issues):
        issues.append({"level": "info", "msg": f"검증 통과 · {n}행 · heat {df['heat_no'].nunique()}건"})
    return issues


def has_decomposition(df: pd.DataFrame) -> bool:
    return {"start_time", "proc_end_time"}.issubset(df.columns) \
        and df["start_time"].notna().any() and df["proc_end_time"].notna().any()


# ══════════════════════════════════════════════════════════════
#  파생 지표 (B: 가시화)
# ══════════════════════════════════════════════════════════════
def with_dwell(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dwell_min"] = (out["exit_time"] - out["enter_time"]).dt.total_seconds() / 60
    return out


def lead_times(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("heat_no")
    lead = (g["exit_time"].max() - g["enter_time"].min()).dt.total_seconds() / 60
    return pd.DataFrame({"heat_no": lead.index, "grade": g["grade"].first().values,
                         "lead_min": lead.values})


def _stage_order(series: pd.Series) -> pd.Series:
    order = {s.id: i for i, s in enumerate(STAGES)}
    return series.map(order).fillna(999)


def stage_dwell(df: pd.DataFrame) -> pd.DataFrame:
    d = with_dwell(df)
    agg = d.groupby("stage")["dwell_min"].agg(["mean", "median", "count"]).reset_index()
    agg["label"] = agg["stage"].map(lambda s: STAGE_BY_ID[s].label if s in STAGE_BY_ID else s)
    return agg.sort_values("stage", key=_stage_order).reset_index(drop=True)


def bottleneck_ranking(df: pd.DataFrame) -> pd.DataFrame:
    return stage_dwell(df).sort_values("mean", ascending=False).reset_index(drop=True)


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


def grade_mix(df: pd.DataFrame) -> pd.DataFrame:
    """강종 믹스 — heat 기준 강종 분포."""
    m = df.drop_duplicates("heat_no").groupby("grade").size().reset_index(name="count")
    return m.sort_values("count", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
#  원인 분석 (C: Diagnostic)
# ══════════════════════════════════════════════════════════════
def decompose(df: pd.DataFrame) -> pd.DataFrame:
    """대기/처리/블로킹 분해 (start_time·proc_end_time 필요)."""
    d = df.copy()
    mins = lambda a, b: (d[a] - d[b]).dt.total_seconds() / 60
    d["wait_min"] = mins("start_time", "enter_time").clip(lower=0)
    d["proc_min"] = mins("proc_end_time", "start_time").clip(lower=0)
    d["block_min"] = mins("exit_time", "proc_end_time").clip(lower=0)
    return d


def time_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """공정별 평균 대기/처리/블로킹(heat당 분)."""
    d = decompose(df)
    agg = d.groupby("stage")[["wait_min", "proc_min", "block_min"]].mean().reset_index()
    agg["label"] = agg["stage"].map(lambda s: STAGE_BY_ID[s].label if s in STAGE_BY_ID else s)
    return agg.sort_values("stage", key=_stage_order).reset_index(drop=True)


def blocking_by_cause(df: pd.DataFrame) -> pd.DataFrame:
    """각 공정이 '유발한' 하류 블로킹 총량(분). block at S 는 다음 공정 S+1 이 원인."""
    d = decompose(df).sort_values(["heat_no", "enter_time"])
    causer_total: dict[str, float] = {}
    for _, g in d.groupby("heat_no"):
        stages_seq = g["stage"].tolist()
        blocks = g["block_min"].tolist()
        for k in range(len(stages_seq) - 1):
            causer = stages_seq[k + 1]  # 다음 공정이 자리 없어 막음
            causer_total[causer] = causer_total.get(causer, 0.0) + blocks[k]
    rows = [{"stage": s, "label": STAGE_BY_ID[s].label if s in STAGE_BY_ID else s,
             "block_caused_min": v} for s, v in causer_total.items()]
    out = pd.DataFrame(rows)
    return out.sort_values("block_caused_min", ascending=False).reset_index(drop=True) if len(out) else out


def utilization(df: pd.DataFrame) -> pd.DataFrame:
    """공정별 설비 가동률(%) = Σ처리시간 / (관측기간 × 용량). 낮으면 상류 공급부족(starving) 신호."""
    d = decompose(df)
    span_min = (df["exit_time"].max() - df["enter_time"].min()).total_seconds() / 60
    rows = []
    for s in STAGES:
        sub = d[d["stage"] == s.id]
        if sub.empty:
            continue
        cap = 1 if s.cap == float("inf") else int(s.cap)
        util = sub["proc_min"].sum() / (span_min * cap) * 100 if span_min > 0 else 0
        rows.append({"stage": s.id, "label": s.label, "util_pct": min(util, 100.0)})
    return pd.DataFrame(rows)


def reason_impact(df: pd.DataFrame) -> pd.DataFrame:
    """사유코드별 지연 기여 — 사유가 있는 방문의 (처리시간 - 공정 정상치) 합(분)."""
    d = decompose(df)
    nominal = d[d["reason_code"].fillna("") == ""].groupby("stage")["proc_min"].median()
    rows = []
    delayed = d[d["reason_code"].fillna("") != ""]
    for reason, g in delayed.groupby("reason_code"):
        excess = (g["proc_min"] - g["stage"].map(nominal).fillna(0)).clip(lower=0).sum()
        rows.append({"reason_code": reason, "delay_min": excess, "count": len(g)})
    out = pd.DataFrame(rows)
    return out.sort_values("delay_min", ascending=False).reset_index(drop=True) if len(out) else out


def bottleneck_heatmap(df: pd.DataFrame, freq: str = "1h") -> pd.DataFrame:
    """시간대(행 방향은 공정) × 시간버킷 평균 체류시간 피벗 — 병목이 시간대별로
    어떻게 이동하는지 히트맵용. 값 단위: 분."""
    d = with_dwell(df).copy()
    d["bucket"] = d["enter_time"].dt.floor(freq)
    piv = d.pivot_table(index="stage", columns="bucket", values="dwell_min", aggfunc="mean")
    order = [s.id for s in STAGES if s.id in piv.index]
    piv = piv.reindex(order)
    piv.index = [STAGE_BY_ID[s].label for s in piv.index]
    return piv


def utilization_timeline(df: pd.DataFrame, freq: str = "2h") -> pd.DataFrame:
    """유한 용량 공정의 시간대별 가동률(%) 롱포맷 (bucket, label, util)."""
    d = decompose(df).copy()
    d["bucket"] = d["start_time"].dt.floor(freq)
    bucket_min = pd.Timedelta(freq).total_seconds() / 60
    rows = []
    for s in STAGES:
        if s.cap == float("inf"):
            continue
        sub = d[d["stage"] == s.id]
        for bkt, busy in sub.groupby("bucket")["proc_min"].sum().items():
            rows.append({"bucket": bkt, "label": s.label,
                         "util": min(busy / (bucket_min * s.cap) * 100, 100.0)})
    return pd.DataFrame(rows)


def equipment_states(df: pd.DataFrame) -> pd.DataFrame:
    """설비 시간 상태 분해(%) — 가동/블로킹/유휴(스타빙). 관측기간×용량 기준."""
    d = decompose(df)
    span_min = (df["exit_time"].max() - df["enter_time"].min()).total_seconds() / 60
    rows = []
    for s in STAGES:
        if s.cap == float("inf"):
            continue
        sub = d[d["stage"] == s.id]
        if sub.empty or span_min <= 0:
            continue
        avail = span_min * s.cap
        busy = sub["proc_min"].sum()
        blocked = sub["block_min"].sum()
        idle = max(avail - busy - blocked, 0.0)
        rows.append({"stage": s.id, "label": s.label,
                     "가동": busy / avail * 100, "블로킹": blocked / avail * 100,
                     "유휴/스타빙": idle / avail * 100})
    out = pd.DataFrame(rows)
    return out.sort_values("stage", key=_stage_order).reset_index(drop=True) if len(out) else out


def period_trend(df: pd.DataFrame) -> Optional[dict]:
    """관측 구간을 전·후반으로 나눠 평균 리드타임 추세(시간) 반환."""
    lead = lead_times(df).set_index("heat_no")
    t0 = df.sort_values("enter_time").groupby("heat_no")["enter_time"].first()
    lead["t0"] = t0
    lead = lead.dropna(subset=["t0"]).sort_values("t0")
    n = len(lead)
    if n < 4:
        return None
    return {"early": lead.iloc[:n // 2]["lead_min"].mean() / 60,
            "late": lead.iloc[n // 2:]["lead_min"].mean() / 60}


def transition_effect(df: pd.DataFrame, stage: str = "mold") -> Optional[pd.DataFrame]:
    """특정 공정에서 강종 전환 여부에 따른 평균 처리시간 비교(세트업 영향)."""
    d = decompose(df)
    sub = d[d["stage"] == stage].copy()
    if sub.empty:
        return None
    sub = sub.sort_values(["equipment", "start_time"])
    sub["prev_grade"] = sub.groupby("equipment")["grade"].shift()
    sub = sub.dropna(subset=["prev_grade"])
    sub["구분"] = (sub["grade"] != sub["prev_grade"]).map({True: "강종 전환", False: "동일 강종"})
    agg = sub.groupby("구분")["proc_min"].agg(["mean", "count"]).reset_index()
    return agg


if __name__ == "__main__":
    sample = generate_sample_event_log()
    sample.to_csv("data/sample_event_log.csv", index=False)
    print(f"wrote data/sample_event_log.csv  ({len(sample)} rows, "
          f"{sample['heat_no'].nunique()} heats)")
