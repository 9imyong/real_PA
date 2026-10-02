---
id: ADR-0007
title: 추론 서버와 로봇 대화 제어의 배치 확정
status: 승인됨
date: 2026-10-02
decision_makers: [프로젝트 소유자]
related_requirements: [REQ-API-001, REQ-MODEL-001, REQ-LEMMY-001]
supersedes: ADR-0006의 추후 Lemmy 대화 제어 배치
superseded_by: null
---

# ADR-0007: 추론 서버와 로봇 대화 제어

## 맥락

- 사용자 답변: 회사 GPU 서버에서 추론, 로봇에서 입출력·대화 제어
- 회사 장비는 미정, 우선 현재 로컬 GPU 사용, 대상 운영체제 Ubuntu 26
- 독립 브라우저 우선 검증과 역할별 모델 교체 방향은 유지

## 결정

- 최종 Lemmy 배치에서 로봇이 세션·끼어들기·generation·재생 확인을 소유
- 자체 GPU worker가 역할별 모델 추론을 제공, 외부 유료 AI 서비스 필수 의존 없음
- 회사 장비 확정 전에는 로컬 GPU worker로 같은 역할 포트 검증
- standalone 브라우저 검증은 기존 API 서버의 대화 제어기를 계속 사용
- 로봇 배치는 기존 `robot` 실행 경로와 `company_rpc` 어댑터를 활용하되 별도 인수 필요
- ADR-0006의 독립 브라우저 우선순위·공개 API·Lemmy 추가 수정 보류는 유지

## 결과와 검증

- 개발 환경 Ubuntu 24.04 WSL의 통과 결과를 Ubuntu 26 지원 인증으로 취급하지 않음
- RPC 동시 음성 입력의 queue overflow가 재현되어 로봇 배치 안정성 미확정
- 실제 로봇 오디오·네트워크·회사 GPU 장비 검증은 후속 단계
- 사용자 배치 승인과 구현·성능 인수 완료는 구분
- [아키텍처](../architecture/system.md), [T008](../tasks/active/TASK-20261002-008.md)
