# 테스트 및 인수 검증 안내

## 합성 한국어 왕복 전사 진단

- 실행: `.venv/bin/python scripts/korean-roundtrip-smoke.py --configs config/local/sensevoice/worker.toml config/local/mimic3-generated/worker.toml`
- 고정 10문장·전체 합성 음성·같은 SenseVoice STT, 공백/문장부호 제외 normalized CER와 정확 일치 수 기록
- `korean-roundtrip-smoke.json`: Supertonic CER 3.54%·일치 7/10, VITS CER 7.96%·일치 5/10, 빈 전사 없음
- 작은 합성 표본의 왕복 결과이며 TTS/STT 오류 원인 분리·사람 목소리·청감·일반 품질 인증 아님

## VITS 교체 후 연속 음성 시험

- `mimic3-model-adapter-smoke.json`: 같은 실제 모델의 direct/company_rpc 경로에서 5개 역할 envelope·reset·pre-cancel 통과, 모델 architecture 간 비교 시험 아님
- `browser-mimic3-continuous-voice.json`: 실제 설치 wheel·Chromium·자체 모델·한국어 Mimic3 VITS TTS, 100회/1445.094초 완료
- 같은 capture/연결에서 유효 final·응답 완료 100회, 출력 중 끼어들기 1회, 종료 활성 세션 0
- 합성 입력/무음 출력 조건. 텍스트 문맥 확인은 음성 phase 전 10턴에서 수행
- API/native RSS 관찰 862684 → 891740KiB(96.6 → 1300.1초), Chromium/GPU 제외·전체 누수 판정 아님
- 물리 음성/AEC·Ubuntu 26·30분 기준·100턴 문맥 품질·일반 지연 인수와 구분

## 독립 브라우저 인수 현황

- 기준: [REQ-API-001](../requirements/REQ-API-001.md)의 A01–A09, 현재 파일·실행 결과 확인
- 아래 artifact는 로컬 검증 산출물, 모든 변경 이후 동일 조합 재시험 성공 또는 전체 제품 인수 완료 의미 제외

| 조건 | 확인한 근거 | 남은 범위 |
| --- | --- | --- |
| A01 단일 서버 브라우저/API | API asset/health fixture·현재 localhost:18484 실제 실행·인증 세션 열기/종료 | 대상 Ubuntu 26 실행 |
| A02 텍스트·생성 중 입력 | 실제 Chromium 연속 텍스트·generation 중단, 권한 실패 주입 후 연결 유지 | 사용자 환경 입력/재생 확인 |
| A03 음성 전환·동시 capture | 실제 Chromium 합성 음성 125회·1880.344초 동일 capture 유지·출력 중 입력, capture 변환 3개 | 실제 장치·물리 30분 연속 음성 capture |
| A04 중단·늦은 출력 거절 | generation/ack/native 결과 모사 회귀·실제 합성 끼어들기 | 물리 중단 지연 100회·에코 조건 |
| A05 후속·문맥·회수 | `browser-30-minute-silent-smoke.json` 986회·1801.383초·종료 세션 0, 문맥 검사는 10번째 | 기본 출력 clock 정지·기억 검사 간헐 실패·물리 음성 장시간 |
| A06 자체 GPU·외부 fallback 제외 | network-none 컨테이너 GPU/API/Chromium의 텍스트 10회·합성 음성 응답 2회·GPU 25/25층 | 실제 물리 오디오를 포함한 네트워크 차단 시험 |
| A07 기술별 교체 | 실제 direct/RPC 역할 계약·transducer/SenseVoice STT 교체·설정/manifest 검사 | 모든 역할의 다른 실제 모델 2개·실패/품질 재측정 |
| A08 인증·Origin·TLS | 인증/Origin/세션 상한 fixture·Nginx loopback HTTPS/WSS 실제 10회 | 공인 인증서·회사 배포·WAN·대상 용량 |
| A09 추후 Lemmy API 사용 경계 | standalone 설치 wheel·Lemmy 저장소 없이 브라우저 실행·공개 전송 계약 | 실제 Lemmy 통합은 사용자 우선순위에 따른 후속 단계 |

- 실제 모델 시험의 제한: 합성 입력·buffer ack·무음 sink·물리 출력 여부를 artifact별로 구분
- 수치 목표의 제한: 첫 음성/끼어들기 p95·한국어 정확도·AEC 거짓 중단 기준은 아직 인수 미완료
- 현재 진행: 로컬 브라우저 제공·회귀 검증, 실제 마이크/스피커 접근 가능 여부의 사용자 답변 대기

- `artifacts/offline-env/offline-browser-smoke.json`·`offline-browser-result.json`: 외부 route 없는 동일 network-none 컨테이너의 GPU/API/실제 Chromium·텍스트 10회·문맥·음성 응답 완료 2회·끼어들기 2회·종료 세션 0 통과
- GPU 25/25층 offload 확인, 합성 voice final 3회 중 응답 완료 사이클 2회·Web Audio 무음 sink 재생 ACK 사용. native 시험의 즉시 buffer ACK와 구분
- 시작 실패 artifact 2개 보존, llama 라이브러리 경로 보존·공개 host font 리소스/loader 연결 후 성공. 해당 mount는 컨테이너 내부 읽기 전용이며 호스트 변경 없음
- 브라우저/추론의 외부 AI·인터넷 필수 의존 제거 근거, 물리 음성/AEC·기본 출력 clock 정지 해결·Ubuntu 26/운영 이미지 인증과 구분

- `scripts/offline-voice-smoke.py`: loopback-only interface 확인·외부 route 연결 거절·컨테이너 내부 LLM 실행·native VAD/STT/LLM/TTS 후속 대화 검증
- `artifacts/offline-env/offline-voice-verbose.json`: Docker `--network none --gpus all`에서 GPU 25/25층 offload·유효 음성 final 1회·응답 완료 2회·audio chunk 861개 buffer ACK 통과
- 기존 localforge CUDA image(Ubuntu 22.04)·호스트 Python 3.12/stdlib/공개 shared library·설치 wheel packages·모델의 읽기 전용 bind 사용, 호스트 API/GPU 서비스·네트워크 설정 변경 없음
- 첫 2개 artifact는 GPU 로그 증거 부족으로 failed 보존, 최종 시험은 명시적 verbosity에서 숫자만 추출·원문 로그 미저장
- UI 시작·합성 음성·즉시 buffer ACK 조건, KWS 모델 load와 실제 호출어 검증 구분. 브라우저·물리 재생/AEC·Ubuntu 26/운영 이미지 인증 제외

- `browser-output-text-recovery.json`: 최신 설치 wheel·실제 모델/Chromium에서 기본 출력 clock 정지 후 음성 off 안내·동일 WebSocket 텍스트 응답 완료·종료 세션 0 확인
- 출력 장애 후 텍스트 경로의 복구 증거이며 기본 출력 clock 원인 해결·연속 음성/AEC 성공과 구분

- `browser-output-smoke.py --signal tone --chunk-ms 40`: 절차적 440Hz/amplitude .005 입력, 녹음·모델·마이크·소켓 제외
- `browser-output-tone-chunks.json`의 기본 48kHz는 source 612회 뒤 clock 39.4693/running/output_timeout, 같은 40ms 무음 `browser-output-silent-chunks.json`은 65.019초·1114회 통과
- `pulseaudio-tone-stream.json`: Chromium 없이 pacat/48kHz/mono/50ms latency·100ms tone frame을 wall clock으로 전송, 527회 뒤 drain 3초 timeout·총 55.706초 실패
- 현재 OS 출력 경로의 별도 실패 재현이며 정확한 WSLg 원인 확정/실제 청취 검증은 제외. [WSLg의 PulseAudio/RDP 경계](https://github.com/microsoft/wslg#pulse-audio-plugin) 및 [관련 정지 보고](https://github.com/microsoft/wslg/issues/1508)와 실제 동일 원인 여부 미확정

- 44.1kHz 기본 출력 비교 `browser-default-output-44100.json`: 10회 완료 뒤 11번째의 clock 정지·source 32개, sample rate 정합만으로 해결 불가
- 완료/중단 노드 disconnect 회귀 포함 browser 27개 통과, 기본 48kHz `browser-output-node-cleanup.json` 재시험도 19회 뒤 정지. 노드 정리는 lifecycle 보완이며 clock 근본 원인 해결 증거 아님

- 기본 출력 120초 목표 재현 실패: `browser-default-output-recheck.json` 19회, 진단 추가한 `browser-default-output-diagnostic.json` 21회 뒤 종료
- 진단 시 모델 stage 오류 0·LLM completed/turn_done 21회, 출력 clock running/currentTime 39.888에서 3003.7ms 정지·source 27개 대기·watchdog 오류 처리 후 source 0/연결 종료
- WSLg RDPSink 44.1kHz와 브라우저 48kHz 조건, 정지 근본 원인/기본 출력 안정성 미해결. 무음 sink·짧은 성공 시험은 해당 실패 해결 근거 제외

- 첫 음성 chunk 수신 측정: 브라우저 sendText 시각 → 현재 generation의 첫 수락 audio_chunk, 원시 ms·nearest-rank p50/p95 저장
- `artifacts/browser-audio-receipt-latency.json`: 실제 설치 wheel/로컬 모델/Chromium·145회·240.357초, 수신 지연 p50 204.2ms·p95 392.7ms·종료 세션 0
- 입력 대부분 고정 인사 요청·첫 10회 문맥 검사·무음 sink 조건, cache/warm-up 효과 분리 없음. 발화 종료→실제 출력 지연·다양한 한국어 품질·끼어들기 100회·물리 목표 인수와 구분

- `artifacts/browser-input-id-tls-smoke.json`: input_id 계약 포함 설치 wheel의 실제 모델/Chromium·Nginx HTTPS/WSS 10회·문맥·합성 음성 완료 2회·끼어들기·종료 세션 0 통과
- 최신 설치 wheel Python 73개 통과, 빠른 on/off의 늦은 전사 거절은 browser fixture 26개에 포함. 이 일반 회귀가 물리 장치 경합·AEC·공인 인증서 검증을 대신하지 않음

- `artifacts/browser-idle-recovery.json`: 최신 설치 wheel/실제 Chromium·fixture 추론, 0.7초 유휴 상한 주입에서 종료 안내·AudioContext/socket 정리·새 연결 재시작 2회·종료 세션 0 확인
- 설치 wheel Python 73개 통과, fixture 소켓에서는 PCM 전송 중 유지와 종료 후 연결 용량 회복 확인. 기본 300초 대기·실제 모델/물리 입력 인수와 구분

- 동일 엔진의 실제 LLM 변경: Qwen3.5-0.8B-Q4_0 → 공식 [Qwen3-1.7B-Q8_0](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF), 별도 `config/local/qwen3-1.7b/worker.toml`·manifest로 선택, dialogue/browser 코어 변경 없음
- 파일 SHA-256 `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a`, revision `90862c4b9d2787eaed51d12237eafdfe7c5f6077`, Apache-2.0 LICENSE·모델 카드·provenance ignored artifact 보존
- `artifacts/browser-second-llm-smoke.json`: 실제 설치 wheel/Chromium 텍스트 10회·문맥·음성 응답 완료 2회·종료 세션 0 통과, 음성 final 5회·출력 중 끼어들기 4회 관찰
- 서로 다른 LLM 모델의 같은 엔진 검증이며, 실행 엔진 2개·모든 역할의 실제 모델 2개·한국어 품질 인수와 구분

- `artifacts/browser-continuous-voice-long-smoke.json`: 설치 wheel/실제 모델/Chromium의 동일 capture·연결에서 125회 음성 final 이후 응답 재생 완료, 음성 구간 1880.344초·종료 세션 0
- VAD 18856프레임·STT 4004프레임·nonempty final 125회·출력 중 끼어들기 1회 확인, 입력 합성·Web Audio 무음 sink 조건
- 음성 구간은 첫 final 이후부터 측정, 이름 문맥 검사는 선행 텍스트 2번째 수행. 30분 이름 보존·자연 발화 품질·물리 출력/AEC 검증 제외
- 메모리 관측 `artifacts/browser-continuous-voice-resource-observations.json`: Python API/native audio process RSS 4분 5초부터 29분 55초까지 778936→795248KiB, Chromium/GPU container 제외·메모리 누수 부재 증명 제외

- 출력 단독 진단: `scripts/browser-output-smoke.py --chromium <실행 파일> --duration 65`, 모델/마이크/연결 없이 silent PCM·실제 Chromium 기본 장치 clock 측정
- `artifacts/browser-output-default-smoke.json`: 기본 48kHz 출력·65.774초·65개 source 완료, WSLg RDPSink RUNNING 확인. 기존 대화 조건의 clock 정지 근본 원인 확정 제외
- 출력 단독 성공은 물리 재생/AEC·chunk 스트리밍/모델 동시 실행·장시간 대화 성공과 구분

- `artifacts/browser-30-minute-silent-smoke.json`: 실제 Chromium/설치 wheel/로컬 GPU의 같은 연결에서 1801.383초·986회 텍스트 응답/재생 통과
- 종료 단계의 합성 음성 final 1회·재생 중 끼어들기 1회·종료 세션 0 확인, 문맥 기억은 10번째의 이름 anchor 포함 메시지 19개로 검증
- 장시간 텍스트 구간 마이크 off·무음 sink 조건, 최초 문맥의 30분 보존·연속 음성 capture·물리 재생/AEC 인수 및 기본 출력 clock 정지 해결 증거 제외

- 고정 합성 문맥의 실제 모델 이름 기억 측정: `scripts/context-model-smoke.py --config <설정> --trials 10`
- `artifacts/context-model-smoke.json`: 메시지 19개에서 temperature 0/0.3 각각 10/10 이름 포함 응답, `measured` 상태는 브라우저/한국어 품질 인수 성공 의미 제외
- 브라우저 기억 검사 시 요청의 메시지 수·합성 이름 anchor 포함 여부만 기록, 실제 생성 문맥의 원문 기록 제외

- 장시간 브라우저 시험: `scripts/browser-smoke.py --duration 1800`과 기존 config·Chromium 인자 사용, 같은 연결의 텍스트/재생 구간 최소 시간 검사
- 문맥 기억 검사는 `--turns`번째에서 수행, 이후 반복은 장시간 연결·생성·재생 안정성 검증이며 최초 문맥의 무기한 보존 주장 제외
- 장시간 텍스트 구간의 마이크는 off, 종료 전 음성 입력·재생 중 끼어들기 별도 검사. 30분 연속 음성 capture·실기기/AEC 인수 대체 불가

- 브라우저 부분 자막 초기화·마이크 off의 늦은 부분 전사 제외·빈 전사 상태 보존 회귀: client 18개·capture 3개 통과
- 최신 설치 wheel의 실제 Chromium/로컬 모델: `artifacts/browser-caption-reset-smoke.json`, 10회·문맥 기억·음성 final 1회·재생 중 끼어들기 1회·종료 세션 0 통과
- 해당 브라우저 시험은 합성 입력·48kHz 기본 출력 경로 조건, 실제 마이크·스피커/AEC·30분 연속 브라우저 인수와 구분

## 추가 배치 답변과 무음 출력 재시험

- SenseVoice 실제 VAD/STT 경로 통과: 3회 유효 buffered partial·최종 전사 1회, fixture LLM과 합성 TTS 입력 조건
- `sensevoice-adapter-smoke.json`: 실제 모델 direct/RPC 기본 계약·reset·시작 전 취소 통과, 두 경로는 같은 SenseVoice 가중치 사용
- `browser-sensevoice-smoke.json`: 최신 설치 wheel·실제 모델·Chromium 20회 대화·문맥·음성 final·재생 중 끼어들기·종료 세션 0 통과
- baseline transducer와 대체 SenseVoice는 서로 다른 STT architecture, 교체 시 코어/브라우저의 모델별 분기 추가 없음
- 긴 발화 첫 시험은 gated 처리 뒤 전체 파형의 one-batch 비교 요청에서 SenseVoice 22초 상한 거절. 전체 waveform 비교와 20초 구간 처리 인수 구분
- `--allow-comparison-rejection`을 명시하면 one-batch 거절을 별도 status로 보존, gated final/partial/segment 요구는 유지. 기본 실행은 비교 거절 시 여전히 실패
- `sensevoice-long-speech-smoke.json` 통과: 25.627초 합성 입력·20초 구간 경계 1회·유효 partial 23회·최종 합산 전사 1회/213자
- full/cropped 전체 파형 one-batch 비교는 각각 `input_rejected`, 성공한 긴 발화의 구간 처리와 전체 파형 허용 여부 구분
- 실제 한국어 정확도·사람 발화·마이크/AEC·장시간 browser는 별도 인수, fixture LLM 진단이 실제 assistant 응답 품질 근거는 아님
- 음성 adapter의 빈 결과·모델 lock 대기·HTTP 응답 cleanup 경계에서 취소를 재검사, 늦은 completed 전달 방지
- 해당 계약 회귀 포함 Python 56개 통과, fixture 검사와 실제 모델 취소/브라우저 회귀 구분
- Nginx TLS 시험 경로 추가: `browser-smoke.py --nginx <실행 파일>`, 배포 template·loopback 임시 인증서·실제 installed wheel 사용
- `artifacts/browser-tls-smoke.json` 통과: HTTPS/WSS 경유 실제 Chromium·로컬 모델의 10회 대화·문맥·합성 음성 입력·재생 중 끼어들기·종료 세션 0
- 시험용 자체 서명 인증서의 오류 허용은 Playwright context에 한정, 운영 인증서 신뢰·회사 배포·실제 WAN 검증 아님
- 동시에 실행된 30분 목표 RPC 진단은 전체 실패: capture 2161개·처리 2148개·최대 큐 12, Nginx/브라우저 모델 시험과 실행 구간 중첩
- 실패 뒤 LLM container 약 1.65GiB·호스트 available 약 4.61GiB, 기존 swap 전체 사용과 다른 조건. 추가 동시 실행/지연 분리 필요
- 겹친 두 시험의 결과를 단일 사용자 30분 인수 또는 Nginx 자체 성능 실패로 해석하지 않음
- 긴 발화의 20초 STT 구간 처리 구현, endpoint 합산·전사 초과 후 다음 입력 복구 회귀 포함 Python 44개·browser 15개·capture 3개 통과
- 실제 STT/VAD/TTS의 1.5초 구간 시험은 recognizer final 요청 2회·사용자 final 1회·11자 유효 전사 확인, fixture LLM으로 응답 생성 제외
- 변경 후 `artifacts/browser-segment-regression.json`: 설치 wheel·실제 모델·기본 출력 Chromium의 20회 대화·문맥·합성 음성 끼어들기·세션 회수 통과
- `artifacts/gated-long-speech-smoke.json`은 26.96초 합성 입력이 VAD 발화 8개로 분리되어 20초 구간 분리 인수 실패, `segment_boundaries=0` 명시
- 단순 전체 입력 길이와 실제 한 발화의 지속 길이를 구분, 반복 소스의 앞뒤 무음을 줄인 추가 시험 필요
- 추가 `artifacts/gated-long-speech-continuous.json` 통과: 26.33초 합성 입력·VAD 단일 발화·기본 20초 segment boundary 1회·recognizer final 요청 2회·사용자 final 1회
- 합친 최종 전사는 187자, 단일 waveform 직접 인식은 209–210자. 글자 수 차이는 정확도 지표가 아니며 구간 경계 인식 손실의 평가 필요
- 위 시험은 실제 음성 모델·fixture LLM·합성 입력, 사람의 장문·실제 오디오·전체 assistant 응답 품질 검증과 구분
- 단계별 진단에서 TTS `InvalidOutput` 확인: 문장 뒤 별도 줄바꿈 토큰이 공백뿐인 합성 요청을 생성
- 대화 제어기에서 공백 구절 합성 제외, 텍스트 원문 유지 회귀 포함 Python 42개 통과
- 수정 후 `artifacts/browser-whitespace-soak.json`: 실제 로컬 모델·설치 wheel·Chromium의 20회 대화·문맥 기억·유효 음성 final·재생 중 끼어들기·종료 후 세션 0 통과
- text turn 소요 1.732–4.392초는 전체 응답 재생 시간 포함, 첫 음성 지연 지표와 구분
- 위 결과는 합성 입력·Web Audio 무음 sink 조건, 실제 마이크·스피커·AEC·Ubuntu 26 검증 제외
- 기본 출력 경로의 `artifacts/browser-whitespace-default-soak.json`도 같은 20회 대화·문맥·유효 음성 final·끼어들기·세션 회수 통과
- 기본 출력 시험의 text turn 소요 1.733–8.941초, 합성 입력 유지·물리 오디오 검증 미수행
- 수정 후 서로 다른 출력 경로에서 각각 1회 통과, 30분 장시간 안정성 인수를 대체하지 않음
- 모델 없는 Chromium 진단에서 100개 40ms 오디오 source 모두 완료, 해당 조건에서 clock 정지 미재현
- 오류 직전 멈춘 시각만으로 clock 정지 원인을 단정할 수 없음, TTS 오류가 취소한 미완료 출력과 구분 필요
- 최종 로봇은 입출력·대화 제어, 자체 GPU 서버는 추론. 회사 장비 확정 전 로컬 GPU 사용
- 독립 브라우저 경로는 현재 검증 용도로 유지, [ADR-0007](../decisions/ADR-0007-confirmed-robot-control.md) 참고
- `browser-silent-sink-diagnostic.json` 재시험은 첫 text turn 실패: chunk 39개, accepted ack 7개, 오류 직전 미완료 source 32개
- `turn_failed` 이후 연결 유지·source 정리 확인. AudioContext 시각은 약 0.95초에서 60.51초로 진행
- 이 시험은 영구 clock 정지의 증거가 아님. 서버 turn 실패 원인의 추가 분리 필요
- 실패 artifact에 text playback event·clock·queue 상태 추가, 접속 키·원시 발화·전사 내용 제외
- Python 41개·client 14개·capture 3개 통과, 실제 브라우저 반복 인수 미완료

- **담당:** 프로젝트 소유자
- **마지막 검토:** 2026-10-01
- **현재 실행 가능:** 문서 검사·단위/통신 계약·실제 모델 smoke
- **제품 검증 상태:** 일부 제어/계약·실제 모델 smoke 통과, 전체 V/L/M 인수 미완료

## 실행 가능한 문서 검사

```bash
python3 scripts/check-links.py .
```

마크다운 형식은 문서 CI 또는 설치된 `markdownlint-cli2 '**/*.md'`로 확인.
문서 검사는 음성 기능·Lemmy 연동 성공의 증거로 사용 금지.

## 음성 시나리오

| ID | 관련 요구사항 끝 번호 | 시나리오·관찰 결과 | 계층·작업 |
| --- | --- | --- | --- |
| V01 | 01 | 네트워크 차단 후 실제 모델 대화, 외부 요청 0건 확인 | E2E·T004/T006 |
| V02 | 02 | 호출어/UI 시작, 후속 10회 발화, 종료 뒤 재호출 | 장치·T003/T006 |
| V03 | 03 | 출력 중 capture 프레임과 사용자 STT 입력 지속 | 통합·T003 |
| V04 | 04 | 끼어들기·취소·늦은 토큰/오디오 주입, 이전 재생 0건 | 단위/통합·T003/T004 |
| V05 | 05 | 짧은 쉼·발화 수정·종료 표현, 잘린 전사로 쓰기 실행 없음 | 단위/장치·T003/T006 |
| V06 | 06 | 구절 중간 중단, 재생 확인 범위와 기억 비교 | 통합·T003/T005 |
| V07 | 07 | 종료·유휴·장치 제거 뒤 task·큐·장치 자원 회수 | 통합·T003 |
| V08 | 08 | 한국어 평가셋, 부분/최종 전사·응답·첫 음성 지연 | 모델/E2E·T002/T004 |
| V09 | 09 | 사용자 침묵 10분 재생, 반향·거짓 중단 계측 | 실기기·T006 |
| V10 | 10 | GPU 부족·모델 timeout·큐 초과, 유한 종료·복구 | 통합·T004/T006 |
| V11 | 11 | 오류·진단 경로 로그에 원시 음성·개인 내용 없음 | 통합·T003/T005 |

모든 V ID는 REQ-VOICE-001의 동일 번호 항목과 연결.

## Lemmy 시나리오

| ID | 관련 요구사항 끝 번호 | 시나리오·관찰 결과 | 작업 |
| --- | --- | --- | --- |
| L01 | 01 | 미인증·위조 사용자 문맥 거부, 실행 0건 | T005 |
| L02 | 02 | 실제 메모 조회·알림 조회/등록, 저장 결과 대조 | T005/T006 |
| L03 | 03 | 미허용 도구·오류 인자·모델의 user_id 주입 거부 | T005 |
| L04 | 04 | 등록 중 재연결·재시도·프로세스 재시작, 동일 키 총 1건 | T005/T006 |
| L05 | 05 | 도구 완료 전후 끼어들기, 실제 결과와 상태 일치 | T005 |
| L06 | 06 | 자막·대표 상태·오류 UI, 역순/중복 이벤트 처리 | T005 |
| L07 | 07 | 신규 음성 경로 실패 후 기존 경로의 새 세션, 쓰기 자동 재전송 0건 | T005/T006 |
| L08 | 08 | 기존 인증·생체·DB·안전 정책 회귀, 권한 우회 0건 | T005 |
| L09 | 09 | 두 사용자 세션·기록·메모 분리, 데이터 혼입 0건 | T005 |

모든 L ID는 REQ-LEMMY-001의 동일 번호 항목과 연결.

## 검증 단계

1. 단위: 취소·generation 폐기·endpoint·권한·도구 상태 전이
2. 통합: fake provider로 늦은 결과·timeout·입출력 동시성·중복 등록 검증
3. 모델: 실제 STT/LLM/TTS의 단독·동시 성능과 한국어 평가
4. 장치: 헤드셋 및 실제 스피커의 반향·끼어들기·재생 확인
5. Lemmy E2E: 실제 인증·저장소·UI·오프라인 메모/알림 흐름

fake provider 통과는 실제 모델·장치 검증 완료 근거 아님.

## 측정 규약

- monotonic clock 사용, 분산 호스트 시 clock 정렬과 오차 기록
- 사용자 발화 종료/시작 정답 시각과 VAD 감지 시각 분리
- 첫 토큰·첫 TTS chunk·첫 playback 샘플·최종 이전 음성 샘플 시각 기록
- [요구사항 품질 표](../requirements/REQ-VOICE-001.md#품질과-제약)의 표본과 p95 기준 적용
- cold/warm, 모델별/동시 실행, CPU/GPU 사용량·peak VRAM·실패·timeout 별도 보고
- 30분 soak와 10분 반향 시험에 장치·거리·음량·배경 소음 조건 기록
- 도구 실행 지연과 일반 대화 지연 분리

## 증거 보관

- Task에 명령·환경·revision·날짜·exit code·결과 요약 기록
- 민감 내용 없는 수치 결과와 artifact manifest 보관
- 테스트 구현 전 임의의 `pytest` 성공 주장 금지
- 실행 못한 시나리오의 이유·영향과 후속 Task 기록

## 모델 교체 시나리오

### 실제 어댑터 경로 smoke

```bash
.venv/bin/python scripts/model-adapter-smoke.py config/local/worker.toml
```

- 실제 자체 GPU LLM·Sherpa 음성 모델을 direct adapter와 company_rpc 경로로 각각 실행
- 역할 5개의 모델 identity/capability 협상·event 종류 일치·completed·reset 후 native 세션 제거·시작 전 취소 검증
- LLM의 유효 text delta·STT의 유효 최종 전사·TTS의 PCM bytes/sample rate·VAD 시작/끝 event 확인
- KWS는 이번 합성 문장이 호출어가 아니므로 completed/reset/cancel만 확인, 실제 호출어 감지 인수 근거 아님
- 결과 artifact: `artifacts/model-adapter-smoke.json`, 원시 오디오·전사·접속 키 미기록
- 두 경로는 같은 모델 가중치 사용. 실제 다른 엔진/모델 2개 교체·실행 중 취소·실패 contract·WAN 동시 capture 인수와 구분
- M07 부분 근거, 전체 인수 완료로 처리 금지

### 동시 입력의 처리 완료와 지속 시험

```bash
.venv/bin/python scripts/duplex-gpu-smoke.py config/local/worker.toml --turns 21 --duration 60 --output artifacts/rpc-duration-smoke.json
```

- `--duration`은 최소 생성/capture 지속 시간, 마지막 요청 완료·입력 drain·종료는 추가 시간 소요 가능
- 성공 전 capture 종료·모든 VAD 입력 처리 완료 확인, accepted frame만 세고 미처리 큐를 남기는 성공 판정 금지
- 결과에 processed frame·최대 입력 큐·VAD 호출 시간 포함, buffer 수신 즉시 ack하는 진단이며 실제 재생 지연과 구분
- 진행 artifact의 status/pid/count 기록, 이전 통과 파일을 현재 진행 결과로 오인하지 않도록 시작 시 교체
- 최근 짧은 RPC 시험은 20회 후속·47개 입력 frame·761개 chunk 통과, 입력 drain 보완 전 결과
- 보완 후 60초 RPC 지속 시험은 queue overflow 재현: capture 50개·처리 완료 37개·최대 큐 12개, 전체 실패
- 역할별 단건 adapter smoke와 지속 입력 처리량은 서로 다른 인수. 실제 회사/WAN·30분 안정성 통과로 해석 금지
- 동일 native 지속 시험도 응답 대기 timeout으로 실패: capture/처리 각 55개·최대 큐 12·VAD 최대 2.4773초/평균 0.0615초
- producer 실패를 마지막 요청 완료 후에만 확인하던 진단 경로 보완, next_event와 capture/runtime task를 함께 기다려 입력 실패 즉시 전달
- 두 배치의 지속 실패 근거로 RPC 단독 원인 확정 금지, native latency의 긴 꼬리·호스트 자원·생성 작업 동시성 추가 분리 필요
- 개발 llama-server의 host memory 4.588GiB·swap 전체 사용 관찰. 현재 실행 binary의 `--help`에서 cache-ram 기본 8192MiB 확인
- 개발 container만 `--cache-ram 256`으로 재시작, 동일 GPU/model/context/thread 설정 유지. 재현 실행은 `scripts/start-local-llm.sh`
- 새 조건 `artifacts/rpc-cache-bounded-soak.json` 통과: 60.107초·후속 응답 325회·입력 595개 전부 처리·12351개 chunk·generation 중단 검증
- 최대 입력 큐 1·VAD 최대 0.1602초/평균 0.0027초, 시험 후 LLM container 1.497GiB·호스트 available 약 4.5GiB
- 재시작과 cache 제한이 함께 적용된 결과, cache 설정 하나의 독립 인과 효과·모든 환경의 안정성으로 일반화 금지
- 이 시험은 합성 무음 capture와 즉시 buffer ack, 실제 음성/AEC·재생 시간·30분 안정성·WAN 인수와 구분
- 겹친 모델 시험 종료 후 `artifacts/rpc-30-minute-isolated.json` 통과: 실제 GPU/음성 모델·RPC 1800.181초·후속 응답 9746회
- 입력 17822개 전부 처리·출력 chunk 370349개·최대 입력 큐 1·VAD 최대 0.0844초/평균 0.0024초·generation 중단 확인
- 이 30분 결과는 합성 무음 입력·즉시 buffer ack의 추론/전송 지속 시험, 실제 브라우저의 30분 재생·사람 음성·물리 AEC·WAN 인증 결과 아님

- 상태: 포트·adapter·설정·제어 계약 구현, 아래 전체 모델 교체 인수는 미완료
- [REQ-MODEL-001](../requirements/REQ-MODEL-001.md)의 동일 번호 항목과 대응

| ID | 검증 | 작업 |
| --- | --- | --- |
| M01 | 5개 포트의 표준 I/O, 코어의 SDK 의존 없음 확인 | T003 |
| M02 | 동일 엔진의 호환 모델 2개를 설정만 변경, 코어 diff 없음 | T002/T004 |
| M03 | 역할별 다른 엔진 adapter로 교체, 대화·Lemmy 코어 diff 없음 | T003/T004 |
| M04 | 언어·partial·tool calling·취소 미지원 조합의 명확한 시작 거부 | T003/T004 |
| M05 | load/reset/close·timeout·cancel·늦은 결과·오류 정규화 | T003/T004 |
| M06 | 역할 독립 선택, manifest hash·revision 불일치 및 unknown adapter 거부 | T002/T003 |
| M07 | 역할별 adapter 2개에 동일 contract suite 실행, fake/실제 결과 분리 | T003/T004 |
| M08 | 새 세션 적용·로드 실패 자원 정리·이전 설정 복구, 업무 상태 유지 | T004/T006 |

### 공통 contract suite

- 성공 입출력·정상 완료·빈 입력·잘못된 형식·timeout·정상 취소
- stream 도중 취소·늦은 결과·reset 후 세션 격리·반복 close·자원 회수
- STT partial 교체/final, TTS sample rate/sequence, KWS/VAD 시각과 반복 입력
- LLM 표준 도구 이름/JSON 인자 및 provider별 event 정규화
- 각 역할의 어댑터 2개에 같은 의미 계약 적용, 일부 기능 생략은 미지원으로 표시
- fake suite는 제어 계약 증거만 제공, 실제 모델 2개 검증과 품질 평가 대체 불가
- adapter 2개 확보 전 해당 역할의 실제 교체 인수는 미완료

## 2026-10-01 검증 기록

```bash
.venv/bin/python -m unittest discover -s tests -v
python3 -m compileall -q src
node --check src/real_pa/browser/client.js
node --check src/real_pa/browser/capture.js
```

- 제어·설정·RPC·로봇 입력·Lemmy schema 변환 테스트 20개 통과
- RPC 테스트는 실제 loopback socket + fixture 모델 사용, 실제 모델 품질 시험과 구분
- 기존 CUDA 이미지의 `--list-devices`에서 RTX 3090 인식 확인
- 실제 GPU 서버 LLM: 한국어 응답 완료, 첫 토큰 0.4174초, 총 0.4469초, 단일 표본
- 실제 TTS → streaming STT·KWS·VAD: 전용 고정 환경에서 모델 로드 1.858초, 합성 0.226초/음성 3.12초, 부분 전사 32회·최종 한국어 전사
- 실제 모델 RPC duplex: 생성 중 입력 21프레임, 출력 77chunk, 이전 generation 폐기와 후속 2턴 완료
- duplex 첫 음성 buffer 수신 1.490초, 전체 시험 2.103초. 실제 playback 시각·p95 결과 아님
- artifacts 폴더에 개인 발화 없는 수치 결과 저장, raw 음성 기본 미저장
- 개발 `.venv`와 lockfile 확보, 실제 Ubuntu 26·회사 WAN·로봇 스피커 검증 전
- Lemmy 변경 Python 구문 검사 통과, 실제 전체 앱·인증·알림 DB E2E 미실행
- native 라이브러리·GPU·socket은 sandbox 밖 실행으로 검증, sandbox 접근 제한과 제품 장애 구분

- `.github/workflows/runtime-ci.yml`: GPU 없는 CI에서 제어·RPC 계약만 검증, 실제 모델 smoke는 별도
- 네이티브 라이브러리 호환성을 실제 검증한 sherpa-onnx/core 1.13.5로 고정

### 모델 식별 협상 보강 후 검증 상태

- 최신 변경 후 네트워크 없는 제어·로봇·Lemmy 변환 16개 재검증 통과
- 모델 identity 일치·불일치의 추가 단위 시험 2개 통과
- 전체 실제 소켓 20개 통과 기록은 이전 단계의 증거이며 최신 협상 변경의 회귀 결과로 사용 금지
- 새 소켓 identity 시험과 최신 전체 RPC 회귀: 자동 권한 검토 시간 초과 2회로 실행 미완료
- 자동 검토의 위험 거절 판정이 아니라 실행 승인 절차 시간 초과, 후속 재검증 필요

### 호출어 pre-roll 회귀 검증

- `.venv/bin/python -m unittest discover -s tests -p test_robot.py -v`: 4개 통과
- 호출어 감지 전후 3개 입력 프레임이 순서·내용을 유지하며 STT에 한 번씩 전달되는지 검증
- fixture 입력으로 중복 처리만 검증, 실제 호출어 인식률·마이크·Ubuntu 26 호환성 증거 아님
- `python3 scripts/check-links.py .`: 통과

## 2026-10-02 Lemmy duplex 연결 검증

- real-PA `.venv/bin/python -m unittest discover -s tests -v`: 최신 전체 27개 통과
- 실제 loopback RPC·모델 identity 협상 회귀 포함, 앞선 승인 시간 초과 검증 항목 해소
- Lemmy `tests/test_ws_duplex.py`와 `tests/test_kiosk_auth.py`: 7개 통과
- 실제 JWT·kiosk 인증 코드 사용, 사용자 profile/binding 저장소와 추론 worker는 fixture
- `node tests/browser/voice-duplex.test.cjs`: 5개 통과, 브라우저 API fixture 사용
- 출력 중 capture·즉시 재생 중단·늦은 chunk/ack 폐기·handshake/권한 취득 중 종료·입력 backpressure 검증
- JS 구문 검사와 Lemmy 변경 Python 구문 검사 통과
- 문서 내부 링크 검사 통과, Markdown 42개 파일 형식 검사 0건
- 격리된 Lemmy 시험 환경: Python 3.12.3·FastAPI 0.142.2·pydantic-settings 2.15.0·PyJWT 2.15.1
- Lemmy 배포 lockfile 환경의 전체 앱 검증·실제 브라우저·AEC·도구·DB·Ubuntu 26 인수는 별도 필요

## 2026-10-02 목표 변경 후 standalone API 검증

- 사용자 변경: Lemmy 추가 수정 중단, T008 독립 브라우저·클라우드 API 우선
- `tests/test_api.py`: 실제 localhost HTTP asset·health·WebSocket streaming·인증·Origin·세션 상한 4개 통과
- `node tests/browser/realtime-client.test.cjs`: 브라우저 API fixture 9개 통과
- 마이크 권한 없는 텍스트 연결·연결 유지 마이크 on/off·출력 중 입력·재생 중단·늦은 결과 폐기 검증
- native 취소가 느려도 interrupt가 먼저 반환하는 제어 시험 추가, 실제 native 모델 재검증 필요
- 전체 Python 회귀 37개 통과, 브라우저 fixture 9개 통과
- wheel 빌드·별도 Python 환경 설치·브라우저 asset 5개 포함 확인
- 실제 Chromium 검증 중 음성 최종 전사가 submit의 출력 flush에 지워지는 문제 수정
- 최종 전사의 새 generation 전달을 회귀 검사에 포함
- 설치된 wheel·별도 Python 환경·실제 Chromium·로컬 GPU 모델의 standalone API 시험 통과
- 10회 후속 대화와 이름 문맥 재현 통과, 종료 후 활성 서버 세션 0개
- 각 입력부터 브라우저 음성 버퍼 재생 완료까지 1.783–5.426초, 응답 길이·재생 시간을 포함한 단일 합성 시험
- 브라우저 fake microphone의 합성 한국어 음성으로 최종 전사 1회·재생 중 음성 끼어들기 1회 확인
- `scripts/browser-smoke.py`: Playwright 설치 환경과 Chromium 경로 필요, 실제 사용자 음성·키 기록 없음
- 연속 합성 음성 시험: `--voice-turns 10`으로 같은 capture track을 켠 상태에서 음성 final·응답 재생 완료 10회 검사, 텍스트 구간과 음성 구간 시간 별도 기록
- 합성 final 증가와 응답 완료를 모두 확인한 사이클만 집계, 물리 마이크·스피커/AEC·30분 인수와 구분
- `artifacts/browser-smoke.json`과 스크린샷은 로컬 검증 산출물이며 버전 관리 제외
- headless WebAudio 완료는 실제 스피커 출력 증거가 아니며, 실제 마이크/AEC·Ubuntu 26·장시간·클라우드 배포 검증 필요
- 이후 마이크 permission/on-off 경합·queued frame 폐기 회귀 추가, 브라우저 fixture 11개 통과
- 재생 완료 callback의 순서가 바뀌어도 chunk 순서대로 ack를 보내는 회귀 추가, 브라우저 fixture 12개 통과
- 반복 실브라우저 시험 중 일부 재생 이후 turn timeout 관찰, 순서 보완 후 실제 모델 재검증 진행
- systemd 서비스: 설치 경로를 현재 실행 파일로 치환한 임시 복사본 `systemd-analyze verify` 통과
- Nginx 1.24 임시 binary·합성 인증서·임시 temp path·loopback 고위 포트로 배포 템플릿 `nginx -t` 검사, 실제 서비스 시작·외부 배포 없음
- ack 순서 보완 후 실제 Chromium·GPU로 10회 후속 대화·문맥·합성 음성 끼어들기·종료 세션 0개 다시 통과
- 완료까지 1.666–5.504초, 장시간 안정성이나 모든 timeout 원인의 해결을 증명하는 결과는 아님
- 20회 반복 시험에서 OS 출력 clock이 0.96초에서 정지한 상태 관찰, ack 7개 수락·0개 거부로 ack 순서 단독 원인 가설 제외
- Chromium 합성 출력 장치로 20회 텍스트 대화 완료, 이후 음성 입력에서 provider timeout 발생해 전체 시험은 미통과
- 해당 시점 호스트 RAM 7.5GB 중 가용 약 1.4GB·swap 2GB 거의 소진, 높은 시스템 부하 관찰
- 최신 반복 재실행은 페이지 로딩 단계에서 timeout, 실제 모델 안정성 성공으로 보고하지 않음
- 개별 `turn_failed`는 음성 재생을 중단하고 연결·capture를 유지하여 다음 입력 허용, 브라우저 fixture 13개 통과
- 실패한 capture task의 예외가 session 정리를 막지 않도록 수정, 전체 Python 38개 통과
- 최신 wheel은 cached build dependency를 사용한 `uv build --offline --wheel`로 빌드, 실제 브라우저 재검증 필요

합성 출력 시험은 `scripts/browser-smoke.py --fake-output` 사용. Chromium의 `--disable-audio-output`은 OS 출력 stream을 fake stream으로 대체하는 시험 옵션이다. [Chromium 구현 기록](https://chromium.googlesource.com/chromium/src/+/f29eb01290cd36a30177ecf8197f906c01088a0d) 참조. 이 시험을 물리 출력·AEC 검증으로 해석하지 않는다.

- 같은 실제 WebSocket 연결에서 fixture 추론 실패 뒤 텍스트·PCM 입력·답변 처리 검증 추가, 전체 Python 39개 통과
- 최신 wheel의 full Chromium 시험은 연결 단계에서 timeout, headless shell도 재생 중 audio clock 정지 관찰
- headless shell 실패 뒤 `client.isActive=true`·audio context 유지 확인, 복구 UI는 실제 환경에서 작동
- 브라우저 검증 script에 최종 전사·재생 중 끼어들기 assert 추가, 실패 결과도 상태·수치만 artifact에 기록하도록 개선
- 실제 모델/RPC의 20회 LLM·TTS 후속 응답은 14.464초·761 chunks로 완료, 동시 입력은 51 frames 뒤 queue overflow 발생하여 전체 시험 실패
- 입력 feeder와 runtime 작업의 실패를 성공 조건에 포함, 실패 시 세션·remote provider 정리와 failed artifact 기록 보완
- 이 결과는 텍스트 생성·합성만의 성공이며 연속 음성 입력 안정성 근거가 아님
- VAD 발화 시작 전 200ms를 중복 없이 replay하고 발화 끝 frame을 STT에 전달, 무음 구간 STT 호출 절감 구현
- 호출어 replay·출력 중 VAD 입력·무음 제외·발화 시작/끝 frame 보존 회귀 포함 Python 40개 통과
- 실제 RPC 반복 시험은 개선 후에도 queue overflow 재현, RPC 전송과 API 서버 native 추론 경로 비교 필요
- native 구성의 실제 GPU/음성 모델은 20회 후속 응답·46개 합성 무음 입력 frame·761개 출력 chunk·generation 중단 검증 통과
- native 시험 총 4.618초·첫 출력 buffer 0.607초, buffer 수신 즉시 ack한 진단이며 실제 재생 시간·실마이크·장시간 안정성 측정 아님
- 결과는 `artifacts/duplex-gpu-smoke.json`의 `rpc_transport=false`로 구분, RPC 실패가 해결됐다는 근거는 아님
- 개발 환경 재시작 후 `/tmp` 시험 환경과 임시 GPU container 소실 확인, 기존 이미지·모델로 localhost GPU 서버 복구
- 브라우저 시험 환경을 ignored `artifacts/browser-env`·`artifacts/chromium-libs`에 복구, 실제 OS는 Ubuntu 24.04이며 목표 Ubuntu 26 인수와 구분
- 브라우저 시험은 최대 180초·완료 횟수·PID·failed/passed 상태를 결과 파일로 추적, 이전 stale running 결과를 성공으로 취급하지 않음
- 개선 후 20회 텍스트·음성 단계까지 진행했으나 마지막 문맥/회수 assertion 실패, 세부 조건 기록과 종료 회수 대기 후 재검증 진행
- 16kHz AudioContext 고정 제거, 장치 기본 출력 rate와 Worklet의 16kHz 입력 변환으로 분리
- `node tests/browser/capture.test.cjs`: 16k/44.1k/48k 입력의 render quantum 경계·100ms frame 수·PCM 진폭 보존 3개 통과
- 기존 realtime client fixture 13개 통과, 장치 rate 변경 효과는 실제 브라우저 비교로 확인 중
- 장치 기본 rate의 실제 Chromium 시험은 20회 텍스트 재생 완료·856개 ack 수락·0개 거부, 음성 최종 전사 대기 timeout으로 전체 실패
- 음성 실패를 좁히기 위해 VAD/STT 처리 frame 수·시작/끝 event 수·입력 peak만 수집, 원시 음성·개인 전사 미기록
- 진단 시험에서도 마이크 시작 전 오디오 clock 정지 재현: VAD/STT 입력 frame 수 모두 0, 음성 모델의 실패로 해석하지 않음
- 세션 동안 offset 0의 ConstantSource를 유지하고 종료 시 정리, device graph의 연속 render를 위한 보완
- 보완된 wheel의 실제 Chromium 2회 텍스트·문맥·음성 final 1회·재생 중 끼어들기 1회·종료 세션 0개 통과
- 실제 출력 context rate 44.1kHz, synthetic output device이며 물리 speaker/AEC 검증 아님; 20회 반복 시험 진행
- STT/KWS stream의 `setdefault` eager 생성 제거, utterance/session별 생성·final 후 재생성 회귀 포함 Python 41개 통과
- silent clock 종료/재연결 정리 포함 realtime client fixture 14개·capture 변환 3개 통과
- 같은 구성의 20회 텍스트·문맥 재현 통과, 음성 final 대기 timeout으로 전체 시험 실패
- 해당 음성 단계의 VAD 300 frames·STT 50 frames·시작/끝/final 각 2회·peak 12471 확인, 이번 실패는 입력 미도달과 구분
- final event 발생과 내용 있는 전사를 구분하도록 `nonempty_final` 수치 추가, 원시 전사 미기록
- 직접 합성 waveform→STT 대조: 3.12초 입력·16자 한국어 전사 확인, 실제 browser/VAD 경로와 구분
- 48kHz 출력 비교: VAD 300 frames·STT 46 frames·final 2회 모두 빈 전사, 출력 rate 변경만으로 음성 문제 해결되지 않음
- `scripts/gated-audio-smoke.py`: 실제 audio provider와 production RobotRuntime 사용, fixture LLM은 응답 생성을 억제하여 인식 경계만 진단
- 종료 silence 추가 실험은 빈 전사를 해결하지 못해 제거, VAD 감지 이전 구간 보존을 기본 900ms로 확대
- 확대 후 실제 gated 입력 3.2초·전사 14자·nonempty final 1회 확인, 합성 단일 시험이며 전체 browser/실마이크 성공 증거 아님
- 해당 변경의 전체 Python 41개 통과, 실제 브라우저 재검증 필요
- 최신 wheel·Chromium·GPU의 48kHz 출력/900ms pre-roll 20회 시험 전체 통과
- 문맥 재현·nonempty 음성 final 1회·재생 중 끼어들기 1회·종료 세션 0개 확인
- 음성 입력 VAD 50 frames·STT 30 frames, 입력부터 재생 종료까지 1.733–6.914초; 응답 길이와 재생 시간 포함
- 결과 `artifacts/browser-soak-48k.json`, synthetic input/output device이며 실제 speaker·microphone·AEC 성능 증거 아님
- 통과한 48kHz 출력 설정을 테스트 콘솔 기본값에 반영, 해당 기본 실행 재검증 필요
- 기본값 재검증에서 마이크 전 audio clock 정지 재현, 단일 20회 통과를 안정성 완료 근거로 사용하지 않음
- 최신 `--fake-output`은 Web Audio `sinkId: {type: 'none'}`를 지정하고 실제 sink type을 확인
- 무음 sink는 clock을 진행하며 graph를 render하는 용도, [Chrome 공식 설명](https://developer.chrome.com/blog/audiocontext-setsinkid/) 참조. 초기 `--disable-audio-output` flag 효과를 검증한 결과와 구분
- 무음 sink 시험에서 텍스트 2회·문맥·유효 음성 final 통과, 이후 음성 응답 재생 완료 대기 timeout으로 전체 실패
- 해당 음성 단계 VAD 50 frames·STT 31 frames·nonempty final 1회 확인, 후속 생성·재생 상태 진단 추가

## 8B 연속 음성 지속 시간 검증

- `browser-smoke.py --voice-duration 1800 --voice-turns 100`: 같은 capture/연결에서 최소 30분 및 최소 100회 음성 응답 완료 조건
- 시간 기준은 음성 단계 시작부터 응답 완료까지, 대기 상태만 유지하는 시간 측정 제외
- 현재 실행 증거: ignored `artifacts/browser-qwen3-8b-30min-voice.json`, `running`은 완료 판정 제외
- 합성 입력·무음 출력·로컬 GPU/Chromium 조건, 실제 Windows 장치/AEC·WAN 결과와 구분

## 동시 음성 부하 진단

- 실행: `.venv/bin/python scripts/voice-load-smoke.py --config config/local/qwen3-8b/worker.toml --concurrency 1 2 4 8 16 --rounds 5 --output artifacts/voice-load-capacity.json`
- 별도 loopback 시험 API·실제 공유 모델·100ms PCM 입력·지속 무음 capture·오디오 길이에 맞춘 ACK 사용
- live API 세션 분리, LLM GPU endpoint 공유에 따른 경합 가능. 제품 API 기본 연결 상한은 4, 시험 API 상한만 단계별 최대값 적용
- 첫 오디오 지연: AC RMS 0.001 이상인 마지막 합성 음성 frame 전송 → 첫 audio chunk 수신. 실제 사람 발화 종료·물리 재생 지연 제외
- RAM RSS: 시험 API/모델과 같은 프로세스의 부하 driver 포함, 기존 API·LLM·Windows browser 제외. stage baseline과 sampled peak·lifetime peak 구분
- GPU 메모리: GPU 전체의 1초 간격 표본, live 서비스 포함·사용자별 독립 비용으로 해석 금지
- CPU: 시험 API/driver process의 평균 CPU 시간, 100%는 코어 1개 상당. 순간 peak·LLM CUDA CPU 시간·호스트 전체 CPU 제외
- 실패 client와 완료 요청 모두 집계, 실패 stage 이후 높은 동시성 진행 중단·전체 실패율 별도 검토
- 5회/client 시험의 p95는 예비 지표, 50명 서버 구매·전체 한국어 품질·WAN/물리 AEC 지원 인증 근거로 사용 금지
- 가입자 1000명·동시 음성 사용자 50명은 사용자 답변 기준, 서버 수는 목표 지연을 만족하는 지속 동시성·응답 길이·가용성 여유로 산정

### 2026-10-02 예비 부하 결과

| 동시 합성 음성 client | 완료/요청 | 실패 client | 첫 오디오 p95 | 시험 API/driver peak RSS |
| --- | --- | --- | --- | --- |
| 1 | 5/5 | 0 | 1.668초 | 814MiB |
| 2 | 10/10 | 0 | 2.266초 | 856MiB |
| 4 | 20/20 | 0 | 3.215초 | 960MiB |
| 8 | 40/40 | 0 | 4.137초 | 1018MiB |
| 16 | 5/80 | 15 | 전체 합격 판단 제외 | 1020MiB |

- 증거: ignored `artifacts/voice-load-capacity.json`, RTX 3090·Qwen3-8B·SenseVoice·Supertonic·16 logical CPU/WSL 조건
- 8명 단계의 평균 benchmark CPU 358.1%(약 3.58 core 상당), GPU 전체 sampled peak 8889MiB. live 서비스 경합·RAM의 단계별 allocator 잔류 포함
- 별도 16명 진단 `voice-load-16-diagnostic.json`: 11/16 완료·5개 capture queue overflow, 성공 요청 p95 7.092초. 원래 80회 시험 실패와 표본/상태 차이 유지
- 50명 가정 계산: 동일 응답/빈도의 8명 단위를 단순 복제하면 최소 7개 처리 단위, 30% 여유 가정 시 9개. GPU 서버 대수·지연 보장·서버 구매 사양 확정 근거 제외
- 현재 API 기본 상한 4 유지, 시험에서만 확장. LLM 슬롯/음성 모델 lock·worker 분산·긴 대화/소음/혼합 입력·WAN 시험 후 제품 상한 결정 필요
