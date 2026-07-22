"""시뮬레이션 엔진 — 체류시간(proc) + 용량(cap) 기반 결정적 모델.

legacy/cpn_slab.html 의 step() 엔진을 파이썬으로 이식한 것으로, 토큰(슬래브)은
"처리 완료 + 다음 Place에 여유가 있을 때"만 전진하며, 단일 설비(cap=1) 포화 시
상류 토큰이 블로킹되어 실제 병목을 재현합니다.

향후 확장(현업 인터뷰 후):
- optimization.py: 목적함수·제약(시퀀싱/배정/스케줄) — docs/OPTIMIZATION_SPEC.md
- 필요 시 SimPy 기반 이산사건 모델로 대체 가능(인터페이스 유지)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .model import GRADES, GRADE_BY_ID, STAGE_BY_ID, STAGES, stages_for


@dataclass
class Config:
    max_wip: int = 6
    auto_arrival: bool = True
    arrival_prob: float = 0.45
    bottleneck_threshold: int = 2
    thick_min: int = 200
    thick_max: int = 300
    seed: Optional[int] = 42


@dataclass
class Slab:
    id: int
    heat_no: str
    grade: str
    thick: int
    route: str
    stages: list[str]
    stage_idx: int = 0
    remaining: int = 0
    start_time: int = 0
    entered_tick: int = 0
    blocked: bool = False

    @property
    def stage(self) -> str:
        return self.stages[self.stage_idx]


class Simulation:
    """스텝 기반 결정적 시뮬레이션. Streamlit 세션에 인스턴스를 보관해 사용."""

    def __init__(self, config: Optional[Config] = None):
        self.cfg = config or Config()
        self.reset()

    # ── 상태 ──────────────────────────────────────────────
    def reset(self) -> None:
        self.rng = random.Random(self.cfg.seed)
        self.slabs: list[Slab] = []
        self.done = 0
        self.sim_time = 0
        self.heat_seq = 1
        self.id_seq = 1
        self.completion_times: list[int] = []
        self.lead_by_grade: dict[str, list[int]] = {}
        self.dwell_by_stage: dict[str, list[int]] = {}
        self.manual_queue: list[tuple[str, Optional[int]]] = []
        self.history: list[dict] = []
        self.log: list[tuple[int, str, str]] = []

    # ── 헬퍼 ──────────────────────────────────────────────
    def occupancy(self, sid: str) -> int:
        return sum(1 for s in self.slabs if s.stage == sid)

    def _log(self, msg: str, level: str = "event") -> None:
        self.log.append((self.sim_time, level, msg))

    def _make_slab(self, grade_id: Optional[str] = None, thick: Optional[int] = None) -> Slab:
        g = GRADE_BY_ID.get(grade_id) if grade_id else None
        if g is None:
            g = self.rng.choice(GRADES)
        t = thick or self.rng.randint(self.cfg.thick_min, self.cfg.thick_max)
        heat = f"H{self.heat_seq:03d}"
        self.heat_seq += 1
        slab = Slab(
            id=self.id_seq, heat_no=heat, grade=g.id, thick=t, route=g.route,
            stages=list(stages_for(g.route)), remaining=STAGE_BY_ID["ld"].proc,
            start_time=self.sim_time, entered_tick=self.sim_time,
        )
        self.id_seq += 1
        return slab

    def enqueue_manual(self, grade_id: str, thick: Optional[int], qty: int) -> None:
        for _ in range(max(1, qty)):
            self.manual_queue.append((grade_id, thick))

    def clear_queue(self) -> None:
        self.manual_queue.clear()

    # ── 엔진 ──────────────────────────────────────────────
    def _arrivals(self) -> None:
        ld_cap = STAGE_BY_ID["ld"].cap
        if self.manual_queue and len(self.slabs) < self.cfg.max_wip and self.occupancy("ld") < ld_cap:
            grade_id, thick = self.manual_queue.pop(0)
            s = self._make_slab(grade_id, thick)
            self.slabs.append(s)
            self._log(f"[투입·수동] {s.heat_no} {s.grade} {s.thick}mm → 전로 OUT", "ok")
            return
        if (self.cfg.auto_arrival and len(self.slabs) < self.cfg.max_wip
                and self.rng.random() < self.cfg.arrival_prob):
            s = self._make_slab()
            self.slabs.append(s)
            self._log(f"[투입·자동] {s.heat_no} {s.grade} {s.thick}mm → 전로 OUT", "ok")

    def step(self) -> None:
        self.sim_time += 1
        self._arrivals()

        # 1) 처리 진행 — 체류시간 감소
        for s in self.slabs:
            if s.remaining > 0:
                s.remaining -= 1

        # 2) 이동 — 하류(뒤쪽)부터 처리해 용량을 먼저 비운다
        movers = sorted((s for s in self.slabs if s.remaining <= 0),
                        key=lambda s: -s.stage_idx)
        for s in movers:
            if s.stage_idx >= len(s.stages) - 1:
                continue  # 야드 도착분 → 완료 단계에서 처리
            cur, nxt = s.stage, s.stages[s.stage_idx + 1]
            if self.occupancy(nxt) < STAGE_BY_ID[nxt].cap:
                self.dwell_by_stage.setdefault(cur, []).append(self.sim_time - s.entered_tick)
                s.stage_idx += 1
                s.entered_tick = self.sim_time
                s.remaining = STAGE_BY_ID[nxt].proc
                s.blocked = False
                self._log(f"[이동] {s.heat_no} ({s.grade}) → {STAGE_BY_ID[nxt].label}")
                if nxt == "lf":
                    self._log("  ↳ Guard: grade=SUS304 → LF 경로", "ok")
                if nxt == "rh":
                    self._log("  ↳ Guard: grade=API5L → RH 탈가스", "ok")
                if nxt == "cooling" and s.thick < 230:
                    self._log(f"  ↳ 경고: 두께 {s.thick}mm 주의", "warn")
            else:
                s.blocked = True  # 다음 Place 만석 → 병목(블로킹)

        # 3) 완료 — 야드 도착 + 처리 완료
        done_now = [s for s in self.slabs if s.stage == "yard" and s.remaining <= 0]
        for s in done_now:
            lead = self.sim_time - s.start_time
            self.completion_times.append(lead)
            self.lead_by_grade.setdefault(s.grade, []).append(lead)
            self._log(f"[완료] {s.heat_no} 야드 입고 (리드타임 {lead}스텝)", "ok")
            self.done += 1
        self.slabs = [s for s in self.slabs if not (s.stage == "yard" and s.remaining <= 0)]

        self._sample()

    def run(self, n_steps: int) -> None:
        for _ in range(max(0, n_steps)):
            self.step()

    def _sample(self) -> None:
        row = {"t": self.sim_time, "wip": len(self.slabs), "done": self.done}
        for st in STAGES:
            row[f"occ_{st.id}"] = self.occupancy(st.id)
        self.history.append(row)

    # ── 지표 ──────────────────────────────────────────────
    def throughput(self, window: int = 30) -> float:
        if len(self.history) < 2:
            return 0.0
        win = self.history[-window:]
        dt = win[-1]["t"] - win[0]["t"]
        dd = win[-1]["done"] - win[0]["done"]
        return (dd / dt * 60) if dt > 0 else 0.0

    def avg_lead(self) -> Optional[float]:
        if not self.completion_times:
            return None
        return sum(self.completion_times) / len(self.completion_times)

    def bottleneck(self) -> tuple[Optional[str], Optional[str]]:
        """(Place 라벨, 사유) 또는 (None, None)."""
        blocked = [s.stage for s in self.slabs if s.blocked]
        if blocked:
            return STAGE_BY_ID[blocked[0]].label, "블로킹"
        occ: dict[str, int] = {}
        for s in self.slabs:
            occ[s.stage] = occ.get(s.stage, 0) + 1
        over = [k for k, v in occ.items() if v >= self.cfg.bottleneck_threshold]
        if over:
            return STAGE_BY_ID[over[0]].label, "대기 누적"
        return None, None
