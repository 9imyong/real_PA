# 자체 서버 배포

현재 localhost 실제 모델·브라우저와 Nginx loopback HTTPS/WSS 경로 검증 통과.
아래 파일은 배포 템플릿이며 회사 서버·Ubuntu 26·공인 인증서·실제 WAN 환경 검증은 미완료.

## 설치와 설정

1. 서버의 GPU 드라이버와 자체 LLM 서버를 준비한다. LLM endpoint는 TOML의 `providers.llm.options.base_url`로 지정한다.
2. `/opt/real-pa/.venv`에 빌드한 `real_pa-0.1.0-py3-none-any.whl[audio]`를 설치한다. 브라우저 asset은 wheel에 포함된다.
3. TOML·역할별 manifest는 `/etc/real-pa/`에 둔다. 모델 경로·SHA256·capability는 실제 서버 파일에 맞춘다.
4. `realpa` 서비스 계정이 설치 경로·설정·모델을 읽을 수 있게 한다. 추론 서버는 별도 프로세스로 운영한다.
5. `/etc/real-pa/api.env`에 `REAL_PA_API_TOKEN`을 지정한다. 최소 16자이며 실제 값은 저장소·명령 출력에 기록하지 않는다. 파일은 root 소유, 권한 600으로 둔다.
6. [서비스 템플릿](../../deploy/real-pa.service)의 domain·설치 경로를 맞춘다. 인증된 브라우저 Origin은 정확한 HTTPS scheme·host·port로 지정한다.
7. [Nginx 템플릿](../../deploy/nginx.conf)의 domain·인증서 경로를 맞춘다. API는 loopback에 두고 외부에서는 TLS proxy만 노출한다.

서비스와 proxy를 설치한 뒤 `systemd-analyze verify`와 `nginx -t`로 해당 서버의 설정을 검사한다. 템플릿 추가만으로 서비스가 설치되거나 외부에 공개되지는 않는다.

- 서비스 종료 신호: `KillSignal=SIGINT`, CLI의 asyncio 종료·WebSocket 닫기·provider 정리 경로 사용
- 종료 대기: `TimeoutStopSec=90`, native 실행 정리가 초과하면 systemd의 강제 종료 가능
- 로컬 실제 모델 5개 역할 로드 후 SIGINT 종료·exit code 0 확인: `artifacts/service-shutdown-smoke.json`
- 활성 출력 경로: 실제 모델의 첫 audio chunk 수신·ACK 미전송·turn_done 전 SIGINT → WebSocket 1001·exit 0 확인, `artifacts/service-active-shutdown-smoke.json`
- 위 출력 시험의 LLM 텍스트 생성은 이미 완료, LLM 추론 중/native 실행 중 종료·물리 재생·실제 systemd 설치·Ubuntu 26 검증은 별도 인수

## WSL에서 SSH 포트포워딩으로 테스트

- 추론/API 서버: loopback `127.0.0.1:18484` 유지, 브라우저의 localhost 접속을 SSH로 전달
- WSL 클라이언트 터미널에서 실행, `user@server`는 실제 SSH 접속 대상에 맞게 치환

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18484:127.0.0.1:18484 user@server
```

- 클라이언트 브라우저 주소: `http://localhost:18484`, 같은 Origin의 `/v1/realtime`도 같은 터널 사용
- 브라우저가 실행되는 클라이언트의 마이크·스피커 사용, 서버 `/dev/snd` 장치의 필수 의존 없음
- Windows 브라우저에서는 Windows→WSL localhost 전달도 필요, 콘솔/health 접속 성공 여부로 먼저 확인
- 현재 사용자 확인 경로: WSL SSH 터널 → Windows Chrome/Edge, 서버의 WSLg 스피커 경로와 구분
- Windows 브라우저에서 콘솔 연결 후 음성 입력을 켜고 마이크 권한 허용, 응답 중 발화와 후속 대화 확인
- Windows에서 수행한 물리 시험이 없으면 기존 WSLg 실패 또는 synthetic/silent 성공을 해당 경로 결과로 대체 금지
- 클라이언트 포트를 19484로 바꾸면 SSH의 첫 포트만 변경, 서버 API에 `--origin http://localhost:19484 --origin http://127.0.0.1:19484` 추가
- 로컬 실행기도 같은 `--origin` 반복 옵션 지원, 명시한 Origin만 허용

```bash
# 서버 터미널: 접속 키 생성/재사용, 터널 클라이언트의 19484 Origin 허용
.venv/bin/python scripts/start-local-api.py --config config/local/sensevoice/worker.toml --origin http://localhost:19484 --origin http://127.0.0.1:19484
# WSL 클라이언트 터미널: Windows에서 http://localhost:19484 접속
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:19484:127.0.0.1:18484 user@server
```

- 같은 포트 18484는 기본 허용 Origin과 일치, SSH 사용자 인증과 API의 start token 인증은 별개
- SSH 경로는 개발 접속 방식, 실제 회사/WAN 터널·물리 microphone/speaker·AEC 검증은 별도 인수

## 클라이언트 메시지

- 브라우저: HTTPS `/`에서 콘솔을 열고 API 키를 입력한다. 키는 브라우저의 메모리에만 유지한다.
- 미래 Lemmy: `wss://<domain>/v1/realtime`에 연결하고 `start` 메시지에 token과 `ui_started`를 전달한다.
- PCM16 mono 16kHz의 100ms frame을 binary로 전송한다. 텍스트·중단·마이크 reset·재생 ack는 [전송 계약](../specs/duplex-transport.md)을 따른다.
- 서버는 세션 문맥·AI 파이프라인을 제어하고 클라이언트는 입력·AEC·실제 재생과 ack를 담당한다.
- 공유 API 키는 현재 독립 테스트 인증이며 Lemmy 업무 사용자 인증·도구 권한을 대신하지 않는다.

## 배포 확인

로컬 프록시 회귀는 `scripts/browser-smoke.py --nginx <실행 파일>`로 수행.
배포 템플릿의 포트·upstream·인증서를 임시 loopback 설정으로 치환, 실제 Nginx·Chromium·모델 실행.
시험용 자체 서명 인증서만 사용하고 browser의 인증서 오류 허용은 해당 시험 context에 한정.
배포 서버 인증서 체인·신뢰 검증을 대체하지 않음.

- `/healthz`·콘솔 asset·WebSocket 인증·허용/거부 Origin·동시 세션 상한 검사
- reverse proxy 경유 10회 후속 대화·음성 입력·재생 중 끼어들기·disconnect 후 자원 회수 검사
- 실제 microphone/speaker·AEC·지속 대화 지연·GPU 메모리 측정
- 모델·엔진 변경 후 [모델 교체 시나리오](testing.md#모델-교체-시나리오)와 대화 회귀 검사

현재 서비스 상한은 4세션이다. 모델별 native lock으로 일부 추론이 직렬화되므로 이 값이 동시 실시간 품질 보장은 아니다. 초기 운영은 1명 대화로 측정한 뒤 확장한다.
