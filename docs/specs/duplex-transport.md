# Duplex 전송 계약

- **담당:** 프로젝트 소유자
- **검토일:** 2026-10-02
- **상태:** standalone 브라우저·클라우드 API 개발 계약, 실제 모델·브라우저 인수 진행
- **현재 연결:** real-PA `/v1/realtime`, HTTP 브라우저와 같은 서버·Origin
- **추후 소비자:** Lemmy·다른 승인 클라이언트, 기존 `/ws/duplex` 변경은 미배포 후속 자산

## 인증과 소유권

- standalone API: 접속 token 검증 없음, 브라우저 Origin allowlist, 기본 최대 4개 연결
- standalone 연결: 입출력 메시지 없는 300초 이후 close code 4000·유휴 안내·세션 회수, capture PCM/응답 출력 중 연결 유지
- 해당 상한은 전송 유휴 조건, 마이크를 켠 사용자 침묵의 의미상 종료와 구분. RobotGateway/인증된 Lemmy 경로 기본 종료 정책 변경 제외
- API 접속 키 환경 변수·입력 UI·인증 실행 옵션 없음
- 원격 접속은 TLS proxy·wss, Lemmy 서버의 Origin 없는 연결 허용
- Lemmy 개인 도구 권한은 API 접속 키만으로 부여하지 않음, 실제 업무 권한 연동은 후속 단계
- session_id: 서버 생성 UUID, client의 user/session/binding 값으로 소유권 변경 금지
- 회사 worker credential: Backend 환경 소유, 브라우저 전달 금지
- 모델 설정: 서버에 native/self-hosted 또는 company_rpc 역할 주입, manifest·capability 검증
- 브라우저·미래 Lemmy는 모델 engine·weight·worker credential을 알 필요 없음
- 브라우저 captureDevice는 open({context})에서 MediaStream·echoCancellation:true 반환, close(stream)에서 장치/처리기 자원 동기 정리. open 실패의 부분 자원은 adapter 책임
- controller는 미지원 AEC 결과 거절·늦은 open 결과 정리·마이크 off/종료 시 close 호출, cleanup 실패에도 track 정지
- 이 경계는 브라우저 입력 교체용, software AEC의 render/capture PCM·지연 동기화·실기기 품질 계약 인수 대체 불가

## Client → robot

- input_id: 선택적 0–9007199254740991 정수, 새 브라우저는 마이크 전환마다 증가. 생략한 기존 client는 현재 값 유지
- 서버 transcript_partial/final의 data.input_id는 해당 capture 식별자, 브라우저는 현재 값과 다른 전사 거절
- 식별자 없는 기존 서버 결과는 하위 호환으로 수신, 빠른 입력 전환 격리는 새 서버/client 조합의 계약

| 메시지 | 형식 | 동작 |
| --- | --- | --- |
| start | `{"type":"start","ui_started":true}` | 최초 handshake, true로 호출어 없이 지속 대화, 선택적 system_prompt |
| PCM | binary 3200byte | PCM16 little-endian mono 16000Hz, 정확히 100ms |
| listen | `{"type":"listen"}` | 이전 생성 중단 후 호출어 없이 듣기 활성화 |
| interrupt | `{"type":"interrupt"}` | generation 변경·출력 폐기, 입력은 지속 |
| input_reset | `{"type":"input_reset","input_id":1}` | 입력 epoch 변경·STT/VAD 상태 정리, 연결/출력 유지 |
| text | `{"type":"text","text":"문장"}` | 최종 텍스트 발화, 최대 4000자·선택적 request_id |
| text_ack | generation_id 정수 | 완료한 텍스트 전용 응답의 UI 표시 확인, 현재 generation·최초 확인만 수락 |
| playback_ack | generation_id·chunk_id 정수 | 현재 generation의 다음 chunk 재생 완료 확인 |
| close | `{"type":"close"}` | 입력·생성·재생 종료 |

- text의 선택적 output_audio boolean 기본 true, false는 명시적 텍스트 전용 응답·TTS 미호출
- 텍스트 전용 답변은 최대 16000자, turn_done 이후 text_ack로 확인한 내용만 후속 문맥에 반영. 음성 heard 기록과 표시 확인 구분
- 출력 clock 정지 시 기존 생성 취소·미재생 audio ACK 금지·마이크/음성 출력 off·오류 안내, 같은 연결의 텍스트 요청 유지
- 음성 입출력은 출력 장치 확인 후 사용자의 명시적 새 연결로 복구, 외부 AI 전환/자동 발화 재전송 없음

- handshake: 10초·최대 52096자(JSON escape 포함), ui_started는 boolean만 허용
- system_prompt: 선택, 공백 아닌 문자열·최대 8000자, 연결 동안 모든 LLM 요청의 첫 system 메시지·문맥 축소 대상 제외
- chat_http 설정 system_prompt와 함께 쓰면 운영자 지침 뒤에 연결 지침을 이어 하나의 system 메시지로 전송
- 운영자 지침은 정체성 없는 규칙 한정, 이름·말투·페르소나는 연결 지침(클라이언트) 소유
- Lemmy는 서버에서 조합한 레미 지침만 전달, 브라우저 start의 system_prompt는 upstream 미전달
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
| transcript_final | data.text·generation_id·endpoint_ms | 최종 전사. endpoint_ms는 VAD 종료 판정부터 최종 전사까지(ms), VAD 무음 대기 시간 제외 |
| text_delta | data.text·generation_id | 답변 자막 누적 |
| audio_chunk | data.pcm·sample_rate·chunk_id·generation_id | pcm은 `{"$pcm16":"base64"}` |
| completed | generation_id | LLM 생성 완료, 재생 완료를 뜻하지 않음 |
| turn_done | generation_id | 생성·합성 완료, 재생 ack 별도 |
| input_rejected | data.code·generation_id | 전사 길이 상한 안내, 연결·capture 유지 |
| error | data.code | 민감한 내부 예외 노출 없이 세션 오류 |

- 새 generation보다 낮은 오디오·자막은 폐기, local interrupt 전송부터 서버 확인 전까지 늦은 오디오 재생 금지
- 음성 응답 중단은 새 generation의 `transcript_final`에 `data.control=interrupt` 전달, 자막 확정·listening 유지·LLM 요청 생성 없음
- control은 대화 제어기가 확정한 동작 표시, 클라이언트의 한국어 문자열 비교로 중단 정책 복제 금지
- 전체 발화 `그만`의 중단과 음성 `대화 끝`/`종료`의 종료 판단에서 앞뒤 공백·끝 구두점 `. ! ? 。 ！ ？ …` 제거, 표시 전사 원문 유지
- 명령 앞뒤의 추가 단어·문장과 내부 구두점은 제거 제외, 명령에 관한 질문의 오중단 방지
- 브라우저 마이크 전환·텍스트 입력·연결 종료 시 미확정 부분 자막 제거, 마이크 off 동안 부분 전사 표시 제외
- 빈 부분 전사는 이전 부분 자막 제거, 최종 대화 기록과 응답 재생 상태 변경 제외
- ack: WebAudio onended 근거, 실제 스피커 소리/물리적 재생 시각 증명 아님
- 기억: 현재 연결에서 완전히 ack한 구절만 assistant 문맥으로 반영, 부분 재생 구절은 제외
- 현재 standalone 대화는 업무 도구 미광고·미실행, 선택적 ToolLoop와 Lemmy bridge는 후속 자산
- 오류·종료 후 자동 발화 재전송 금지, 신규 연결은 새 세션

## 실패와 전환

- 추론 서버의 명시적 문맥 한도 거절: 응답 생성 전의 최신 user 입력만 문맥에서 제거·`input_rejected/context_capacity_exceeded` 전달, 이전 대화 보존·다음 입력 허용
- 해당 거절은 ChatHttp/company_rpc 공통 오류로 전달, 일반 HTTP 장애와 구분. 이미 출력/도구 결과가 있는 턴의 기록 자동 삭제 제외
- 출력/도구 이벤트 전 명시적 문맥 한도 거절 시 가장 오래된 user 턴 단위로 제한적으로 요청 축소·재시도, 기존 deadline 유지·최신 입력 보존
- 축소 요청이 수락된 뒤에만 이전 문맥 제외 확정·`context_trimmed` 안내, 최신 입력만으로도 거절되면 이전 문맥 보존. 자동 요약·출력/도구 이벤트 이후 재시도 제외

- 브라우저 microphone track 종료·capture 처리 오류 시 input_reset·마이크 off·자원 정리·안내, 텍스트 연결과 기존 출력 유지
- 입력의 epoch가 바뀐 뒤 도착한 이전 장치 종료 이벤트는 현재 마이크 상태 변경 제외

- 브라우저 미완료 재생 중 오디오 시계가 3초간 정지하면 장치 오류 안내·미재생 chunk ACK 금지·음성 입출력 정리, 동일 연결의 텍스트 모드 유지
- 재생 완료·끼어들기·연결 종료 시 시계 감시 timer 해제, 자동 재생 성공/재연결 주장 제외

- 1008: start 형식 불충족
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

## 명시적 키 없는 브라우저 모드

- API 기본 anonymous mode에서 start의 token 생략 허용, `ui_started`·메시지 형식·Origin·세션 상한 검증 유지
- 테스트 UI 접속 키 입력 제거, `/client-config`는 호환 응답 `requires_token=false` 유지
- CLI API·로컬 실행기 모두 키 없는 모드 기본, `--require-token`으로 인증 선택. robot/worker 인증 변경 없음
- 인증된 사용자 식별·Lemmy 도구 권한 부여와 별개인 anonymous 대화 모드

## 클라이언트 라우팅 도구 (T009)

- 결정: [ADR-0008](../decisions/ADR-0008-client-routed-tools.md). real-PA 구현·fixture 계약·실제 8B 왕복 확인, Lemmy 연동 전
- start에 `route: true`와 `tools`가 모두 있을 때만 활성, 미지정 연결은 기존 동작 불변
- 실행 코드는 클라이언트 소유, real-PA는 정의·호출 요청·결과 전달만 담당

| 방향 | 메시지 | 형식 | 동작 |
| --- | --- | --- | --- |
| C→S | start | `tools`: function 정의 배열(최대 16), `route`: boolean | 연결 동안 사용할 도구 후보 등록 |
| S→C | route_request | data.request_id·text | 발화 확정 후 LLM 시작 전 라우팅 요청 |
| C→S | route | request_id, `tools`: 이름 배열, `tool_choice`: auto/required/none, 선택 `prefetched`·`reply` | 이번 턴 도구 부분집합 결정 |
| S→C | tool_call | data.call_id·name·arguments·request_id | LLM 도구 호출의 실행 위임 |
| C→S | tool_output | call_id, `result`: JSON object | 실행 결과 반환, 응답 계속 |

- route 시한 1.5초 초과·형식 오류·미등록 이름: 도구 없이 응답, 세션 유지
- tool_output 시한 15초 초과: `{"error":"tool_timeout"}`을 결과로 전달, 성공 표현 금지
- tool_output 결과 최대 65536byte, object 외 형식은 실패 결과 처리
- 끼어들기·새 발화로 generation 변경 시 route·tool 대기 즉시 해제, 늦은 응답 무시
- `required`는 부분집합이 1개 이상일 때만 유효, 빈 부분집합은 도구 없이 진행
- 기존 tool_started·tool_result 이벤트는 유지, 클라이언트 반환 메시지는 이름 충돌 방지를 위해 tool_output 사용
- 인자 검증·기본값·권한 판단은 클라이언트 책임, 모델 인자를 그대로 신뢰 금지
- `prefetched`: 클라이언트가 이미 실행한 조회 최대 4개(`name`·`arguments`·`result` object, 결과 65536byte 이하). 이번 턴 도구 메시지로 넣고 도구 없이 답변만 생성([ADR-0009](../decisions/ADR-0009-strong-signal-prefetch.md))
- `reply`: 공백 아닌 500자 이하 고정 문장. LLM 호출 없이 그대로 출력·음성 합성(조회 실패 안내 등 fail-closed). `prefetched`와 함께면 결과도 기록에 남김
- `prefetched`·`reply`가 형식에 맞지 않으면 route 전체를 도구 없음으로 처리
- `required`는 첫 LLM 라운드에만 적용, 결과 수신 후 라운드는 자유 응답
- `required` 라운드는 비스트리밍·최대 96 token 요청, 호출 전 텍스트는 발화하지 않고 폐기(llama.cpp 스트리밍 파서의 호출 유실 회피)
- 강제 라운드에 호출이 없거나 잘린 호출이면 그 출력은 버리고 `tool_choice` 없이 스트리밍 답변으로 전환(실측: 거절 시 7.8초 지연 방지)
- start의 `tools` 사용에는 LLM manifest `tools` feature 필요, 미충족 시 1008
