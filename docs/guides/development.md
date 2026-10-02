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
