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

## 클라이언트 계약

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
