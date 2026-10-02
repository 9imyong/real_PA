---
id: ADR-0006
title: 독립 브라우저와 클라우드 대화 API 우선 구현
status: 승인됨
date: 2026-10-02
decision_makers: [프로젝트 소유자]
related_requirements: [REQ-API-001, REQ-VOICE-001, REQ-MODEL-001]
supersedes: ADR-0005
superseded_by: null
---

# ADR-0006: 독립 브라우저와 클라우드 대화 API

## 맥락

- 최신 사용자 지시: real-PA 자체 테스트 브라우저에서 실시간 텍스트·음성·연속 대화 우선 구현
- Lemmy 추가 수정보다 독립 기능 우선, 추후 Lemmy는 배포된 클라우드 API 사용
- 로봇에서 대화 제어하던 ADR-0005의 배치 우선순위를 변경

## 검토한 대안

| 대안 | 장점 | 비용 |
| --- | --- | --- |
| Lemmy 내 먼저 구현 | 기존 인증·업무 활용 | 브라우저·배포·AI 파이프라인 검증 결합 |
| standalone API와 브라우저 | 독립 검증·공통 API·모델 교체 | 연결 인증·클라우드 운영·클라이언트 계약 필요 |

## 결정

- real-PA API 서버에서 세션·STT·LLM·TTS·VAD·취소 제어
- 브라우저/추후 Lemmy 클라이언트에서 capture·AEC·playback·재생 확인
- HTTP 테스트 브라우저와 `/v1/realtime` WebSocket을 한 서버/Origin으로 제공
- 텍스트 연결은 마이크 권한 없이 가능, 연결 중 마이크 전환과 입력·출력 동시 실행
- 역할별 포트·adapter·manifest 교체 계약 유지, 외부 AI API 자동 전환 금지
- 기존 Lemmy 변경은 미배포 참고 자산으로 보존, 추가 변경·현재 인수 범위의 선행 조건으로 사용하지 않음
- 승인 범위: 사용자 변경 방향. 실제 브라우저·모델 품질·클라우드 배포 인수 완료 의미 아님

## 결과와 검증

- 로컬 GPU에서 동일 API로 먼저 개발, 회사 클라우드로 이동 시 client/API 계약 유지
- TLS proxy·credential·Origin·동시 용량·WAN 지연은 배포 검증 대상
- 개인 도구·DB·사용자 권한은 후속 Lemmy 통합 단계의 책임
- [T008](../tasks/active/TASK-20261002-008.md), [테스트 가이드](../guides/testing.md)
