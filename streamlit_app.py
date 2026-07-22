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

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from src.model import GRADES, GRADE_BY_ID, STAGES, STAGE_BY_ID, temp_for  # noqa: E402
from src.simulation import Config, Simulation  # noqa: E402
from src import optimization as opt  # noqa: E402
from src import data as datamod  # noqa: E402
from src import whatif as wi  # noqa: E402

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
#  탭 3 — 과거 데이터 (실데이터 가시화 · A1/A2)
# ══════════════════════════════════════════════════════════════
def render_data() -> None:
    st.caption("과거 이벤트 로그(표준 스키마)를 불러와 물류를 가시화하고 병목 후보를 찾습니다 "
               "— 실데이터 연동 전 형식 확정·데이터 감사를 위한 A1·A2 단계.")

    choice = st.radio("데이터 소스", ["샘플 데이터", "CSV 업로드"], horizontal=True)
    if choice == "CSV 업로드":
        up = st.file_uploader("이벤트 로그 CSV", type=["csv"])
        if up is None:
            st.info("CSV를 업로드하거나 '샘플 데이터'를 선택하세요. "
                    "필수 컬럼: heat_no, grade, stage, enter_time, exit_time "
                    "(선택: width_mm, thickness_mm, equipment, reason_code, due_date)")
            return
        df = datamod.load_event_log(up)
    else:
        df = datamod.load_event_log(os.path.join(APP_DIR, "data", "sample_event_log.csv"))

    issues = datamod.validate(df)
    has_error = any(i["level"] == "error" for i in issues)
    with st.expander(f"🔍 데이터 감사 결과 ({len(issues)}건)", expanded=has_error):
        for it in issues:
            {"error": st.error, "warn": st.warning, "info": st.caption}[it["level"]](it["msg"])
    if has_error:
        return

    tmin, tmax = df["enter_time"].min(), df["exit_time"].max()
    f = st.columns([2, 2])
    with f[0]:
        dr = st.date_input("기간", (tmin.date(), tmax.date()),
                           min_value=tmin.date(), max_value=tmax.date())
    with f[1]:
        gsel = st.multiselect("강종", sorted(df["grade"].unique()),
                              default=sorted(df["grade"].unique()))
    if isinstance(dr, (tuple, list)) and len(dr) == 2:
        d0, d1 = pd.Timestamp(dr[0]), pd.Timestamp(dr[1]) + pd.Timedelta(days=1)
        df = df[(df["enter_time"] >= d0) & (df["enter_time"] < d1)]
    if gsel:
        df = df[df["grade"].isin(gsel)]
    if df.empty:
        st.warning("선택 조건에 해당하는 데이터가 없습니다.")
        return

    lead = datamod.lead_times(df)
    m = st.columns(4)
    m[0].metric("heat 수", f"{df['heat_no'].nunique()}")
    m[1].metric("이벤트(행)", f"{len(df)}")
    m[2].metric("평균 리드타임", f"{lead['lead_min'].mean() / 60:.1f} h")
    span_h = (df["exit_time"].max() - df["enter_time"].min()).total_seconds() / 3600
    m[3].metric("관측 기간", f"{span_h:.0f} h")

    st.subheader("🚧 병목 후보 — 설비별 평균 체류시간")
    bn = datamod.bottleneck_ranking(df)
    top = bn.iloc[0]["label"] if len(bn) else None
    fig_bn = go.Figure(go.Bar(
        x=bn["mean"], y=bn["label"], orientation="h",
        marker_color=[HOT if lbl == top else STEEL for lbl in bn["label"]],
        text=[f"{v:.0f}분 (n={int(n)})" for v, n in zip(bn["mean"], bn["count"])],
        textposition="outside"))
    fig_bn.update_layout(height=300, margin=dict(l=0, r=70, t=10, b=0), paper_bgcolor=TRANSPARENT,
                         plot_bgcolor=TRANSPARENT, yaxis=dict(autorange="reversed"),
                         font_color="#e6edf3")
    st.plotly_chart(fig_bn, use_container_width=True)
    if top:
        st.caption(f"평균 체류시간이 가장 긴 공정: **{top}** → 다음 단계(C. 원인 분석) 최우선 후보")

    left, right = st.columns(2)
    with left:
        st.subheader("WIP 추이 (시간축)")
        wip = datamod.wip_timeline(df)
        fig_wip = go.Figure(go.Scatter(x=wip["t"], y=wip["wip"], mode="lines",
                                       fill="tozeroy", line_color=ACCENT2))
        fig_wip.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor=TRANSPARENT,
                              plot_bgcolor=TRANSPARENT, font_color="#e6edf3", yaxis_title="WIP")
        st.plotly_chart(fig_wip, use_container_width=True)
    with right:
        st.subheader("강종별 평균 리드타임 (시간)")
        lg = lead.groupby("grade")["lead_min"].mean().reset_index()
        fig_lg = go.Figure(go.Bar(
            x=lg["grade"], y=lg["lead_min"] / 60,
            marker_color=[GRADE_BY_ID[g].color if g in GRADE_BY_ID else STEEL for g in lg["grade"]],
            text=[f"{v / 60:.1f}h" for v in lg["lead_min"]], textposition="outside"))
        fig_lg.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor=TRANSPARENT,
                             plot_bgcolor=TRANSPARENT, font_color="#e6edf3")
        st.plotly_chart(fig_lg, use_container_width=True)

    with st.expander("데이터 미리보기 (상위 20행)"):
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
#  탭 — 원인 분석 (C: Diagnostic)
# ══════════════════════════════════════════════════════════════
def render_cause() -> None:
    st.caption("샘플 과거 로그 기준 — 병목의 원인을 대기/처리/블로킹 분해·가동률·사유코드·강종 전환으로 "
               "진단합니다 (C. 원인 분석). 실데이터도 동일 스키마로 분석됩니다.")
    df = datamod.load_event_log(os.path.join(APP_DIR, "data", "sample_event_log.csv"))
    if not datamod.has_decomposition(df):
        st.warning("start_time·proc_end_time 가 없어 대기/블로킹 분해가 불가합니다(체류시간만 분석 가능).")
        return

    util = datamod.utilization(df)
    bd = datamod.time_breakdown(df)
    cause = datamod.blocking_by_cause(df)
    reasons = datamod.reason_impact(df)
    trans = datamod.transition_effect(df)

    top_util = util.sort_values("util_pct", ascending=False).iloc[0]
    bd = bd.assign(total=bd[["wait_min", "proc_min", "block_min"]].sum(axis=1))
    top_dwell = bd.sort_values("total", ascending=False).iloc[0]
    top_reason = reasons.iloc[0] if len(reasons) else None

    c = st.columns(3)
    c[0].metric("병목 설비 (가동률)", top_util["label"], delta=f"{top_util['util_pct']:.0f}%",
                delta_color="off")
    c[1].metric("최장 체류 공정", top_dwell["label"], delta=f"{top_dwell['total']:.0f} 분/heat",
                delta_color="off")
    if top_reason is not None:
        c[2].metric("최대 지연 사유", top_reason["reason_code"],
                    delta=f"{top_reason['delay_min']:.0f} 분", delta_color="off")

    blocker = cause.iloc[0] if len(cause) else None
    if blocker is not None and blocker["block_caused_min"] > 0:
        st.error(f"🎯 근본 원인 추정: **{top_util['label']}**(가동률 {top_util['util_pct']:.0f}%)가 포화되어 "
                 f"상류에 블로킹을 유발 — 블로킹 유발 1위 **{blocker['label']}** "
                 f"({blocker['block_caused_min']:.0f}분).")

    st.subheader("① 체류시간 분해 — 대기 / 처리 / 블로킹 (heat당 평균)")
    fig = go.Figure()
    fig.add_bar(y=bd["label"], x=bd["wait_min"], name="대기(큐)", orientation="h", marker_color=ACCENT2)
    fig.add_bar(y=bd["label"], x=bd["proc_min"], name="처리", orientation="h", marker_color=STEEL)
    fig.add_bar(y=bd["label"], x=bd["block_min"], name="블로킹(하류 막힘)", orientation="h",
                marker_color=HOT)
    fig.update_layout(barmode="stack", height=320, margin=dict(l=0, r=0, t=10, b=0),
                      paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT, font_color="#e6edf3",
                      yaxis=dict(autorange="reversed"), xaxis_title="분/heat",
                      legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("‘블로킹’은 처리를 마쳤지만 하류가 막혀 반출 못 한 시간 — 턴디시 블로킹의 원인은 몰드.")

    lft, rgt = st.columns(2)
    with lft:
        st.subheader("② 설비 가동률")
        umax = util["util_pct"].max()
        fig_u = go.Figure(go.Bar(
            x=util["util_pct"], y=util["label"], orientation="h",
            marker_color=[HOT if v == umax else STEEL for v in util["util_pct"]],
            text=[f"{v:.0f}%" for v in util["util_pct"]], textposition="outside"))
        fig_u.update_layout(height=300, margin=dict(l=0, r=40, t=10, b=0), paper_bgcolor=TRANSPARENT,
                            plot_bgcolor=TRANSPARENT, font_color="#e6edf3",
                            yaxis=dict(autorange="reversed"), xaxis=dict(range=[0, 110]))
        st.plotly_chart(fig_u, use_container_width=True)
        st.caption("가동률이 낮은 공정은 병목에 막혀 놀고 있음(starving) — 포화된 몰드가 전체를 제약.")
    with rgt:
        st.subheader("③ 사유코드별 지연 기여 (분)")
        fig_r = go.Figure(go.Bar(
            x=reasons["delay_min"], y=reasons["reason_code"], orientation="h", marker_color=ACCENT,
            text=[f"{v:.0f}분 (n={int(n)})" for v, n in zip(reasons["delay_min"], reasons["count"])],
            textposition="outside"))
        fig_r.update_layout(height=300, margin=dict(l=0, r=70, t=10, b=0), paper_bgcolor=TRANSPARENT,
                            plot_bgcolor=TRANSPARENT, font_color="#e6edf3",
                            yaxis=dict(autorange="reversed"),
                            xaxis=dict(range=[0, reasons["delay_min"].max() * 1.25]))
        st.plotly_chart(fig_r, use_container_width=True)

    if trans is not None and len(trans) == 2:
        st.subheader("④ 강종 전환이 몰드 처리시간에 미치는 영향")
        fig_t = go.Figure(go.Bar(
            x=trans["구분"], y=trans["mean"],
            marker_color=[HOT if k == "강종 전환" else STEEL for k in trans["구분"]],
            text=[f"{m:.1f}분 (n={int(n)})" for m, n in zip(trans["mean"], trans["count"])],
            textposition="outside"))
        fig_t.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor=TRANSPARENT,
                            plot_bgcolor=TRANSPARENT, font_color="#e6edf3", yaxis_title="평균 처리시간(분)")
        st.plotly_chart(fig_t, use_container_width=True)

    st.success("💡 개선 시사점: 병목(몰드)의 최대 지연 원인은 **강종 전환 셋업**입니다. "
               "같은 강종을 묶어 주조 순서를 정하면(캐스트 시퀀싱) 전환을 줄여 병목을 완화할 수 있습니다 "
               "→ **‘제약·최적화 예시’ 탭**에서 그 효과를 확인하세요.")


# ══════════════════════════════════════════════════════════════
#  탭 — 개선 what-if (D: Prescriptive)
# ══════════════════════════════════════════════════════════════
def render_whatif() -> None:
    st.caption("C(원인 분석)의 결론 — 병목(몰드)의 최대 지연 원인은 강종 전환 — 을 받아, 같은 heat들을 "
               "주조 순서만 바꿔 개선 효과를 정량화합니다 (D. 개선 what-if). 결정론적 비교라 차이는 "
               "오롯이 ‘순서 결정’에서 옵니다.")
    df = datamod.load_event_log(os.path.join(APP_DIR, "data", "sample_event_log.csv"))
    window = st.slider("윈도우 크기 (도착 순서를 재배치하는 범위)", 4, 14, 8)
    r = wi.compare(df, window=window)
    b, w_, g = r["baseline"], r["windowed"], r["grouped"]

    st.markdown(f"#### 개선(윈도우 그룹핑, w={window}) — 기준 대비")
    m = st.columns(4)
    m[0].metric("강종 전환", f"{w_['grade_changes']:.0f} 회",
                delta=f"{w_['grade_changes'] - b['grade_changes']:.0f} 회", delta_color="inverse")
    m[1].metric("총 셋업", f"{w_['setup_min']:.0f} 분",
                delta=f"{w_['setup_min'] - b['setup_min']:.0f} 분", delta_color="inverse")
    m[2].metric("몰드 가동률", f"{w_['mold_util_pct']:.0f} %",
                delta=f"{w_['mold_util_pct'] - b['mold_util_pct']:.1f} %p", delta_color="inverse")
    m[3].metric("평균 리드타임", f"{w_['avg_lead_min']:.0f} 분",
                delta=f"{(w_['avg_lead_min'] - b['avg_lead_min']) / b['avg_lead_min'] * 100:.1f} %",
                delta_color="inverse")

    labels = {"grade_changes": "강종 전환(회)", "setup_min": "총 셋업(분)",
              "mold_util_pct": "몰드 가동률(%)", "avg_lead_min": "평균 리드타임(분)",
              "throughput_per_h": "처리량(개/h)", "wip_peak": "WIP 피크"}
    st.markdown("#### 정책별 KPI 비교")
    table = pd.DataFrame({
        "지표": list(labels.values()),
        "기준(도착순)": [round(b[k], 1) for k in labels],
        f"윈도우 그룹핑(w={window})": [round(w_[k], 1) for k in labels],
        "전체 그룹핑(상한)": [round(g[k], 1) for k in labels],
    })
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("#### 기준 대비(%) — 낮을수록 개선 (전환·셋업·가동률·리드타임)")
    keys = ["grade_changes", "setup_min", "mold_util_pct", "avg_lead_min"]
    knames = [labels[k] for k in keys]
    fig = go.Figure()
    fig.add_bar(x=knames, y=[w_[k] / b[k] * 100 for k in keys],
                name=f"윈도우 그룹핑(w={window})", marker_color=STEEL,
                text=[f"{w_[k] / b[k] * 100:.0f}" for k in keys], textposition="outside")
    fig.add_bar(x=knames, y=[g[k] / b[k] * 100 for k in keys],
                name="전체 그룹핑(상한)", marker_color=ACCENT2,
                text=[f"{g[k] / b[k] * 100:.0f}" for k in keys], textposition="outside")
    fig.add_hline(y=100, line_dash="dot", line_color=MUTED)
    fig.update_layout(barmode="group", height=320, margin=dict(l=0, r=0, t=10, b=0),
                      paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT, font_color="#e6edf3",
                      yaxis_title="기준=100%", legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, use_container_width=True)

    st.success("💡 **윈도우 그룹핑**은 전환·셋업·병목을 줄이면서 **리드타임까지 개선**(버스트 없음). "
               "반면 **전체 그룹핑**은 병목은 더 줄지만 같은 강종이 몰려 상류(RH)에 버스트가 생겨 리드타임이 "
               "악화됩니다 — 한 목적만 밀면 부작용이 납니다. 그래서 **납기·폭·흐름 제약을 함께 고려한 시퀀싱 "
               "최적화(E)** 가 필요합니다 → ‘제약·최적화 예시’ 탭.")


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

tab_data, tab_cause, tab_whatif, tab_sim, tab_opt = st.tabs(
    ["📥 과거 데이터 (가시화·병목)", "🔎 원인 분석", "📈 개선 what-if", "🔄 물류 시뮬레이션",
     "🧩 제약·최적화 예시 (인터뷰용)"])
with tab_data:
    render_data()
with tab_cause:
    render_cause()
with tab_whatif:
    render_whatif()
with tab_sim:
    render_simulation(sim)
with tab_opt:
    render_optimization()
