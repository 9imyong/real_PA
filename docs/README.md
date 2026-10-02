# 문서 안내

- **담당:** 프로젝트 소유자
- **마지막 검토:** 2026-10-01
- **상태:** 런타임 구현·실제 모델 smoke 진행, 제품 인수 미완료
- **체계:** project-sample standard, 통합 아키텍처 1개 유지

## 기준 문서

| 질문 | 문서 | 상태 |
| --- | --- | --- |
| 무엇을 만드는가 | [로컬 양방향 대화 요구사항](requirements/REQ-VOICE-001.md) | 사용자 방향 반영, 수치 목표는 검증 전 |
| Lemmy에 어떻게 적용하는가 | [Lemmy 연동 요구사항](requirements/REQ-LEMMY-001.md) | 연동 계약 구현 전 |
| 현재와 목표 구조는 무엇인가 | [통합 아키텍처](architecture/system.md) | 현재 구현 경로와 목표 설계 구분 |
| 어떤 방향이 정해졌는가 | [ADR 목록](decisions/README.md) | 방향 승인 및 기술 제안 구분 |
| 어떤 순서로 구현하는가 | [작업 목록](tasks/README.md) | T002–T005 진행, T006 실제 인수 미완료 |
| 어떻게 개발·검증하는가 | [개발](guides/development.md), [테스트](guides/testing.md) | 실행 도구와 계획 구분 |
| 어떻게 변경·릴리스하는가 | [Git](guides/git-workflow.md), [릴리스](guides/release.md) | 최초 제품 릴리스 전 |

## 읽는 순서

1. 저장소 [README](../README.md)와 [AGENTS](../AGENTS.md) 확인
2. 요구사항 2개와 [아키텍처](architecture/system.md) 확인
3. 관련 ADR과 [진행 작업](tasks/README.md) 확인
4. 개발·테스트 가이드 확인 후 해당 Task 착수

## 문서 책임

- 요구사항: 사용자 결과·품질 목표·인수 조건
- 아키텍처: 현재 상태, 목표 구성, 불변 조건, 책임 경계
- ADR: 당시 결정 이유와 대안, 승인 이후 원문 보존
- Task: 변경 범위·실행 계획·진행 이력·검증 증거
- [문서 운영 정책](DOCS_GOVERNANCE.md): 작성 스타일·생략·갱신 규칙
- [용어집](glossary.md): 양방향·반향·취소·세션 용어
- [AI 작업 요청 템플릿](AI_AGENT_PROMPT_TEMPLATE.md): 후속 구현 요청 형식

## 확장 기준

RFC·Operations 모듈 미도입, 내부 설계는 통합 아키텍처에서 관리.
Lemmy UI의 신규 소켓 소비를 위한 [duplex 전송 계약](specs/duplex-transport.md) 추가.

## 모델 교체 설계

- [모델 교체 요구사항](requirements/REQ-MODEL-001.md)
- [포트·설정·capability 계약](architecture/system.md#모델-교체-계약)
- [ADR-0004](decisions/ADR-0004-model-ports.md)
- [M01–M08 검증](guides/testing.md#모델-교체-시나리오)

## 현재 우선순위

- [독립 브라우저·클라우드 API 요구사항](requirements/REQ-API-001.md)
- [ADR-0006](decisions/ADR-0006-standalone-cloud-api.md), [T008](tasks/active/TASK-20261002-008.md)
- Lemmy 추가 수정은 후속 단계, 현재 독립 API 인수에 Lemmy 앱/DB 필수 의존 없음
