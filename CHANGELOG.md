# 변경 이력

## 출시되지 않음

### 수정: 취소된 모델 요청의 늦은 완료

- 음성 adapter 처리 시작·빈 결과 완료·HTTP adapter 응답 cleanup 뒤 context 확인
- 취소된 입력 buffer 변경과 늦은 completed/tool call 전달 방지
- 모델 lock·빈 native 결과·HTTP 종료 경계 계약 회귀 추가

### 추가: 명시적 buffered STT 어댑터

- 확보된 SenseVoice 모델용 별도 STT adapter와 주기적 부분 전사·buffer 상한·취소/reset 계약 구현
- baseline을 보존하는 별도 설정 생성, buffered_partial 선언 필수
- fixture 계약 포함 Python 53개 통과, 실제 모델·브라우저·한국어 품질 인수 전

### 수정: 음성 응답 중단 자막

- “그만” 음성 중단의 최종 전사를 새 generation에 전달, 미완료 부분 자막 정리
- 중단 뒤 listening·capture·연결 유지, 다음 입력 허용
- control metadata 전달과 이전 generation 자막 거부 회귀 추가

### 수정: 모델 교체의 정적 구성 검사

- registry 전체 preflight로 미등록 adapter·선언 기능 오류를 모델 load 전에 거부
- check-config에 worker/api/robot profile과 정적 검사 범위 표시 추가
- 실제 load 뒤 provider 기능 검증·실패 cleanup 유지

### 추가: 실제 TLS 프록시 대화 회귀

- 브라우저 smoke에 Nginx 배포 template·임시 loopback HTTPS/WSS 시험 경로 추가
- 실제 모델·Chromium의 10회 대화·음성 입력·끼어들기·세션 회수 통과
- 시험용 인증서 예외는 Playwright context에 한정, 회사 배포·운영 인증서 인수 미완료

### 수정: 개발 GPU 서버의 메모리 상한

- 로컬 LLM 실행 script에 prompt cache 기본 256MiB 상한 적용, 자동 pull·기존 container 삭제 없음
- 개발 호스트 swap 압박 확인 후 해당 container만 재시작, 동일 RPC 60초 동시 입력·응답 시험 통과
- 실제 모델 후속 325회·입력 595개 처리·최대 큐 1, 물리 오디오·30분 안정성 인수와 구분

### 수정: 긴 음성 입력의 세션 종료

- 기본 20초 STT 구간 정리와 자연 VAD endpoint의 단일 요청 처리
- 합친 전사 4000자 초과 안내 후 연결·다음 발화 유지
- 구간 전사 input_reset/close 폐기·최근 bounded WAV 유지
- 실제 모델 구간 lifecycle 진단 통과, 장문 한국어 품질 인수는 미완료

### 추가

- 2026-10-01: project-sample standard 문서 체계 적용
- 로컬 실시간 양방향 음성·Lemmy 연동 요구사항과 통합 목표 설계 작성
- 로컬 실행 방향 ADR 및 취소·Lemmy 경계 기술 제안 작성
- 구현 단계 T002–T006 및 기능·품질·실기기 검증 계획 작성
- 독립 실행 가능한 내부 문서 링크 검사와 문서 CI 제공

위 항목은 초기 문서 기준선. 현재 코드·검증 상태는 아래 후속 기록과 아키텍처 참고.

### 변경

- 2026-10-01: LLM·STT·TTS·KWS·VAD의 역할별 포트·설정·manifest·capability·취소 계약 구체화
- 모델 교체 요구사항 8개와 M01–M08 검증, ADR-0004 추가
- 기존 T002·T003·T004·T006에 교체 구현·실제 adapter 2개 검증 반영

### 추가: 자체 GPU 런타임 개발

- 회사 GPU 추론과 로봇 대화 제어 분리, 사용자 대상 OS Ubuntu 26 반영
- 공통 포트·설정·hash·factory·capability 검증, 자체 SSE/RPC/Sherpa 모델 어댑터
- generation 취소·재생 ack·제한 큐·지속 입력·브라우저 AEC 콘솔
- Lemmy LlmPort bridge 및 selfhosted provider 선택 연결
- 20개 제어·통신 테스트와 실제 GPU/음성/RPC 모델 smoke 통과
- 실제 로봇·Lemmy 도구·반향·p95·모델별 2개 교체 인수는 계속 진행

### 2026-10-02: standalone API 우선순위 변경

- 사용자 목표 변경에 따라 Lemmy 추가 수정 중단, 독립 브라우저·클라우드 대화 API 우선
- 같은 Origin의 HTTP 브라우저·health·인증된 `/v1/realtime`, Origin·세션 상한 제공
- 마이크 없는 텍스트 연결·연결 유지 음성 on/off·streaming 답변·응답 중단
- input epoch·native 취소 정리 분리·늦은 출력 폐기로 연속 입력 보호
- 브라우저 자산의 설치 패키지 포함, REQ-API-001·ADR-0006·T008 추가
- fixture API 4개·브라우저 제어 9개 통과, 실제 브라우저·모델·반향·클라우드 인수 미완료

### 수정: 줄바꿈 토큰의 음성 합성 실패

- 문장 뒤 별도 줄바꿈 토큰을 빈 TTS 구절로 전달하던 문제 수정
- 공백 구절은 합성 제외, 브라우저 텍스트 stream 보존
- 실제 모델 진단의 TTS `InvalidOutput` 확인과 회귀 포함 Python 42개 통과
- 설치 wheel·실제 모델·Chromium의 20회 연속 대화·합성 음성 끼어들기 시험을 무음 sink와 기본 출력 경로에서 각각 통과
- 물리 오디오·장시간 안정성·Ubuntu 26·회사 배포 인수는 미완료
