"""CPN 슬래브 물류 가시화 — 연주 부문 (Streamlit).

기존 단일 HTML 프로토타입(legacy/cpn_slab.html)을 파이썬 웹으로 이식한 스켈레톤.
- 탭 1: 물류 시뮬레이션 (체류시간·용량 기반 결정적 엔진)
- 탭 2: 제약·최적화 **예시** (현업 인터뷰 설명용 데모) — docs/OPTIMIZATION_SPEC.md

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
from src import optimization as opt  # noqa: E402

st.set_page_config(page_title="CPN 슬래브 물류 — 연주 부문", page_icon="🏭", layout="wide")

ACCENT, ACCENT2, HOT = "#e05c1a", "#f0a05a", "#ff6b35"
SURFACE, BORDER, MUTED, STEEL = "#161b22", "#30363d", "#8b949e", "#4a9eff"
TRANSPARENT = "rgba(0,0,0,0)"


def cap_label(cap: float) -> str:
    return "∞" if cap == float("inf") else str(int(cap))


def get_sim() -> Simulation:
    if "sim" not in st.session_state:
        st.session_state.sim = Simulation(Config())
    return st.session_state.sim


# ══════════════════════════════════════════════════════════════
#  탭 1 — 물류 시뮬레이션
# ══════════════════════════════════════════════════════════════
def flow_dot(sim: Simulation) -> str:
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
        lines.append(
            f'  {stg.id} [label="{stg.label}\\n{occ}/{cap_label(stg.cap)}", '
            f'shape={shape}, fillcolor="{fill}"];')
    edges = [
        ("ld", "lf_wait", ""), ("lf_wait", "lf", ""), ("lf_wait", "rh", ""),
        ("lf_wait", "tundish", "style=dashed"), ("lf", "tundish", ""), ("rh", "tundish", ""),
        ("tundish", "mold", ""), ("mold", "cooling", ""), ("cooling", "yard", ""),
    ]
    for a, b, attr in edges:
        lines.append(f"  {a} -> {b} [{attr}];")
    lines.append("}")
    return "\n".join(lines)


def render_simulation(sim: Simulation) -> None:
    st.caption(f"전로(LD) → 정련(LF/RH) → 연속주조 → 야드 · 강종별 경로 자동 분기 · "
               f"경과 {sim.sim_time} 스텝")

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

    st.subheader("공정 흐름 — Place / 용량 점유")
    st.graphviz_chart(flow_dot(sim), use_container_width=True)

    left, right = st.columns(2)
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
            marker_color=[HOT if (c != float("inf") and o >= c and o > 0) else STEEL
                          for o, c in zip(occ_vals, cap_vals)],
            text=[f"{o}/{cap_label(c)}" for o, c in zip(occ_vals, cap_vals)],
            textposition="outside"))
        fig_occ.update_layout(height=280, margin=dict(l=0, r=40, t=10, b=0),
                              paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT,
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
                                  paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT,
                                  font_color="#e6edf3", xaxis_title="스텝", yaxis_title="WIP")
            st.plotly_chart(fig_wip, use_container_width=True)
        else:
            st.caption("실행하면 추이가 표시됩니다")

        st.subheader("강종별 평균 리드타임 (스텝)")
        lead_rows = [{
            "강종": g.id,
            "평균": (sum(sim.lead_by_grade.get(g.id, [])) / len(sim.lead_by_grade[g.id])
                    if sim.lead_by_grade.get(g.id) else 0),
            "완료수": len(sim.lead_by_grade.get(g.id, [])), "color": g.color,
        } for g in GRADES]
        ldf = pd.DataFrame(lead_rows)
        fig_lead = go.Figure(go.Bar(
            x=ldf["평균"], y=ldf["강종"], orientation="h", marker_color=ldf["color"],
            text=[f"{v:.1f}" if n else "—" for v, n in zip(ldf["평균"], ldf["완료수"])],
            textposition="outside"))
        fig_lead.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0),
                               paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT,
                               yaxis=dict(autorange="reversed"), font_color="#e6edf3")
        st.plotly_chart(fig_lead, use_container_width=True)

    with st.expander("📋 공정 이벤트 로그"):
        if sim.log:
            st.code("\n".join(f"{t:>3} | {msg}" for t, _l, msg in sim.log[-40:]), language=None)
        else:
            st.caption("로그 없음")


# ══════════════════════════════════════════════════════════════
#  탭 2 — 제약·최적화 예시 (인터뷰용 데모)
# ══════════════════════════════════════════════════════════════
def _seq_frame(res: opt.Result) -> pd.DataFrame:
    rows = []
    prev = None
    for i, h in enumerate(res.sequence, start=1):
        dw = "" if prev is None else f"{h.width - prev.width:+d}"
        chg = "↔" if (prev is not None and prev.grade != h.grade) else ""
        rows.append({"순서": i, "Heat": h.heat_no, "강종": f"{h.grade} {chg}",
                     "폭(mm)": h.width, "Δ폭": dw, "납기순번": h.due})
        prev = h
    return pd.DataFrame(rows)


def render_optimization() -> None:
    st.info(
        "⚠️ 아래 데이터·규칙·수치는 모두 **가정한 예시**입니다. 이 화면은 현업 인터뷰에서 "
        "\"최적화가 무엇을 하는지\"를 눈으로 보여 주기 위한 데모예요. 실제 목적·제약은 "
        "인터뷰로 확정해 `docs/OPTIMIZATION_SPEC.md`에 정리한 뒤 정식 solver(OR-Tools CP-SAT 등)로 "
        "대체합니다.")

    st.markdown("#### 예시 문제: 캐스트 시퀀싱 — 한 턴디시로 연속 주조할 heat 순서 정하기")

    c = st.columns(3)
    with c[0]:
        st.markdown("**목적(무엇을 최소화?)**")
        use_width = st.checkbox("폭 증가 최소화 (coffin rule)", value=True)
        use_grade = st.checkbox("강종 전환 최소화", value=True)
        use_due = st.checkbox("납기/우선순위 준수", value=True)
    with c[1]:
        st.markdown("**제약(예시)**")
        enforce_jump = st.checkbox("인접 폭 변화 상한 적용", value=True)
        max_jump = st.slider("폭 변화 상한 (mm)", 100, 700, 300, 50)
        st.caption("턴디시 수명(예시): 캐스트당 최대 8 heat")
    with c[2]:
        st.markdown("**가중치(예시)**")
        w_up = st.slider("폭 증가 페널티", 0.0, 10.0, 3.0, 0.5)
        w_grade = st.slider("강종 전환 페널티", 0.0, 120.0, 60.0, 10.0)
        w_due = st.slider("납기 위반 페널티", 0.0, 30.0, 8.0, 1.0)

    weights = opt.Weights(width_up=w_up, width_down=0.2, grade_change=w_grade, due=w_due)
    options = opt.Options(use_width=use_width, use_grade=use_grade, use_due=use_due,
                          enforce_max_jump=enforce_jump, max_width_jump=max_jump)

    base = opt.baseline(opt.EXAMPLE_HEATS, weights, options)
    best = opt.optimize(opt.EXAMPLE_HEATS, weights, options)

    m = st.columns(4)
    m[0].metric("기준(입력) 총비용", f"{base.cost:.0f}")
    m[1].metric("최적 총비용", f"{best.cost:.0f}",
                delta=f"-{(base.cost - best.cost) / base.cost * 100:.0f}%" if base.cost else None,
                delta_color="inverse")
    m[2].metric("강종 전환 (기준→최적)",
                f"{opt.grade_changes(best.sequence)} 회",
                delta=f"{opt.grade_changes(best.sequence) - opt.grade_changes(base.sequence)} 회",
                delta_color="inverse")
    m[3].metric("하드 제약 충족", "가능" if best.feasible else "완화됨",
                delta=None, delta_color="off")

    st.subheader("폭 프로파일 — 기준 vs 최적")
    fig = go.Figure()
    x = list(range(1, len(base.sequence) + 1))
    fig.add_scatter(x=x, y=[h.width for h in base.sequence], mode="lines+markers",
                    name="기준(입력) 순서", line=dict(color=MUTED, dash="dot"),
                    marker=dict(color=[GRADE_BY_ID[h.grade].color for h in base.sequence], size=11))
    fig.add_scatter(x=x, y=[h.width for h in best.sequence], mode="lines+markers",
                    name="최적 순서", line=dict(color=ACCENT2, width=2),
                    marker=dict(color=[GRADE_BY_ID[h.grade].color for h in best.sequence], size=13))
    fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0),
                      paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT, font_color="#e6edf3",
                      xaxis_title="주조 순서", yaxis_title="슬래브 폭(mm)",
                      legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("마커 색 = 강종. 최적 순서는 폭이 매끄럽게 감소(coffin)하고 강종 전환이 줄어듭니다.")

    s1, s2 = st.columns(2)
    with s1:
        st.markdown("**기준(입력) 순서**")
        st.dataframe(_seq_frame(base), use_container_width=True, hide_index=True)
    with s2:
        st.markdown("**최적 순서**")
        st.dataframe(_seq_frame(best), use_container_width=True, hide_index=True)

    with st.expander("🗣️ 인터뷰에서 이 화면으로 설명·질문할 것", expanded=True):
        st.markdown(
            "- **목적**: 우리가 실제로 최소/최대화하려는 건 무엇인가요? (폭 전이? 강종 전환? 납기? 처리량?)\n"
            "- **폭 전이 규칙**: 연속 슬래브 폭은 감소만 허용인가요? 증가 허용 시 상한(mm)은?\n"
            "- **강종 전환**: 전환 시 실제 setup 비용/시간은? 같은 cast에 섞을 수 있는 강종 범위는?\n"
            "- **턴디시 수명**: 캐스트당 최대 heat 수는 실제로 몇 개인가요?\n"
            "- **시간·온도 윈도우**: 출강 후 주조까지 허용 시간, 온도 하/상한은?\n"
            "- **납기/우선순위**: 긴급 주문·고객 우선순위 규칙이 있나요?\n\n"
            "→ 답변을 `docs/OPTIMIZATION_SPEC.md`에 채우면 이 예시를 실제 제약·목적으로 교체합니다.")


# ══════════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════════
sim = get_sim()

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
        format_func=lambda gid: f"{gid} · {GRADE_BY_ID[gid].label} ({GRADE_BY_ID[gid].route})")
    thick = st.number_input("두께(mm, 0=랜덤)", min_value=0, max_value=400, value=0, step=10)
    qty = st.number_input("수량", min_value=1, max_value=20, value=1)
    a1, a2 = st.columns(2)
    if a1.button("＋ 투입 예약", use_container_width=True):
        sim.enqueue_manual(grade_id, thick or None, int(qty))
    if a2.button("대기열 비우기", use_container_width=True):
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

st.markdown("###### COLORED PETRI NET · 연주 부문")
st.title("슬래브 물류 · 스케줄 최적화")

tab_sim, tab_opt = st.tabs(["🔄 물류 시뮬레이션", "🧩 제약·최적화 예시 (인터뷰용)"])
with tab_sim:
    render_simulation(sim)
with tab_opt:
    render_optimization()
