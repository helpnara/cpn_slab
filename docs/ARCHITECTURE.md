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

## 2. CPN 요소 정의

### 2.1 Color set — 강종

`cpn_slab.html`의 `GRADES` 배열에 정의되어 있습니다.

| id | route | label | color |
|------|--------|-----------|---------|
| `SUS304` | `LF` | 스테인리스 | `#c084fc` |
| `SS400` | `DIRECT` | 일반구조용 | `#34d399` |
| `API5L` | `RH` | 파이프라인강 | `#f59e0b` |

### 2.2 Place — 공정 위치

`STAGES` 배열에 정의됩니다. `cx/cy`는 SVG 다이어그램상의 좌표입니다.

| id | label | 역할 | (cx, cy) |
|-----------|-------------|-----------------------|-----------|
| `ld` | 전로 OUT | 전로 출강 완료 버퍼 | (55, 150) |
| `lf_wait` | 정련 대기 | 정련 전 대기(분기 지점) | (218, 150) |
| `lf` | LF 정련 | Ladle Furnace 정련 | (310, 70) |
| `rh` | RH 탈가스 | RH 진공 탈가스 | (310, 230) |
| `tundish` | 턴디시 | 연주기 턴디시 | (405, 150) |
| `mold` | 몰드 | 연주기 몰드(주형) | (580, 150) |
| `cooling` | 2차 냉각대 | 2차 냉각/응고 구간 | (745, 150) |
| `yard` | 슬래브 야드 | 최종 입고(완료) | (910, 150) |

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

> ⚠️ 현재 Guard는 SVG의 정적 표기와 `tick()` 내 로그 메시지로만 표현되며,
> 별도의 규칙 엔진으로 강제되지는 않습니다. 실제 분기는 `stagesFor()`가 반환한
> 고정 시퀀스를 따라갑니다. 개선 방향은 [ROADMAP](ROADMAP.md) 참고.

### 2.5 토큰 속성

투입 시 `tick()`에서 슬래브 객체가 생성됩니다.

| 속성 | 설명 | 생성 규칙 |
|-----------|--------------------------|--------------------------------------|
| `id` | 고유 식별자 | `'slab-' + Date.now()` |
| `heatNo` | Heat 번호 | `makeHeat()` → `H001`, `H002`, … |
| `grade` | 강종 | `GRADES`에서 무작위 |
| `thick` | 두께(mm) | 200 ~ 300 무작위 |
| `route` | 경로 | 강종의 `route` |
| `stages` | Place 시퀀스 | `stagesFor(route)` |
| `stageIdx` | 현재 단계 인덱스 | 0에서 시작 |
| `startTime` | 투입 시각(초) | 투입 시점 `elapsed` |

온도는 상태로 저장하지 않고 `makeTemp(stage)`로 현재 Place에 따라 계산됩니다:
`ld` 1650℃ → `lf/rh` 1580℃ → `tundish` 1545℃ → `mold` 1520℃ →
`cooling` 1100~1300℃ → 그 외 900℃.

## 3. 시뮬레이션 루프

`tick(timestamp)` — `requestAnimationFrame` 콜백. 매 프레임 호출되지만
선택된 **속도(speed) 간격(ms)** 이 지났을 때만 로직을 실행합니다.

각 틱마다:

1. **투입**: `slabs.length < 6` 이고 `Math.random() < 0.45` 이면 새 슬래브 1개 투입
2. **이동**: 각 슬래브를 `Math.random() < 0.5` 확률로 다음 Place로 전진
   (`stageIdx++`), 분기 지점 진입 시 Guard 로그 기록
3. **완료 처리**: `yard`에 도달한 슬래브를 제거하고 `done++`, 처리 시간 기록
4. **렌더**: `renderSvgTokens()`, `renderTokenList()`, `updateStats()` 호출

### 주요 파라미터 (튜닝 지점)

| 파라미터 | 현재값 | 위치 | 의미 |
|--------------------|---------|------------------|-----------------------------|
| 최대 동시 슬래브 | 6 | `tick()` 투입 조건 | 공정 내 최대 토큰 수 |
| 투입 확률 | 0.45 | `tick()` 투입 조건 | 틱당 신규 투입 확률 |
| 전진 확률 | 0.5 | `tick()` 이동 로직 | 틱당 다음 Place 이동 확률 |
| 두께 범위 | 200~300mm | `tick()` | 무작위 두께 |
| 병목 임계 | 2 | `updateStats()` | 한 Place에 토큰 ≥2면 경보 |
| 속도 옵션 | 1500/800/400ms | `#speed-sel` | 틱 간격 |

## 4. 코드 구조 (`cpn_slab.html`)

단일 파일 안에 3개 영역이 있습니다.

```
<style> ... </style>     — CSS 변수(디자인 토큰) + 레이아웃/컴포넌트 스타일
<body> ... </body>       — 헤더, 범례, SVG 다이어그램, 컨트롤, 패널, 지표
<script> ... </script>   — 데이터 정의 + 상태 + 렌더 + 시뮬레이션 루프
```

### JS 주요 함수 맵

| 구분 | 함수 | 역할 |
|------|--------------------|-----------------------------------|
| 데이터 | `GRADES`, `STAGES` | Color set / Place 정의 |
| 데이터 | `stagesFor(route)` | 경로별 Place 시퀀스 |
| 데이터 | `stagePos(sid)` | Place 좌표 조회 |
| 생성 | `makeHeat()` | Heat 번호 채번 |
| 생성 | `makeTemp(stage)` | Place별 온도 계산 |
| 렌더 | `renderSvgTokens()` | SVG 위 토큰(●) 배치 |
| 렌더 | `renderTokenList()` | 토큰 목록 패널 |
| 렌더 | `updateStats()` | 지표 4종 + 병목 경보 |
| 렌더 | `addLog(msg, type)` | 이벤트 로그 추가 |
| 상호작용 | `highlightSlab(id)` | 토큰 클릭 하이라이트 |
| 루프 | `tick(timestamp)` | 시뮬레이션 1스텝 |
| 제어 | `startSim()` / `resetSim()` | 시작 / 초기화 |
| 시계 | `startClock()` | 경과 시간 카운터 |

### 전역 상태

`slabs`(현재 토큰 배열), `done`(완료 수), `elapsed`(경과 초),
`heatSeq`(Heat 채번 카운터), `completionTimes`(처리시간 배열),
`isRunning` / `rafId` / `lastTickTime`(루프 제어).

## 5. iOS Safari 호환

이 데모는 iOS Safari에서 **로컬 파일로 직접 열어도** 동작하도록 설계되었습니다.

- **외부 폰트 제거**: 시스템 폰트(`-apple-system`, `Apple SD Gothic Neo` 등)만
  사용 → 네트워크 없이 렌더링 (`<style>` 상단 주석 참고)
- **`requestAnimationFrame` 기반 루프**: 백그라운드 탭에서 `setInterval`이
  불안정한 문제를 피하기 위해 RAF + 타임스탬프 델타로 틱 간격을 제어
  (`tick()` 상단 주석 참고)
- **CDN·외부 리소스 0**: 오프라인에서도 완전 동작

이 제약은 개선 작업 시에도 유지하는 것을 권장합니다 (신규 의존성 추가 지양).
