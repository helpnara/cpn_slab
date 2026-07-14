# CLAUDE.md

이 저장소에서 Claude Code(또는 AI 보조 도구)로 작업할 때 참고할 지침입니다.

## 프로젝트 한 줄 요약

제철소 연주(연속주조) 부문 슬래브 물류를 **Colored Petri Net** 개념으로
시각화·시뮬레이션하는 **단일 HTML 프로토타입**(`cpn_slab.html`).

## 문서 지도

- [README.md](README.md) — 개요·실행·사용법
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — CPN 모델(강종/Place/경로/Guard), 코드 구조, 함수 맵
- [docs/MAINTENANCE.md](docs/MAINTENANCE.md) — 강종·공정·경로 추가, 파라미터 튜닝, 변경 후 체크리스트
- [docs/ROADMAP.md](docs/ROADMAP.md) — 알려진 한계와 개선 백로그

## 작업 규칙

- **의존성 0 원칙**: 외부 폰트·CDN·라이브러리·네트워크 요청을 추가하지 마세요.
  iOS Safari에서 로컬 파일로 직접 열어도 동작해야 합니다.
- **단일 파일 유지**: 현 단계에서는 `cpn_slab.html` 하나로 유지합니다
  (분리는 ROADMAP의 P8에서 다룸).
- **데이터 주도 변경**: 모델 수정은 `<script>` 상단의 `GRADES` / `STAGES` /
  `stagesFor()` 정의부에서 시작합니다.
- **언어**: UI 문자열은 한국어, 코드 식별자는 영문.

## 빌드 · 테스트 · 실행

- **빌드 없음**: 브라우저로 `cpn_slab.html`을 직접 엽니다.
- **자동 테스트 없음**: 변경 후
  [MAINTENANCE의 수동 체크리스트](docs/MAINTENANCE.md#변경-후-확인-체크리스트)로
  검증합니다. (테스트 자동화는 ROADMAP P3)

## 변경 시 유의

- 매직넘버(최대 슬래브 6, 투입 0.45, 전진 0.5, 병목 임계 2, 강종 개수 3)는
  코드에 흩어져 있습니다 — 수정 시 [ARCHITECTURE §3](docs/ARCHITECTURE.md#3-시뮬레이션-루프)를
  확인하세요.
- 모델·구조를 바꾸면 관련 문서(ARCHITECTURE / ROADMAP)도 함께 갱신합니다.
