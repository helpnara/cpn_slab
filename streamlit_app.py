"""CPN 슬래브 물류 가시화 — 연주 부문 (Streamlit).

기존 단일 HTML 프로토타입(legacy/cpn_slab.html)을 파이썬 웹으로 이식한 스켈레톤.
현업 인터뷰로 정의될 최적화/제약(docs/OPTIMIZATION_SPEC.md)을 얹기 위한 기반입니다.

실행:  streamlit run streamlit_app.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.model import GRADES, GRADE_BY_ID, STAGES, STAGE_BY_ID, temp_for  # noqa: E402
from src.simulation import Config, Simulation  # noqa: E402

st.set_page_config(page_title="CPN 슬래브 물류 — 연주 부문", page_icon="🏭", layout="wide")

ACCENT = "#e05c1a"
ACCENT2 = "#f0a05a"
HOT = "#ff6b35"
SURFACE = "#161b22"
BORDER = "#30363d"
MUTED = "#8b949e"


def cap_label(cap: float) -> str:
    return "∞" if cap == float("inf") else str(int(cap))


def get_sim() -> Simulation:
    if "sim" not in st.session_state:
        st.session_state.sim = Simulation(Config())
    return st.session_state.sim


sim = get_sim()

# ── SIDEBAR: 입력부 ───────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ 파라미터")
    sim.cfg.auto_arrival = st.checkbox("자동 투입 사용", value=sim.cfg.auto_arrival)
    sim.cfg.arrival_prob = st.slider("자동 투입 확률", 0.0, 1.0, sim.cfg.arrival_prob, 0.05)
    sim.cfg.max_wip = st.slider("최대 WIP", 1, 12, sim.cfg.max_wip)
    sim.cfg.bottleneck_threshold = st.slider("병목 경보 임계", 1, 6, sim.cfg.bottleneck_threshold)

    st.divider()
    st.header("🎯 슬래브 투입")
    grade_id = st.selectbox(
        "강종", [g.id for g in GRADES],
        format_func=lambda gid: f"{gid} · {GRADE_BY_ID[gid].label} ({GRADE_BY_ID[gid].route})",
    )
    thick = st.number_input("두께(mm, 0=랜덤)", min_value=0, max_value=400, value=0, step=10)
    qty = st.number_input("수량", min_value=1, max_value=20, value=1)
    c1, c2 = st.columns(2)
    if c1.button("＋ 투입 예약", use_container_width=True):
        sim.enqueue_manual(grade_id, thick or None, int(qty))
    if c2.button("대기열 비우기", use_container_width=True):
        sim.clear_queue()
    if sim.manual_queue:
        counts: dict[str, int] = {}
        for g, t in sim.manual_queue:
            counts[f"{g} {t or '랜덤'}"] = counts.get(f"{g} {t or '랜덤'}", 0) + 1
        st.caption("대기열: " + ", ".join(f"{k}×{v}" for k, v in counts.items()))
    else:
        st.caption("투입 대기열 비어 있음")

    st.divider()
    st.header("▶ 실행")
    n_steps = st.number_input("실행 스텝 수", min_value=1, max_value=200, value=20)
    r1, r2, r3 = st.columns(3)
    if r1.button(f"▶ {int(n_steps)}스텝", use_container_width=True):
        sim.run(int(n_steps))
    if r2.button("＋1", use_container_width=True):
        sim.step()
    if r3.button("↺ 초기화", use_container_width=True):
        sim.reset()

# ── HEADER ────────────────────────────────────────────────────
st.markdown("###### COLORED PETRI NET · 연주 부문")
st.title("슬래브 물류 시뮬레이션")
st.caption(f"전로(LD) → 정련(LF/RH) → 연속주조 → 야드 · 강종별 경로 자동 분기 · "
           f"경과 {sim.sim_time} 스텝")

# ── KPI ───────────────────────────────────────────────────────
bn_name, bn_reason = sim.bottleneck()
avg = sim.avg_lead()
k = st.columns(5)
k[0].metric("야드 입고", f"{sim.done} 개")
k[1].metric("공정 중 WIP", f"{len(sim.slabs)} 개")
k[2].metric("병목 경보", "정상" if not bn_name else "경보",
            delta=(bn_name and f"{bn_name} {bn_reason}") or "전 공정 순조",
            delta_color="inverse" if bn_name else "off")
k[3].metric("평균 리드타임", "—" if avg is None else f"{avg:.1f} 스텝")
k[4].metric("처리량", f"{sim.throughput():.1f} 개/60스텝")

# ── FLOW DIAGRAM (Graphviz) ───────────────────────────────────
st.subheader("공정 흐름 — Place / 용량 점유")


def flow_dot() -> str:
    lines = [
        "digraph G {",
        "  rankdir=LR; bgcolor=\"transparent\"; pad=0.2; nodesep=0.4; ranksep=0.6;",
        f"  node [style=filled, fontname=\"sans-serif\", fontsize=10, color=\"{BORDER}\", "
        f"fontcolor=\"#e6edf3\"];",
        f"  edge [color=\"{MUTED}\", arrowsize=0.7];",
    ]
    for stg in STAGES:
        occ = sim.occupancy(stg.id)
        full = stg.cap != float("inf") and occ >= stg.cap and occ > 0
        fill = HOT if full else (ACCENT if occ > 0 else SURFACE)
        shape = "doublecircle" if stg.id in ("ld", "yard") else "circle"
        label = f"{stg.label}\\n{occ}/{cap_label(stg.cap)}"
        lines.append(f'  {stg.id} [label="{label}", shape={shape}, fillcolor="{fill}"];')
    edges = [
        ("ld", "lf_wait", ""), ("lf_wait", "lf", ""), ("lf_wait", "rh", ""),
        ("lf_wait", "tundish", "style=dashed"), ("lf", "tundish", ""), ("rh", "tundish", ""),
        ("tundish", "mold", ""), ("mold", "cooling", ""), ("cooling", "yard", ""),
    ]
    for a, b, attr in edges:
        lines.append(f"  {a} -> {b} [{attr}];")
    lines.append("}")
    return "\n".join(lines)


st.graphviz_chart(flow_dot(), use_container_width=True)

# ── CHARTS + TABLES ───────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
    st.subheader("현재 공정 내 슬래브 (토큰)")
    if sim.slabs:
        rows = [{
            "Heat": s.heat_no, "강종": s.grade, "두께(mm)": s.thick,
            "위치": STAGE_BY_ID[s.stage].label, "잔여": s.remaining,
            "온도(℃)": temp_for(s.stage, sim.rng), "병목": "⚠️" if s.blocked else "",
        } for s in sim.slabs]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=260)
    else:
        st.caption("공정 내 슬래브 없음 — 사이드바에서 실행하세요")

    st.subheader("Place별 점유 / 용량")
    labels = [stg.label for stg in STAGES]
    occ_vals = [sim.occupancy(stg.id) for stg in STAGES]
    cap_vals = [stg.cap for stg in STAGES]
    fig_occ = go.Figure(go.Bar(
        x=occ_vals, y=labels, orientation="h",
        marker_color=[HOT if (c != float("inf") and o >= c and o > 0) else "#4a9eff"
                      for o, c in zip(occ_vals, cap_vals)],
        text=[f"{o}/{cap_label(c)}" for o, c in zip(occ_vals, cap_vals)],
        textposition="outside",
    ))
    fig_occ.update_layout(height=280, margin=dict(l=0, r=40, t=10, b=0),
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                          yaxis=dict(autorange="reversed"), font_color="#e6edf3",
                          xaxis=dict(range=[0, max(max(occ_vals, default=0), 1) + 0.8]))
    st.plotly_chart(fig_occ, use_container_width=True)

with right:
    st.subheader("WIP 추이")
    if len(sim.history) >= 2:
        h = pd.DataFrame(sim.history)
        fig_wip = go.Figure(go.Scatter(x=h["t"], y=h["wip"], mode="lines",
                                       fill="tozeroy", line_color=ACCENT2))
        fig_wip.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0),
                              paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                              font_color="#e6edf3", xaxis_title="스텝", yaxis_title="WIP")
        st.plotly_chart(fig_wip, use_container_width=True)
    else:
        st.caption("실행하면 추이가 표시됩니다")

    st.subheader("강종별 평균 리드타임 (스텝)")
    lead_rows = []
    for g in GRADES:
        arr = sim.lead_by_grade.get(g.id, [])
        lead_rows.append({"강종": g.id, "평균": (sum(arr) / len(arr) if arr else 0),
                          "완료수": len(arr), "color": g.color})
    ldf = pd.DataFrame(lead_rows)
    fig_lead = go.Figure(go.Bar(x=ldf["평균"], y=ldf["강종"], orientation="h",
                                marker_color=ldf["color"],
                                text=[f"{v:.1f}" if n else "—" for v, n in zip(ldf["평균"], ldf["완료수"])],
                                textposition="outside"))
    fig_lead.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           yaxis=dict(autorange="reversed"), font_color="#e6edf3")
    st.plotly_chart(fig_lead, use_container_width=True)

# ── LOG ───────────────────────────────────────────────────────
with st.expander("📋 공정 이벤트 로그", expanded=False):
    if sim.log:
        txt = "\n".join(f"{t:>3} | {msg}" for t, _lvl, msg in sim.log[-40:])
        st.code(txt, language=None)
    else:
        st.caption("로그 없음")

# ── 최적화/제약 (예정) ────────────────────────────────────────
st.divider()
st.subheader("🧩 제약 · 최적화 (예정)")
st.info(
    "현업 인터뷰로 정의될 **제약 규칙**과 **최적화 목적**이 이 영역에 연결됩니다. "
    "`docs/OPTIMIZATION_SPEC.md` 를 채우면 `src/optimization.py`(예: OR-Tools CP-SAT)로 "
    "옮겨, 위 시뮬레이션과 결합한 스케줄 최적화·검증 화면을 추가합니다."
)
