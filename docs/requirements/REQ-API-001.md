---
id: REQ-API-001
title: 독립 테스트 브라우저와 클라우드 대화 API
status: 초안
owners: [프로젝트 소유자]
created: 2026-10-02
last_reviewed: 2026-10-02
---

# 요구사항: 독립 브라우저 양방향 비서

## 목적과 범위

- 사용자 변경: Lemmy 추가 코드 수정에 앞서 real-PA 자체 브라우저와 대화 기능 구현
- 텍스트·음성 입력과 streaming 답변, 답변 도중 입력·끼어들기·후속 문맥 지속
- 자체 GPU로 시작, 추후 클라우드 배포와 Lemmy의 API 사용
- LLM·STT·TTS·VAD·호출어 기술 교체, 코어·브라우저의 모델 SDK 결합 금지
- 기존 Lemmy 도구·DB·인증 코드는 후속 통합 자산, 현재 독립 브라우저의 필수 의존성에서 제외

## 요구사항과 인수

| ID | 필수 결과 | 검증 |
| --- | --- | --- |
| A01 | 하나의 서버에서 테스트 브라우저와 versioned 대화 API 제공 | HTTP asset·WebSocket 시험 |
| A02 | 마이크 권한 없이 텍스트 입력, 생성 도중 다음 입력 가능 | 실제 브라우저·streaming 시험 |
| A03 | 연결 유지 중 음성 입력 on/off, 출력 중 capture 지속 | Worklet·브라우저·모델 시험 |
| A04 | 응답 중단·음성 끼어들기 후 늦은 출력 재생 금지, 입력 유지 | generation·재생·native 취소 시험 |
| A05 | 최소 10회 연속 후속 대화·문맥 유지·종료 자원 회수 | 실제 모델·브라우저·장시간 시험 |
| A06 | 자체 GPU 추론, 외부 AI 서비스 자동 fallback 없음 | 실제 모델·통신 경계 확인 |
| A07 | 역할별 설정·manifest·registry로 교체, 불충족 capability 명시 거절 | REQ-MODEL-001·교체 시험 |
| A08 | 토큰 없는 대화 API·Origin·상한·클라우드 TLS 배포 경계 제공 | 접속·용량·배포 시험 |
| A09 | 추후 Lemmy가 같은 공개 API 사용, standalone의 Lemmy import 필수 의존 없음 | 패키지·독립 실행 시험 |

- GPT Realtime/Gemini Live는 동시 입력·출력과 연속 대화의 동작 참고
- 품질·지연·반향 성능의 동등성은 실제 측정 결과로만 판단
- 대화 API는 항상 토큰 없이 실행, 키 입력·인증 모드 옵션 제거. Origin/상한 및 worker·robot·Lemmy 업무 인증 유지
- 원시 음성 기본 미저장, 접속 키·개인 발화의 진단 로그 기록 금지
- 연결 단위 system_prompt 선택 제공, Lemmy 페르소나 재사용. 세션 지침은 진단 로그 기록 금지
- real-PA 자체 정체성·페르소나 없음, 최종 persona/system instruction은 클라이언트(Lemmy) 소유
- 실제 물리 재생/AEC·Ubuntu 26·회사 배포는 fixture 시험과 구분

## 추적

- [아키텍처](../architecture/system.md), [클라우드 API 결정](../decisions/ADR-0006-standalone-cloud-api.md)
- [T008](../tasks/active/TASK-20261002-008.md), [전송 계약](../specs/duplex-transport.md)
- [모델 교체](REQ-MODEL-001.md), [음성 품질](REQ-VOICE-001.md)

### 대화 API 접속 정책 (2026-10-02)

- 사용자 요청에 따라 `/v1/realtime` 접속 token 검증·환경 변수·CLI 인증 옵션·브라우저 입력 제거
- Origin allowlist·start 형식·세션 상한·유휴 종료 유지, Lemmy 서버의 Origin 없는 연결 허용
- worker/robot RPC credential 및 Lemmy 사용자·binding 인증 유지
