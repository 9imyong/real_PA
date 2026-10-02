# 아키텍처 결정 기록 안내

- **담당:** 프로젝트 소유자
- **마지막 검토:** 2026-10-01

| ID | 결정 | 상태 |
| --- | --- | --- |
| [ADR-0001](ADR-0001-local-voice-runtime.md) | 외부 AI API 없는 로컬 음성 런타임 | 승인됨: 사용자 방향 반영 |
| [ADR-0002](ADR-0002-session-cancellation.md) | 세션 활동 동시 실행과 generation 기반 취소 | 제안됨: 구현 검증 전 |
| [ADR-0003](ADR-0003-lemmy-boundary.md) | Lemmy의 정책·도구·데이터 소유권 유지 | 제안됨: 실제 어댑터 계약 확인 전 |

| [ADR-0004](ADR-0004-model-ports.md) | 역할별 포트·설정·기능 검증으로 모델 교체 | 승인됨: 설계 방향, 구현 미검증 |

승인된 ADR 원문 보존, 변경 시 새 ADR로 대체 관계 기록.
기술 제안은 후속 구현·검증 결과에 따라 상태 결정. 사용자 방향 승인과 세부 기술 검증 완료 구분.
신규 문서: [ADR 템플릿](ADR_TEMPLATE.md).

- [ADR-0005](ADR-0005-company-gpu-robot.md): 회사 GPU 추론·로봇 제어, 사용자 확정·승인됨
- [ADR-0006](ADR-0006-standalone-cloud-api.md): 최신 사용자 지시, 독립 브라우저·클라우드 대화 API 우선, ADR-0005 배치 대체
- [ADR-0007](ADR-0007-confirmed-robot-control.md): 사용자 추가 답변, 최종 로봇의 입출력·대화 제어와 자체 GPU 추론 분리, 독립 브라우저 검증 유지
- [ADR-0008](ADR-0008-client-routed-tools.md): 클라이언트 라우팅·클라이언트 실행 도구, real-PA는 정의·호출 위임만 담당
- [ADR-0009](ADR-0009-strong-signal-prefetch.md): ADR-0008 보완, 강한 신호 조회의 결정적 사전 실행과 실패 시 고정 안내(fail-closed)
