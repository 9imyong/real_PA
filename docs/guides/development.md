# 개발 환경 안내

- **담당:** 프로젝트 소유자
- **마지막 검토:** 2026-10-01
- **현재:** Python package·worker·robot gateway·browser 콘솔 구현 진행

## 문서 검증

```bash
cd /home/joon/code/real-PA
python3 scripts/check-links.py .
```

Python 3.10 이상 필요. 링크 검사는 저장소 상대 파일 경로만 검사하며 외부 URL·앵커의 의미·런타임 동작 보장 없음.
GitHub CI는 마크다운 형식과 내부 링크 검사 수행.

## 모델 개발 후보 환경

- Linux/WSL2와 GPU 추론 환경 후보, 실제 지원 버전은 T002 측정 후 고정
- STT·KWS·VAD의 CPU 배치와 LLM·TTS의 GPU 동시 배치 비교
- PC 헤드셋 → 스피커 → Lemmy 로봇 순서로 장치 조건 확대
- 모델·의존성은 준비 단계에서 확보, 오프라인 검증 시 외부 통신 차단
- LocalForge의 기존 장비·모델은 후보 기준이며 그대로 제품 모델 확정 금지

## 첫 구현 전 기록

1. 운영체제·GPU·드라이버·런타임·오디오 입출력 장치 기록
2. 모델 원본·revision·파일 SHA256·라이선스 기록
3. CPU/GPU 메모리, cold/warm 지연, 단독/동시 실행 결과 기록
4. 한국어 평가 입력과 예상 전사·도구 인자·합격 기준 확정
5. 해당 Task에 증거와 실행 명령 기록, 아키텍처 현재 상태 갱신

## 설정 정책

- 로컬 LLM 선택: `prepare-local-config.py --llm-model <기존 GGUF 경로> --output-dir <새 설정 폴더>`, 상대 경로는 `--models-root` 기준·절대 경로 허용
- 서버 model alias는 `--llm-model-id <이름>`으로 지정, 생략 시 GGUF 파일명 사용. 선택 파일의 SHA256은 manifest에 기록
- 생성 설정의 출력 한도 기본 512 token, `--llm-max-tokens`로 조정. 기본 system prompt 없음, `--llm-system-prompt`는 정체성 없는 운영 규칙에만 사용
- GPU 실행기의 context 기본 8192 token, `REAL_PA_LLM_CONTEXT`로 512–32768 범위 선택. 실제 모델 지원 길이와 GPU 메모리 확인 필요
- 별도 설정 생성 후 `check-config --profile api`와 실제 서버/모델 시험 필요, alias 정적 검사는 실제 다른 모델의 한국어 품질·교체 성공 증거 제외

- `chat_http` adapter 생성 시 `max_tokens`는 양의 정수, `temperature`는 유한한 0 이상 수, `enable_thinking`은 boolean으로 검증
- `system_prompt`는 operator 설정의 비어 있지 않은 4000자 이하 문자열, 각 요청의 첫 system message로 삽입. 세션 기록 변경·모델별 코어 분기 없음
- real-PA는 정체성 없는 추론·도구 오케스트레이션 계층. 이름·말투·페르소나는 클라이언트 start의 `system_prompt` 소유, operator 설정에 정체성 기술 금지
- 설정 변경은 API 재시작 후 새 세션에 적용, 잘못된 기존 응답이 쌓인 대화는 재연결 필요. 모델 context와 세션 기록 상한에 따른 오래된 대화 삭제 가능
- 순차 한국어 진단: `scripts/llm-quality-smoke.py --config <worker.toml> --review`, 합성 입력만 사용·artifact에는 길이/종료 사유/회상 지표만 저장. 사실 정확도는 답변의 별도 검토 필요
- 현재 로컬 검증 설정: ignored `config/local/qwen3-8b/worker.toml`, 공식 Qwen3-8B-Q4_K_M·SenseVoice·Supertonic. 모델 준비 후 `bash scripts/start-local-llm.sh artifacts/models/qwen3-8b/Qwen3-8B-Q4_K_M.gguf`, `.venv/bin/python scripts/start-local-api.py --config config/local/qwen3-8b/worker.toml` 순서
- 0.8B 기본 파일은 이전 연결 시험용 자산, 한국어 대화 품질 보장 제외. 8B 시험에서도 사실 오류 관찰, 모델 크기 증가만으로 정확도 보장 불가
- `token_env`는 환경 변수 이름, `base_url`은 HTTP(S) 주소와 유효 port 형식 요구. 잘못된 값은 HTTP client 생성 전 거절
- 해당 옵션 검사는 adapter 생성 단계, `check-config`의 정적 manifest 검사와 실제 엔진별 옵션 지원·품질 측정 구분

현재 환경 변수: REAL_PA_WORKER_TOKEN·REAL_PA_ROBOT_TOKEN, operator가 직접 설정한 token_env.
비밀 값은 환경에서 읽고 설정·로그·명령 예제에 실제 값 기록 금지.
구현 시 모델 경로·장치·sample rate·큐 상한·timeout·유휴 종료·로그 수준 설정 명세와 기본값 제공.
비밀 값·원시 음성·개인 전사·모델 가중치는 버전 관리 제외.

## 장애 확인 순서

| 증상 | 확인 |
| --- | --- |
| 자체 답변을 사용자로 인식 | AEC render 참조·장치 지연·출력 음량 |
| 끼어들어도 이전 음성 지속 | 재생 큐 flush·취소 완료·generation 검증 |
| 응답 지연 증가 | endpoint 지연·첫 토큰·첫 TTS chunk·큐 깊이·GPU 경쟁 |
| 알림 중복 등록 | operation_id·내구성 기록·timeout 뒤 재전송 정책 |

위 항목은 진단 계획이며 현재 구현된 장애 처리 기능 목록 아님.

## 모델 어댑터 추가 절차

1. [모델 교체 계약](../architecture/system.md#모델-교체-계약)의 역할 포트 구현
2. provider SDK 자료형·오류·이벤트를 표준 자료형으로 변환
3. manifest와 capability 검증·허용 factory registry 등록
4. 동일 contract suite와 실제 모델 품질·자원 평가 수행
5. 설정에서 선택, 새 세션 적용 및 기존 V/L 회귀 확인

실행 설정은 TOML과 JSON manifest 사용. 아키텍처의 YAML은 의미 설명용 예시.

## 자체 GPU 개발 실행

1. `uv sync --locked --extra audio --extra dev`로 전용 환경 준비
2. 기존 모델 경로를 명시하여 manifest 생성, hash 검증

```bash
.venv/bin/python scripts/prepare-local-config.py --models-root ../stt_test/models
.venv/bin/python -m real_pa.cli check-config config/local/worker.toml
```

- 개발 CUDA 서버: 기존 `localforge/llama-cuda:56b9eb280a67` 이미지와 Qwen3.5-0.8B GGUF 사용
- 준비된 이미지·모델의 실행: `bash scripts/start-local-llm.sh`, 모델 경로는 첫 인자로 교체 가능
- 개발 LLM prompt cache 상한 기본 256MiB, `REAL_PA_LLM_CACHE_MIB`로 명시적 조정. 자동 이미지 pull·기존 container 삭제 없음
- 현재 llama.cpp의 기본 cache-ram 8192MiB는 7.3GiB 개발 호스트 메모리보다 큼, 모델/오디오/OS 메모리와 별도로 상한 설정 필요
- prompt cache는 추론 가속용 상태, real-PA 대화 history와 구분. cache 축소로 세션 문맥을 삭제하지 않음
- 모델 선택은 한국어·도구 품질 최종 선정 결과 아님
- 모델·샘플 라이선스 검토 전 배포 금지, 생성한 개발 manifest에 미확인 상태 명시
- `config/local/`, 가중치·음성·평가 artifact는 Git 제외
- LLM HTTP endpoint는 operator 설정, 도구 인자·사용자 입력으로 변경 금지
- API/robot 배치의 정적 검사: `real-pa check-config <설정> --profile api` 또는 `--profile robot`
- 정적 검사는 역할·등록 adapter·manifest/hash·선언 capability 확인, 모델 load·실제 서버 협상·품질·adapter 옵션 검증은 실행 시 별도 수행
- worker profile은 부분 역할 구성을 허용, API/robot profile은 대화에 필요한 5개 역할과 선언 기능 요구

### Worker와 로봇 gateway

충분히 긴 REAL_PA_WORKER_TOKEN·REAL_PA_ROBOT_TOKEN을 shell 환경에 설정한 후 실행.
문서에 실제 토큰을 넣거나 개발 token을 Lemmy 사용자 인증으로 사용 금지.

```bash
.venv/bin/python -m real_pa.cli worker config/local/worker.toml
```

다른 터미널에서 로봇 gateway 실행. 같은 PC에서 직접 모델을 연결하는 개발 실행이며,
회사 서버 분리 시 각 provider의 adapter를 company_rpc로 선택하고 worker token_env와 wss URL 지정.

```bash
.venv/bin/python -m real_pa.cli robot config/local/worker.toml
```

독립 API와 브라우저는 아래 같은 포트에서 실행. 이전 별도 HTTP 콘솔은 패키지 자산으로 이동.

```bash
.venv/bin/python -m real_pa.cli api config/local/worker.toml
```

브라우저에서 localhost:18484를 열고 REAL_PA_API_TOKEN과 같은 접속 키 입력 후 연결.
마이크 수집은 사용자가 시작 버튼을 누른 이후만 수행, 대화 종료 시 track 중지.
브라우저 echoCancellation 지원 필요. 테스트 콘솔은 48kHz AudioContext를 사용하며 입력은 Worklet에서 16kHz로 변환. 실제 AEC 성능은 별도 평가.

### 실제 모델 smoke

#### 대체 STT: SenseVoice buffered partial

```bash
.venv/bin/python scripts/prepare-local-config.py --models-root ../stt_test/models --stt-model sensevoice --output-dir config/local/sensevoice
.venv/bin/python -m real_pa.cli check-config config/local/sensevoice/worker.toml --profile api
```

- adapter `sensevoice_buffered`, 로컬 SenseVoice ONNX·tokens 사용, baseline 설정과 별도 디렉터리
- offline 엔진에 현재 발화 구간을 모아 기본 1초마다 부분 전사를 다시 인식, VAD endpoint에서 최종 인식
- `buffered_partial` capability 선언 필수, 네이티브 streaming transducer로 취급하거나 조용한 fallback으로 사용 금지
- 기본 입력 buffer 22초 상한, 코어의 20초 구간 분리와 pre-roll 수용. max_seconds는 최대 30초
- 실제 모델 VAD/STT 경로·direct/RPC adapter·20회 합성 입력 브라우저 회귀 통과, [검증 기록](testing.md) 참고
- 한국어 정확도·실제 마이크/AEC·긴 발화·반복 안정성은 별도 인수, native streaming으로 표기 금지

#### 기본 모델 smoke 실행

로컬 CUDA LLM endpoint 준비 후 실행.

```bash
.venv/bin/python scripts/gpu-smoke.py
.venv/bin/python scripts/audio-model-smoke.py config/local/worker.toml
.venv/bin/python scripts/duplex-gpu-smoke.py config/local/worker.toml
```

- 마지막 시험: 실제 모델·RPC·지속 합성 입력·끼어들기·후속 2턴 확인
- 실제 마이크·스피커·Lemmy 도구 인수 증거로 사용 금지
- 회사 전체 모델 추론은 서버 역할 배치의 의미, STT/TTS까지 CUDA에 배치 완료를 뜻하지 않음

### 로봇 전용 RPC 설정 생성

```bash
.venv/bin/python scripts/prepare-robot-config.py config/local/worker.toml --url ws://127.0.0.1:18282
.venv/bin/python -m real_pa.cli check-config config/local/robot/robot.toml
.venv/bin/python -m real_pa.cli robot config/local/robot/robot.toml
```

- 회사 접속 시 실제 회사 wss endpoint 사용, worker와 robot은 별도 호스트에서 실행
- 생성한 로봇 manifest는 모델 경로·가중치 없이 model_id·revision·runtime·artifact hash 보유
- 로드 시 worker의 실제 identity와 capability 대조, 불일치 연결 거부
- 위 loopback URL은 로컬 개발 예시이며 회사 주소를 저장소에 기록하지 않음

### Lemmy 인증·UI 연결

- 최신 목표에서는 후속 단계. 아래는 기존 미배포 구현 참고, standalone API의 필수 실행 절차 아님.
- Lemmy 환경에 real-PA 설치, 최초 개발 설치 예시: `python -m pip install -e ../real-PA`
- `VOICE_DUPLEX_ENABLED=true`, `VOICE_DUPLEX_CONFIG`에 robot 전용 TOML의 실제 절대 경로 지정
- robot 설정의 모든 역할은 `company_rpc`, worker credential은 Lemmy 프로세스 환경에만 제공
- 기존 QR pairing 쿠키 필요, 개발 robot token으로 Lemmy 인증 대체 금지
- 기존 화면의 음성 시작 버튼 또는 마이크 권한/gesture로 시작, 답변 중 입력 지속
- master off·페이지 종료·연결 실패 시 마이크와 재생 정리, 재연결 시 이전 발화 자동 재전송 없음
- 현재 신규 경로는 음성·일반 대화·자막 지원, 메모·알림 도구와 DB 기억 연결 전
- 도구 없는 프로필의 의미를 제품 인수 완료로 대체 금지, 실제 Ubuntu 26·로봇 검증 필요
- `VOICE_DUPLEX_ENABLED=false` 후 새 연결부터 기존 경로 사용
- [전송 계약](../specs/duplex-transport.md)

## 독립 API와 테스트 브라우저

- 빠른 로컬 실행: `.venv/bin/python scripts/start-local-api.py --config config/local/sensevoice/worker.toml`
- 기본 localhost:18484·loopback 전용, REAL_PA_API_TOKEN이 없으면 `config/local/browser.token`을 소유자 전용 mode 600으로 생성·재사용
- 브라우저 접속 키 칸에는 파일 내용 입력, 키 값의 터미널/진단 출력 제외. 기존 환경 키가 있으면 해당 값 우선 사용
- 기존 키 파일의 잘못된 권한·길이·symlink는 덮어쓰지 않고 거절, 실행 종료는 Ctrl+C
- 실제 사용 확인 순서: 텍스트 대화 → 마이크 on/후속 발화 → 답변 도중 끼어들기 → 마이크 off/텍스트 → 종료
- 스피커 반향 시험: 사용자 침묵 중 답변의 자체 인식·거짓 중단 관찰, 합성/헤드셋 성공과 구분. 실제 측정 전 AEC 성능 보장 제외

1. `uv sync --locked --extra audio --extra dev`로 환경 준비
2. 자체 GPU LLM 서버와 로컬 모델 manifest 준비, 기존 `prepare-local-config.py` 사용 가능
3. REAL_PA_API_TOKEN 환경에 16자 이상의 접속 키 설정
4. API 실행, 브라우저에서 같은 접속 키 입력

```bash
.venv/bin/python -m real_pa.cli api config/local/worker.toml
```

- localhost:18484에서 브라우저·API 제공, `/v1/realtime`은 추후 Lemmy도 사용할 공개 경로
- 기본은 텍스트 연결, 음성 입력 checkbox로 연결 중 마이크 on/off
- Enter 전송·Shift+Enter 줄바꿈, 답변 도중 새 텍스트 입력/음성 끼어들기 지원
- 응답 멈추기는 입력/연결 유지, 대화 종료는 microphone·playback·socket 정리
- 브라우저 접속 키만 사용, 모델 worker credential·SDK·Lemmy 설정 전달 없음
- 기본 loopback 바인딩, 원격 배포는 TLS proxy와 명시적 `--origin https://배포도메인` 필요
- 모델 config만 변경해 역할 교체, API/브라우저 계약과 코어에 모델별 분기 추가 금지
- native 모델의 취소 정리는 별도 추적, 입력은 재생 flush 이후 계속 진행
- [요구사항](../requirements/REQ-API-001.md), [전송 계약](../specs/duplex-transport.md)

## 자체 GPT-SoVITS TTS 연결

### 한국어 VITS 대안

- `sherpa_vits_korean`: 공식 Sherpa 릴리스의 `vits-mimic3-ko_KO-kss_low` 전용, 기존 Supertonic과 별도 architecture
- options: `num_threads`(양의 정수, 기본 2), `speed`(유한한 양수, 기본 1)
- manifest: role `tts`, languages `ko`, features `phrase/chunks/cancel`, sample_rates `[22050]`
- named artifacts `model`(ONNX), `tokens`, `phondata`(espeak data 내부 파일), 전체 espeak data 파일별 해시 보존
- native 작업 취소의 출력 폐기/실행 종료 대기 계약 재사용, 대화 코어와 브라우저 변경 없음
- 로컬 별도 설정: `config/local/mimic3-korean/worker.toml`, 기본 설정 자동 교체 제외
- 설정 생성기로 선택: `--tts-model mimic3-korean --vits-dir <압축 해제 디렉터리>`, 기본 선택은 `supertonic`

```bash
.venv/bin/python scripts/prepare-local-config.py --models-root ../stt_test/models --stt-model sensevoice --tts-model mimic3-korean --vits-dir artifacts/models/mimic3-korean/vits-mimic3-ko_KO-kss_low --output-dir config/local/mimic3-generated
.venv/bin/python -m real_pa.cli check-config config/local/mimic3-generated/worker.toml --profile api
```

- 모델 상류 CC0 파일·archive SHA256는 ignored 자산 provenance에 기록, espeak data 배포 권리 확인은 별도 필요
- 실제 모델 browser 10턴·합성 음성 2회·끼어들기 통과, 문장부호 skip 경고·음질/물리 재생은 검증 전

### HTTP 연결

- `gptsovits_http`: 기존 tts-serving 또는 자체 GPT-SoVITS `/tts` endpoint용 한국어 어댑터
- [상류 요청/출력 구현](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/api_v2.py)의 `media_type=raw`, `streaming_mode=true` 사용
- TTS provider의 adapter만 `gptsovits_http`로 선택, 다른 역할·대화 코어 유지
- options 필수: `url`(전체 POST endpoint), `sample_rate`(16000/24000/32000/48000), `ref_audio_path`(서버 로컬 파일)
- options 선택: `prompt_text`, `prompt_lang=ko`, `token_env`(자체 gateway X-API-Key의 환경변수 이름)
- manifest: role `tts`, features `phrase/chunks/cancel`, languages `ko`, sample_rates에 실제 출력률 포함
- 모델 revision·hash·license는 실제 배치 자산 기준으로 작성, 참조 음성/전사·접속 키는 버전 관리 제외
- raw 응답의 sample rate metadata 부재: 서버 모델 출력률과 설정의 일치 확인 필수, 기본값 추정 금지
- 설정 출력률의 manifest 누락/불일치는 시작 거부, 서버의 실제 출력률까지 자동 탐지하는 계약 아님
- mono PCM16LE의 `audio/raw` 또는 `application/octet-stream` 응답만 수용, WAV/JSON·빈 출력·홀수 byte 종료 거부
- 40ms chunk와 마지막 부분 frame 전달, task 취소/전체 deadline 시 응답 닫기·완료 event 금지
- 응답 body read 정지 중 Context 취소 신호도 즉시 처리·pending read 정리, 동시에 도착한 chunk 폐기
- 응답 header 대기에도 같은 취소 경계 적용, 취소와 함께 도착한 HTTP response는 전달 없이 닫기
- HTTP 연결 취소는 클라이언트 결과 수신 중단, 서버 GPU 작업의 즉시 취소 보장 아님
- 현재 검증: 전송 fixture·오류·취소 계약. 실제 GPT-SoVITS 모델·한국어 품질·browser 음성 회귀 미완료

## SenseVoice 무음 입력 억제

- `min_signal_rms`: 100ms 구간의 DC 제거 RMS 중 최대값, 기본 0.001(PCM 정규화 기준 약 -60dBFS)
- 기준 미만 입력은 decode 생략·빈 전사 반환, 특정 단어 삭제 없음
- 0으로 비활성화 가능, 설정 범위 0–0.05. 아주 작은 목소리의 누락 가능성 및 장치별 조정 필요
- 무음/낮은 잡음의 실제 `그.` 생성 재현 후 억제 확인, 일반 잡음·반향의 음성 여부 판정 보장 제외

## 접속키 없는 브라우저 실행

- 로컬 실행기 기본 anonymous mode, 브라우저의 접속키 입력칸 숨김·키 없는 start 허용
- CLI 직접 실행도 기본 anonymous mode, 접속키 인증은 `real-pa api <worker.toml> --require-token`
- `/client-config`: `requires_token` boolean만 제공, 키 값 전달 없음
- anonymous 모드의 WebSocket은 허용 browser Origin 필요, Origin 없는 연결·외부 Origin 거절 및 기존 세션 상한 유지
- 인증 모드 재선택: 로컬 실행기 `--require-token`, 기존 키 파일 재사용
