---
id: REQ-MODEL-001
title: AI 모델과 실행 엔진의 교체
status: 설계 기준선
owners: [프로젝트 소유자]
created: 2026-10-01
last_reviewed: 2026-10-01
---

# 요구사항: AI 모델과 실행 엔진 교체

## 목적과 문제

LLM·STT·TTS·KWS·VAD의 교체를 대화 제어·Lemmy 업무 코드 변경 없이 수행.
모델 파일 변경과 실행 엔진 변경의 비용·호환성 구분.

## 요구사항

| ID | 필수 조건 | 검증 |
| --- | --- | --- |
| REQ-MODEL-001-01 | 5개 역할의 provider-neutral 포트·자료형 제공, SDK 객체의 코어 노출 금지 | M01 |
| REQ-MODEL-001-02 | 지원하는 동일 엔진의 호환 모델 변경은 설정과 manifest 변경만으로 수행 | M02 |
| REQ-MODEL-001-03 | 엔진 변경은 어댑터·등록 항목·설정 변경으로 수행, 대화·Lemmy 코어 변경 없음 | M03 |
| REQ-MODEL-001-04 | 필수 기능·언어·오디오 형식 검증, 미지원 조합의 세션 시작 거부 | M04 |
| REQ-MODEL-001-05 | 공통 lifecycle·timeout·취소·오류·늦은 결과 처리 계약 유지 | M05 |
| REQ-MODEL-001-06 | 역할별 독립 선택, 모델·엔진·revision·hash·license 재현 기록 | M06 |
| REQ-MODEL-001-07 | 각 역할의 서로 다른 어댑터 2개로 같은 계약 테스트 통과 | M07 |
| REQ-MODEL-001-08 | 시작 또는 세션 경계에서 교체, 실패 시 이전 조합 복구, 활성 세션 hot swap 제외 | M08 |

## 인수 조건

- 지원하는 모델 2개를 동일 엔진에서 설정으로 선택, 동일 코어 코드 사용
- 역할별 어댑터 2개로 공통 입력·출력·취소·실패 계약 검증
- fake 어댑터 시험과 실제 모델 시험 구분, 실제 교체 완료는 실제 어댑터 2개 결과 필요
- 미지원 streaming STT·LLM tool calling·취소 조합은 이유를 명시하고 시작 거부
- 교체 후 기존 음성·Lemmy 검증 회귀 수행, 성능·한국어 품질 재측정

## 범위와 제약

- 포함: 역할별 설정·factory registry·capability·manifest·계약 시험
- AEC: 동일 lifecycle과 오디오 계약 적용, 모델 여부와 무관하게 별도 처리기 포트 유지
- 제외: 모든 공개 모델의 자동 호환, 활성 세션 hot swap, 외부 AI API 자동 fallback
- 호환 모델의 정의: 해당 adapter가 지원하는 architecture·tokenizer·format·언어·기능 충족
- capability 선언만으로 동작 보장 금지, 실제 adapter 검증으로 증명
- 개발용 엔진·모델 조합과 공통 포트·설정·계약 구현, 실제 모델 2개씩 교체 인수 미완료

## 추적 관계

- [아키텍처 교체 계약](../architecture/system.md#모델-교체-계약)
- [ADR-0004](../decisions/ADR-0004-model-ports.md)
- [T002](../tasks/active/TASK-20261001-002.md), [T003](../tasks/active/TASK-20261001-003.md), [T004](../tasks/active/TASK-20261001-004.md)
- [M01–M08 검증 계획](../guides/testing.md#모델-교체-시나리오)

## 미결 사항

- 각 역할의 실제 어댑터 2개와 모델 후보: T002에서 선정
- 지원 format·취소 제한·자원 요구량: T002 실측 후 manifest 확정
