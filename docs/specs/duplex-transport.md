# Duplex 전송 계약

- **담당:** 프로젝트 소유자
- **검토일:** 2026-10-02
- **상태:** standalone 브라우저·클라우드 API 개발 계약, 실제 모델·브라우저 인수 진행
- **현재 연결:** real-PA `/v1/realtime`, HTTP 브라우저와 같은 서버·Origin
- **추후 소비자:** Lemmy·다른 승인 클라이언트, 기존 `/ws/duplex` 변경은 미배포 후속 자산

## 인증과 소유권

- standalone API: start의 접속 token 확인, 브라우저 Origin allowlist, 기본 최대 4개 연결
- 접속 credential은 REAL_PA_API_TOKEN 환경 소유, 브라우저 입력은 임시 메모리만 사용
- 원격 접속은 TLS proxy·wss, 미래 Lemmy 서버 클라이언트도 같은 start 인증 사용
- Lemmy 개인 도구 권한은 API 접속 키만으로 부여하지 않음, 실제 업무 권한 연동은 후속 단계
- session_id: 서버 생성 UUID, client의 user/session/binding 값으로 소유권 변경 금지
- 회사 worker credential: Backend 환경 소유, 브라우저 전달 금지
- 모델 설정: 서버에 native/self-hosted 또는 company_rpc 역할 주입, manifest·capability 검증
- 브라우저·미래 Lemmy는 모델 engine·weight·worker credential을 알 필요 없음

## Client → robot

| 메시지 | 형식 | 동작 |
| --- | --- | --- |
| start | `{"type":"start","token":"접속 키","ui_started":true}` | 최초 handshake, true로 호출어 없이 지속 대화 |
| PCM | binary 3200byte | PCM16 little-endian mono 16000Hz, 정확히 100ms |
| listen | `{"type":"listen"}` | 이전 생성 중단 후 호출어 없이 듣기 활성화 |
| interrupt | `{"type":"interrupt"}` | generation 변경·출력 폐기, 입력은 지속 |
| input_reset | `{"type":"input_reset"}` | 입력 epoch 변경·STT/VAD 상태 정리, 연결/출력 유지 |
| text | `{"type":"text","text":"문장"}` | 최종 텍스트 발화, 최대 4000자·선택적 request_id |
| playback_ack | generation_id·chunk_id 정수 | 현재 generation의 다음 chunk 재생 완료 확인 |
| close | `{"type":"close"}` | 입력·생성·재생 종료 |

- handshake: 10초·최대 4096자, ui_started는 boolean만 허용
- 이후 단일 메시지: 최대 65536byte/자, 입력 큐 초과 시 세션 실패
- 브라우저: 시작 gesture/마이크 권한·echoCancellation 활성 설정 필요
- 테스트 콘솔의 출력 AudioContext는 48kHz, generic client는 outputSampleRate 미지정 시 장치 기본 rate 사용
- Worklet에서 출력 context와 무관하게 16kHz PCM16으로 변환하여 전송
- 호출어 전 입력: 최근 3개 frame pre-roll, 감지 frame 중복 없이 STT 처리
- raw 음성의 기본 영속 저장 없음
- 텍스트 입력은 마이크 없이 가능, 음성 전환 시 input_reset으로 이전 부분 발화의 늦은 결과 폐기
- request_id는 16–64자의 영문·숫자·underscore·hyphen, 생략 시 서버 생성

## Robot → client

| type | 주요 값 | 동작 |
| --- | --- | --- |
| session_started | session_id | 입력 시작 허용 |
| request_started | data.request_id·generation_id | 현재 발화 식별자 |
| interrupted | generation_id | 기존 playback 즉시 flush, 이전 generation ack 금지 |
| transcript_partial | data.text·generation_id | 부분 전사, 업무 쓰기 실행 근거로 사용 금지 |
| transcript_final | data.text·generation_id | 최종 전사 |
| text_delta | data.text·generation_id | 답변 자막 누적 |
| audio_chunk | data.pcm·sample_rate·chunk_id·generation_id | pcm은 `{"$pcm16":"base64"}` |
| completed | generation_id | LLM 생성 완료, 재생 완료를 뜻하지 않음 |
| turn_done | generation_id | 생성·합성 완료, 재생 ack 별도 |
| input_rejected | data.code·generation_id | 전사 길이 상한 안내, 연결·capture 유지 |
| error | data.code | 민감한 내부 예외 노출 없이 세션 오류 |

- 새 generation보다 낮은 오디오·자막은 폐기, local interrupt 전송부터 서버 확인 전까지 늦은 오디오 재생 금지
- 음성 응답 중단은 새 generation의 `transcript_final`에 `data.control=interrupt` 전달, 자막 확정·listening 유지·LLM 요청 생성 없음
- control은 대화 제어기가 확정한 동작 표시, 클라이언트의 한국어 문자열 비교로 중단 정책 복제 금지
- ack: WebAudio onended 근거, 실제 스피커 소리/물리적 재생 시각 증명 아님
- 기억: 현재 연결에서 완전히 ack한 구절만 assistant 문맥으로 반영, 부분 재생 구절은 제외
- 현재 standalone 대화는 업무 도구 미광고·미실행, 선택적 ToolLoop와 Lemmy bridge는 후속 자산
- 오류·종료 후 자동 발화 재전송 금지, 신규 연결은 새 세션

## 실패와 전환

- 1008: 접속 키·start 형식 불충족
- 1013: 동시 세션 상한, 기존 세션은 유지
- 4401: 선택적 승인 문맥 재검증 실패, 기존 Lemmy 통합 참고 경로의 코드
- 회사 추론 실패: `duplex_unavailable`/`robot_session_failed`, 외부 AI fallback 없음
- 개별 응답 `turn_failed`: 클라이언트 재생 중단·interrupt, 연결과 capture 유지 후 다음 입력 허용
- 긴 발화: 기본 20초마다 STT stream 최종화·정리, VAD 자연 endpoint에서 구간 전사를 합쳐 단일 요청 생성
- 합친 전사 4000자 초과: `input_rejected/transcript_too_long`, 현재 발화의 나머지는 VAD endpoint까지 제외, 다음 발화 허용
- 구간 전사는 메모리에서만 유지, input_reset·close에서 폐기. 로컬 WAV는 최근 제한 오디오 구간이며 긴 발화 전체 녹음과 구분
- 입력 작업/세션 자체 실패는 연결 종료, 종료 정리는 완료된 입력 작업 예외와 무관하게 수행
- rollback: API 종료 후 이전 패키지·설정으로 새 연결, 중단 세션의 자동 발화 재전송 금지
- 현재 연결 간 DB 대화 저장·업무 도구·알림 상태 복구는 미구현
- 검증 근거: [2026-10-02 기록](../guides/testing.md#2026-10-02-lemmy-duplex-연결-검증)

## HTTP 경로

- `/`: 테스트 브라우저, 정적 자산은 package resource로 제공
- `/healthz`: 모델 provider load 이후 ready·protocol_version·역할 목록, 실제 대화 품질/장치 인수 의미 아님
- `/v1/realtime`: WebSocket streaming API, 단일 텍스트 POST 반복 호출로 대체하지 않음
- 키·모델 파일·임의 경로의 HTTP 다운로드 제공 금지
