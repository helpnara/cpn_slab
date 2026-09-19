# CLAUDE.md

이 저장소에서 Claude Code(또는 AI 보조 도구)로 작업할 때 참고할 지침입니다.

## 프로젝트 한 줄 요약

제철소 연주(연속주조) 부문 슬래브 물류를 **Colored Petri Net** 개념으로 모델링해,
**가시화 → 병목 진단 → 개선 what-if → 라우팅 가이던스**로 이어지는 분석을 제공하는
**파이썬(Streamlit) 앱**입니다.

> 초기 프로토타입인 단일 HTML(`cpn_slab.html` + `index.html` 리다이렉트)은 **레거시
> 데모**로 저장소 루트에 남아 있으며 GitHub Pages로 계속 서빙됩니다. 신규 기능은
> 모두 Streamlit 앱에 추가하세요.

## 문서 지도

- [README.md](README.md) — 개요·실행·페이지 구성·배포
- [docs/DEV_PLAN.md](docs/DEV_PLAN.md) — **개발 방향·단계별 TODO(A→E)·인터뷰 후 진행 대기(§6)** ← 작업 전 먼저 확인
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — CPN 모델(강종/Place/경로/Guard), 엔진 구조
- [docs/MAINTENANCE.md](docs/MAINTENANCE.md) — 강종·공정·경로 추가, 파라미터 튜닝, 변경 후 체크리스트
- [docs/ROADMAP.md](docs/ROADMAP.md) — 알려진 한계와 개선 백로그
- [docs/OPTIMIZATION_SPEC.md](docs/OPTIMIZATION_SPEC.md) — 최적화 문제 정의(현업 인터뷰 양식, **미작성**)
- [docs/DATA_REQUEST.md](docs/DATA_REQUEST.md) — 과거 물류 데이터 요청서(현업·IT 전달용)
- [docs/INTERVIEW_GUIDE.md](docs/INTERVIEW_GUIDE.md) — 인터뷰 진행 가이드·체크리스트 (+ `docs/interview_deck.pptx`)

## 코드 구조

```
streamlit_app.py     # 진입점 — 사이드바 네비게이터 + 페이지별 render_*() 함수
src/model.py         # 강종(GRADES)·Place(STAGES, proc/cap)·경로(ROUTES)  ← 모델 변경의 출발점
src/simulation.py    # 체류시간·용량 기반 결정적 시뮬레이션 엔진 (Config, Simulation)
src/data.py          # 이벤트 로그 표준 스키마·로더·검증 + 가시화/진단 지표 (A~C)
src/whatif.py        # 주조 순서 정책별 재시뮬레이션·KPI 비교 (D)
src/guidance.py      # 라우팅 추천 규칙 (E)
src/optimization.py  # 캐스트 시퀀싱 최적화 **예시** (인터뷰 후 CP-SAT로 교체 예정)
data/sample_event_log.csv   # 샘플 이벤트 로그 (src/data.py 생성기로 재생성 가능)
```

페이지는 `streamlit_app.py`의 `PAGES` 테이블 하나로 관리합니다
(라벨·단계 캡션·제목·렌더 함수·안내문). 페이지 추가 시 `PAGES`와 `TIPS`에 함께 등록하세요.

## 작업 규칙

- **데이터 주도 변경**: 모델 수정은 `src/model.py`의 `GRADES` / `STAGES` / `ROUTES`에서
  시작합니다. Place에는 `proc`(체류 스텝)·`cap`(용량)이 있고, 이 둘이 병목을 결정합니다.
- **의존성은 최소로**: 현재 `streamlit` · `plotly` · `pandas` 뿐입니다. 차트는 Plotly,
  공정도는 `st.graphviz_chart`(DOT 문자열)로 해결하세요. 새 의존성은 꼭 필요할 때만
  추가하고 `requirements.txt`에 반영합니다. (CP-SAT 도입 시 `ortools` 예정 — DEV_PLAN §6)
- **가정과 실제를 구분해 표기**: 샘플 데이터·파라미터·최적화 가중치는 아직 가정값입니다.
  UI에 수치를 노출할 때 "예시/가정"임을 밝히는 기존 문구 패턴을 유지하세요
  (도움말 페이지의 '신뢰도' 섹션 참조).
- **언어**: UI 문자열·문서는 한국어, 코드 식별자는 영문.
- **접근성**: 강종은 색 + 패턴(`GRADE_PATTERN`)으로 이중 인코딩합니다.

## 빌드 · 테스트 · 실행

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py          # → http://localhost:8501
python -m src.data                      # 샘플 이벤트 로그 재생성
```

- **자동 테스트 없음**(ROADMAP P3). 변경 후 검증은 두 단계로:
  1. **지표 단위 확인** — `python -c "from src.data import *; ..."` 식으로 계산 결과를 직접 출력
  2. **헤드리스 렌더 확인** — Playwright로 앱을 열어 **콘솔/페이지 에러 0** 과 해당 화면 렌더를 확인
     (스크린샷을 남겨 리뷰하면 좋습니다)
- 레거시 HTML 변경 시에는
  [MAINTENANCE의 수동 체크리스트](docs/MAINTENANCE.md#변경-후-확인-체크리스트)를 사용합니다.

## 배포

- **Streamlit Community Cloud** — repo `main` / `streamlit_app.py`. `main`에 병합되면 자동 재배포.
- **GitHub Pages** — 레거시 HTML 데모(`index.html` → `cpn_slab.html`). 정적 전용이라
  Streamlit 앱은 여기에 올릴 수 없습니다.

## Git 워크플로

병합 커밋의 committer가 `noreply@anthropic.com`이 되도록 **로컬 병합**을 사용합니다
(GitHub API 병합은 committer가 `noreply@github.com`이 되어 Unverified로 표시됨).

```bash
# 작업 브랜치에서 커밋·푸시 → PR 생성(기록용) → 로컬에서 병합
git checkout -B main origin/main
git merge --no-ff <작업브랜치> -m "Merge PR #N: ..."
git push origin main                    # PR이 자동으로 merged 처리됨
git checkout -B <작업브랜치> main && git push origin <작업브랜치>
```

## 변경 시 유의

- **시뮬레이션 튜닝 파라미터는 `Config` 데이터클래스(`src/simulation.py`)에 모여 있고**
  사이드바 위젯과 연동됩니다. 기본값을 바꾸면 해당 위젯의 초기값도 함께 맞추세요.
  (what-if·가이던스의 셋업/도착 상수는 `src/whatif.py` 상단에 있습니다.)
- **이벤트 로그 스키마를 바꾸면** `src/data.py`(로더·검증·지표)와
  [DATA_REQUEST.md](docs/DATA_REQUEST.md)를 **함께** 갱신해야 현업 요청 내용과 어긋나지 않습니다.
- **⏸ 인터뷰 게이트**: D2(CP-SAT 최적화)·E1(제약 엔진)은 `OPTIMIZATION_SPEC.md`가
  채워진 뒤 착수합니다. 그 전에 규칙을 임의로 최적화 로직으로 바꾸지 마세요.
- 모델·구조를 바꾸면 관련 문서(ARCHITECTURE / DEV_PLAN / ROADMAP)도 함께 갱신합니다.
