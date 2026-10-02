---
id: ADR-0005
title: 회사 GPU 추론과 로봇 대화 제어 분리
status: 승인됨
date: 2026-10-01
decision_makers: [프로젝트 소유자]
related_requirements: [REQ-VOICE-001, REQ-LEMMY-001, REQ-MODEL-001]
supersedes: null
superseded_by: null
---

# ADR-0005: 회사 GPU 추론과 로봇 대화 제어 분리

## 맥락

사용자 확정: Gemini 대신 회사 자체 GPU 서버에서 추론, 로봇에서 입출력·전체 대화 제어.
회사 서버 사양 미정, 현재 로컬 GPU로 개발. 대상 운영체제 Ubuntu 26.

## 검토한 대안

| 대안 | 장점 | 비용 |
| --- | --- | --- |
| 모든 모델을 로봇에서 실행 | 네트워크 왕복 제거 | 로봇 GPU·메모리 제약 |
| 회사 GPU 추론·로봇 제어 | 중앙 GPU와 모델 관리·로봇 기능 경계 유지 | 네트워크 지연·연결/취소·인증 필요 |
| 외부 Gemini 유지 | 기존 경로 활용 | 사용자 자체 추론 요구 불충족 |

## 결정

- 회사 GPU 서버에 추론 worker 배치, 로봇에 capture/playback·AEC·세션·도구 정책 배치
- 개발 PC의 RTX 3090으로 동일 경계의 모델·통신 검증
- 실제 모델은 역할별 adapter로 교체, 로봇에는 company_rpc adapter 주입 가능
- streaming 출력 중 입력 수집 지속, 끼어들기 즉시 generation 변경과 playback 중단
- worker 연결 종료/취소 전파, 늦은 결과 폐기와 제한된 큐 유지
- 회사 접속에는 TLS와 worker 인증 필요, 사용자·도구 권한은 Lemmy가 소유

## 결과와 후속 작업

- 로컬 실행은 자사 소유 추론의 의미로 유지, 같은 장치에서만 실행할 필요 없음
- STT/TTS의 CPU/GPU 배치는 모델별 측정 후 결정
- 실제 회사 서버·Ubuntu 26·로봇·WAN 지연·인증·도구 E2E는 T002–T006 검증 필요
- 기존 ADR-0001의 외부 AI 서비스 불사용 방향 유지
- [통합 아키텍처](../architecture/system.md#회사-gpu와-로봇의-실행-경계)
- [검증 기록](../guides/testing.md#2026-10-01-검증-기록)
