---
id: ADR-0004
title: 역할별 포트·설정·기능 검증으로 모델 교체
status: 승인됨
date: 2026-10-01
decision_makers: [프로젝트 소유자]
related_requirements: [REQ-MODEL-001]
supersedes: null
superseded_by: null
---

# ADR-0004: 역할별 포트·설정·기능 검증으로 모델 교체

## 맥락

사용자가 LLM을 포함한 AI 모델의 쉬운 교체 설계 보강 요청.
기존 설계에는 LLM 포트 방향만 명시되고 전체 역할의 설정·기능 차이·교체 검증은 미구체화.

## 결정 기준

- 모델·실행 엔진 변경 시 대화와 Lemmy 업무 코드 보존
- 언어·streaming·취소·도구 기능 차이의 명시적 검증
- 오프라인 실행과 재현 가능한 모델 조합 유지

## 검토한 대안

| 대안 | 장점 | 비용·위험 |
| --- | --- | --- |
| 코어에 엔진별 분기 | 초기 코드 적음 | 교체마다 코어 변경·SDK 결합 |
| 모든 모델을 단일 범용 포트로 추상화 | 인터페이스 수 적음 | 음성·텍스트의 의미·기능 차이 소실 |
| 역할별 포트·어댑터·설정 registry | 역할 독립 교체·계약 검증 가능 | adapter·capability·테스트 유지 비용 |

## 결정

- LLM·STT·TTS·KWS·VAD를 역할별 포트로 정의, AEC는 독립 오디오 처리 포트
- provider-neutral 자료형·lifecycle·오류·취소 계약 유지
- 설정과 명시적 factory registry로 adapter 선택, manifest로 모델 버전 고정
- 시작 시 required capability 검증, 부적합한 조합 거부
- 역할별 어댑터 2개로 같은 계약 테스트 수행
- 동일 엔진의 호환 모델은 설정 변경, 새 엔진은 adapter 추가
- 활성 세션 hot swap은 첫 범위에서 제외

승인 범위는 사용자가 요청한 설계 방향. 실제 모델·엔진 선택·구현 검증 완료 의미 아님.

## 결과

- 긍정: 모델 교체와 업무 규칙 변경 분리, 지원 범위와 실패 원인 명확화
- 비용: 5개 역할의 adapter·계약 시험·capability manifest 관리
- 제약: 임의 공개 모델 자동 호환 보장 불가, 교체마다 품질·자원 재측정 필요

## 후속 작업과 검증

- T002: 실제 모델·adapter 후보 및 capability manifest 선정
- T003: 포트·registry·설정 검증·취소 계약 구현
- T004: 실제 adapter 교체와 음성 통합
- T006: 전체 회귀와 실기기 품질 확인
- [M01–M08 검증](../guides/testing.md#모델-교체-시나리오)
- [통합 아키텍처](../architecture/system.md#모델-교체-계약)
- [요구사항](../requirements/REQ-MODEL-001.md)
