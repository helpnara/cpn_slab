# 유지보수 & 확장 가이드

`cpn_slab.html`은 단일 파일이므로, 대부분의 변경은
`<script>` 상단의 **데이터 정의부**(`GRADES`, `STAGES`, `stagesFor`)와
SVG 다이어그램만 수정하면 됩니다. 아래는 흔한 작업별 체크리스트입니다.

> 모델 요소의 정확한 정의는 [ARCHITECTURE.md](ARCHITECTURE.md)를 먼저 확인하세요.

---

## 새 강종(Color) 추가

예: `SPHC`(열연강판)를 LF 경로로 추가.

1. **`GRADES` 배열**에 항목 추가
   ```js
   { id:'SPHC', color:'#4a9eff', route:'LF', label:'열연강판' },
   ```
2. **`route`가 기존(LF/RH/DIRECT) 중 하나면 끝.** 새 경로가 필요하면
   아래 "새 공정 경로 추가" 절 참고.
3. (선택) **범례(legend-row)** 에 카드 추가 — `<body>`의 `.legend-row` 블록.
4. 색상은 CSS `:root`의 `--token-*` 토큰과 통일감 있게 선택.

> 강종 개수는 하드코딩되어 있지 않습니다(`makeSlab`이 `GRADES.length` 사용).
> 강종을 추가하면 입력부 드롭다운(`populateGradeSelect`)과 심층 분석의
> 강종별 리드타임 차트에도 자동 반영됩니다.

## 새 공정 위치(Place) 추가

예: 몰드 뒤에 `bender`(벤더) 추가.

1. **`STAGES` 배열**에 항목 추가 (`cx/cy`는 SVG 좌표, `proc`=체류 스텝,
   `cap`=수용 용량). `proc`·`cap`이 처리시간과 병목을 좌우합니다.
   ```js
   { id:'bender', label:'벤더', cx:660, cy:150, proc:2, cap:1 },
   ```
2. **`stagesFor()`** 의 해당 경로 시퀀스에 `'bender'` 삽입
   ```js
   if (route === 'LF') return ['ld','lf_wait','lf','tundish','mold','bender','cooling','yard'];
   ```
3. **SVG 다이어그램**에 원(`<circle>`)과 레이블(`<text>`), 연결 화살표(`<line>`) 추가.
   기존 Place 블록을 복사해 좌표만 조정하면 됩니다.
4. (선택) **`makeTemp()`** 에 해당 Place의 온도 규칙 추가.
5. 점유/용량 차트(`updateInsights`)와 병목 경보에는 자동 반영됩니다.

## 새 경로(Route) 추가

예: `IF`(진공 처리 없이 LF+RH 이중 정련) 경로.

1. **`stagesFor()`** 에 새 분기 추가
   ```js
   if (route === 'DUAL') return ['ld','lf_wait','lf','rh','tundish','mold','cooling','yard'];
   ```
2. 이 경로를 쓰는 강종의 `GRADES.route`를 `'DUAL'`로 지정.
3. SVG에 필요한 Transition/Arc 추가.

## 시뮬레이션 파라미터 튜닝

매직넘버는 `<script>` 상단 **`CONFIG` 객체 한 곳**에 모여 있고, 대부분
**입력부 UI에서 실행 중에도 실시간 변경**됩니다
([ARCHITECTURE §3 CONFIG 표](ARCHITECTURE.md#config--튜닝-파라미터-입력부에서-실시간-변경)):

- **혼잡도**: `maxWip`(최대 WIP 슬라이더), `arrivalProb`(투입 확률 슬라이더)
- **처리 속도**: Place별 `proc`(체류시간), `speedMs`(속도 셀렉트)
- **병목 민감도**: `bottleneckThreshold`(임계 슬라이더), Place별 `cap`
- **투입 방식**: `autoArrival`(자동 투입 체크박스), 입력부의 수동 투입 대기열

기본값 자체를 바꾸려면 `CONFIG` 초기값과 해당 슬라이더의 `value` 속성을
함께 수정하세요.

## 스타일 변경

색상·간격은 `<style>` 상단 `:root`의 **CSS 변수**로 중앙화되어 있습니다.
개별 요소를 고치기보다 토큰(`--accent`, `--surface`, `--token-*` 등)을
수정하면 전역에 일관되게 반영됩니다.

## 변경 후 확인 체크리스트

자동화된 테스트가 없으므로 **수동 검증**이 필요합니다.

- [ ] 브라우저(가급적 데스크톱 + iOS Safari)에서 파일을 연다
- [ ] **▶ 시작** 후 3개 강종이 모두 투입되는지 로그로 확인
- [ ] 각 강종이 올바른 정련 경로(LF/RH/직행)로 분기되는지 확인
- [ ] SVG 토큰이 Place를 따라 이동하고 야드에서 사라지는지 확인
- [ ] **입력부**: 자동 투입 끄고 수동으로 강종·두께·수량 예약 → 대기열 소진 확인
- [ ] **파라미터**: WIP·투입확률·병목임계 슬라이더가 실행 중 즉시 반영되는지 확인
- [ ] **병목**: 단일설비(cap=1)에서 상류 토큰이 블로킹되고 경보/병목 배지가 뜨는지 확인
- [ ] **심층 분석**: WIP 추이·Place 점유·강종별 리드타임 차트가 갱신되는지 확인
- [ ] **↺ 초기화** 후 시계·통계·로그·토큰·차트·대기열이 모두 리셋되는지 확인
- [ ] 콘솔에 에러가 없는지 확인 (헤드리스: Playwright로 스모크 확인 가능 — ROADMAP P3)
- [ ] 외부 네트워크 요청이 추가되지 않았는지 확인(오프라인 원칙 유지)

## 코딩 규칙

- **의존성 0 원칙 유지** — 외부 폰트/CDN/라이브러리를 추가하지 않습니다
  (iOS Safari 로컬 실행 호환). 불가피하면 [ROADMAP](ROADMAP.md)에서 논의.
- **단일 파일 유지** — 현 프로토타입 단계에서는 분리하지 않습니다.
  파일 분리·번들 도입은 ROADMAP의 개선 항목으로 다룹니다.
- UI 문자열은 한국어, 코드 식별자는 영문을 유지합니다.
