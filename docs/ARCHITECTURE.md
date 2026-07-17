# 아키텍처 — CPN 모델 & 코드 구조

이 문서는 `cpn_slab.html`의 도메인 모델(Colored Petri Net)과 코드 구조를
정리합니다. 유지보수·개선 작업 전에 먼저 읽어 주세요.

---

## 1. 도메인 개요

제철소 **연주(연속주조) 부문**의 슬래브 물류를 Colored Petri Net으로 모델링합니다.

- **토큰(Token)** = 슬래브 1개 (강종·두께·온도·Heat 번호를 속성으로 가짐)
- **색(Color)** = 강종(SUS304 / SS400 / API5L) — 색에 따라 경로가 분기됨
- **Place** = 설비 또는 버퍼 위치 (전로 OUT, 정련 대기, LF, RH, 턴디시, 몰드, 냉각대, 야드)
- **Transition** = 공정 이벤트 (출강 TAP, 정련 T_LF/T_RH, 주조 CAST, 응고 SOLID, 절단 CUT)

각 Place는 **처리 체류시간(proc)** 과 **수용 용량(cap)** 을 가지며, 토큰은
"체류시간이 끝나고 + 다음 Place에 여유가 있을 때"만 전진합니다. 이 규칙이
CPN의 발화(firing)에 해당하며, 입력이 결과(병목·리드타임·점유율)에 인과적으로
반영되게 합니다.

## 2. CPN 요소 정의

### 2.1 Color set — 강종

`cpn_slab.html`의 `GRADES` 배열에 정의되어 있습니다.

| id | route | label | color |
|------|--------|-----------|---------|
| `SUS304` | `LF` | 스테인리스 | `#c084fc` |
| `SS400` | `DIRECT` | 일반구조용 | `#34d399` |
| `API5L` | `RH` | 파이프라인강 | `#f59e0b` |

### 2.2 Place — 공정 위치

`STAGES` 배열에 정의됩니다. `cx/cy`는 SVG 좌표, `proc`는 처리 체류 스텝 수,
`cap`은 동시 수용 용량입니다.

| id | label | proc | cap | (cx, cy) |
|-----------|-------------|:----:|:----:|-----------|
| `ld` | 전로 OUT | 1 | ∞ | (55, 150) |
| `lf_wait` | 정련 대기 | 1 | 3 | (218, 150) |
| `lf` | LF 정련 | 3 | 1 | (310, 70) |
| `rh` | RH 탈가스 | 4 | 1 | (310, 230) |
| `tundish` | 턴디시 | 1 | 1 | (405, 150) |
| `mold` | 몰드 | 2 | 1 | (580, 150) |
| `cooling` | 2차 냉각대 | 3 | 4 | (745, 150) |
| `yard` | 슬래브 야드 | 1 | ∞ | (910, 150) |

> `cap=1`인 단일 설비(LF/RH/턴디시/몰드)가 병목의 원천입니다. 상류 토큰은
> 이 Place가 비기 전까지 **블로킹**되며, 이것이 `stat-bottleneck` 경보와
> 점유 차트의 신호가 됩니다.

### 2.3 경로(Route) — Color별 Place 시퀀스

`stagesFor(route)` 함수가 강종별 Place 순서를 반환합니다.

```
LF     : ld → lf_wait → lf   → tundish → mold → cooling → yard
RH     : ld → lf_wait → rh   → tundish → mold → cooling → yard
DIRECT : ld → lf_wait        → tundish → mold → cooling → yard
```

`lf_wait` 이후가 강종에 따라 갈리는 **분기 지점(Guard)** 입니다.

### 2.4 Transition & Guard

SVG 다이어그램의 Transition 노드(사각형)와 로그상의 Guard 표현:

| Transition | 위치 | 발화 조건(Guard) |
|------------|-------------------|-----------------------------|
| `T_TAP` | 전로 → 정련대기 | 무조건 |
| `T_LF` | 정련대기 → LF | `grade == SUS304` |
| `T_RH` | 정련대기 → RH | `grade == API5L` |
| (직행) | 정련대기 → 턴디시 | `grade == SS400` |
| `T_CAST` | 턴디시 → 몰드 | 무조건 |
| `T_SOLID` | 냉각대 진입 | 무조건 |
| `T_CUT` | 냉각대 → 야드 | 무조건 |

> Guard의 강종 분기는 `stagesFor()`가 반환하는 경로 시퀀스로 표현되며,
> 이동 자체의 발화는 **체류시간 + 다음 Place 용량** 조건으로 강제됩니다
> (§3). Guard 표현식을 데이터로 정식화하는 방향은 [ROADMAP P1](ROADMAP.md).

### 2.5 토큰 속성

`makeSlab(gradeId, thick)`가 슬래브 객체를 생성합니다.

| 속성 | 설명 | 생성 규칙 |
|--------------|--------------------------|--------------------------------------|
| `id` | 고유 식별자 | `'slab-' + idSeq++` |
| `heatNo` | Heat 번호 | `makeHeat()` → `H001`, `H002`, … |
| `grade` | 강종 | 지정값 또는 무작위 |
| `thick` | 두께(mm) | 지정값 또는 `thickMin~thickMax` 무작위 |
| `route` | 경로 | 강종의 `route` |
| `stages` | Place 시퀀스 | `stagesFor(route)` |
| `stageIdx` | 현재 단계 인덱스 | 0에서 시작 |
| `remaining` | 현재 Place 잔여 체류 스텝 | 진입 시 `proc`, 매 스텝 감소 |
| `startTime` | 투입 스텝(리드타임 기준) | 투입 시점 `simTime` |
| `enteredTick` | 현재 Place 진입 스텝 | 체류시간 통계용 |
| `blocked` | 블로킹 여부 | 다음 Place 만석 시 `true` |

온도는 상태로 저장하지 않고 `makeTemp(stage)`로 현재 Place에 따라 계산됩니다:
`ld` 1650℃ → `lf/rh` 1580℃ → `tundish` 1545℃ → `mold` 1520℃ →
`cooling` 1100~1300℃ → 그 외 900℃.

## 3. 시뮬레이션 엔진

`tick(timestamp)` — `requestAnimationFrame` 콜백. 매 프레임 호출되지만
`CONFIG.speedMs` 간격이 지났을 때만 `step()`(시뮬레이션 1스텝)을 실행합니다.

`step()`의 순서:

1. `simTime++`
2. **투입**(`handleArrivals`): 수동 대기열(`manualQueue`)이 있으면 우선 투입,
   없으면 `CONFIG.autoArrival` && WIP 여유 && 확률(`arrivalProb`) 시 자동 투입.
   `ld` 용량 범위 내에서만.
3. **처리**: 모든 토큰의 `remaining` 1 감소.
4. **이동**: `remaining<=0`인 토큰을 **하류(뒤쪽)부터** 훑어, 다음 Place의
   `occupancy < cap`이면 전진(체류시간 기록·`remaining=다음 proc`), 아니면
   `blocked=true`. 하류부터 처리해 용량을 먼저 비우는 것이 핵심.
5. **완료**: `yard` 도착 + `remaining<=0` 토큰 제거, 리드타임 기록(`done++`).
6. **샘플·렌더**: `sampleHistory()` → `renderSvgTokens/renderTokenList/updateStats/updateInsights`.

### CONFIG — 튜닝 파라미터 (입력부에서 실시간 변경)

`<script>` 상단 `CONFIG` 객체 한 곳에 모여 있습니다.

| 키 | 기본값 | 의미 | UI 연동 |
|-----------------------|--------|-----------------------------|--------------|
| `maxWip` | 6 | 공정 내 최대 동시 슬래브 | 슬라이더 |
| `autoArrival` | true | 자동 투입 on/off | 체크박스 |
| `arrivalProb` | 0.45 | 자동 투입 스텝당 확률 | 슬라이더 |
| `speedMs` | 1500 | 스텝 간격(ms) | 속도 셀렉트 |
| `bottleneckThreshold` | 2 | 점유 경보 임계 | 슬라이더 |
| `thickMin`/`thickMax` | 200/300 | 무작위 두께 범위 | — |

Place의 `proc`/`cap`은 데이터 정의부(`STAGES`)에서 조정합니다.

## 4. 코드 구조 (`cpn_slab.html`)

단일 파일 안에 3개 영역이 있습니다.

```
<style> ... </style>     — CSS 변수(디자인 토큰) + 레이아웃/컴포넌트 스타일
<body> ... </body>       — 헤더, 범례, SVG, 입력부, 컨트롤, 패널, 지표, 심층분석
<script> ... </script>   — CONFIG/데이터 + 상태 + 엔진 + 입력 + 렌더/인사이트
```

### JS 주요 함수 맵

| 구분 | 함수 | 역할 |
|--------|-------------------------|-----------------------------------|
| 데이터 | `CONFIG`, `GRADES`, `STAGES` | 파라미터 / Color set / Place 정의 |
| 데이터 | `stagesFor`, `stagePos`, `gradeOf`, `capOf` | 경로·좌표·강종·용량 조회 |
| 생성 | `makeHeat`, `makeTemp`, `makeSlab` | Heat 채번 / 온도 / 슬래브 생성 |
| 엔진 | `handleArrivals` | 수동·자동 투입 |
| 엔진 | `step` | 시뮬레이션 1스텝(처리·이동·완료) |
| 엔진 | `occupancy` | Place별 현재 토큰 수 |
| 엔진 | `sampleHistory` | 시계열 샘플 적재 |
| 엔진 | `tick` | RAF 루프(speed 게이팅) |
| 입력 | `populateGradeSelect`, `addManual`, `clearQueue`, `renderQueue`, `bindInputs` | 입력부 UI |
| 렌더 | `renderSvgTokens`, `renderTokenList`, `addLog`, `highlightSlab` | 다이어그램·목록·로그 |
| 지표 | `updateStats` | KPI 4종 + 블로킹 기반 병목 경보 |
| 지표 | `updateInsights` | 처리량 KPI + WIP 추이·점유·리드타임 차트 |
| 제어 | `startSim`, `resetSim`, `startClock` | 시작 / 초기화 / 시계 |

### 전역 상태

`slabs`(토큰 배열), `done`(완료 수), `elapsed`(실경과 초, 표시용),
`simTime`(시뮬레이션 스텝), `heatSeq`/`idSeq`(채번), `completionTimes`(리드타임),
`dwellByStage`(Place별 체류시간), `leadByGrade`(강종별 리드타임),
`manualQueue`(수동 투입 대기열), `histSamples`(시계열 샘플),
`isRunning`/`rafId`/`lastTickTime`(루프 제어).

> `histSamples`는 최근 120스텝만 유지합니다. 브라우저 전역 `history`(History
> API)와의 혼동을 피하려 이름을 `histSamples`로 둡니다.

## 5. iOS Safari 호환

이 데모는 iOS Safari에서 **로컬 파일로 직접 열어도** 동작하도록 설계되었습니다.

- **외부 폰트 제거**: 시스템 폰트만 사용 → 네트워크 없이 렌더링
- **`requestAnimationFrame` 기반 루프**: 백그라운드 탭에서 `setInterval`이
  불안정한 문제를 피하기 위해 RAF + 타임스탬프 델타로 스텝 간격 제어
- **차트도 인라인 SVG/CSS**: 심층 분석 차트까지 외부 라이브러리 없이 구현
- **CDN·외부 리소스 0**: 오프라인에서도 완전 동작

이 제약은 개선 작업 시에도 유지하는 것을 권장합니다 (신규 의존성 추가 지양).
