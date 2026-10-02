# real-PA

외부 AI API 없이 자체 GPU의 모델로 동작하는 실시간 양방향 비서. 테스트 브라우저로 텍스트·음성을 입력하고, 추후 Lemmy가 동일한 클라우드 API를 사용.

## 프로젝트 개요

| 항목 | 내용 |
| --- | --- |
| 목적 | 지속 텍스트·음성 대화, 듣기·말하기 동시 처리, 끼어들기, 맥락 유지 |
| 주요 사용자 | 한국어로 대화하는 사용자 |
| 현재 상태 | 런타임·자체 서버 어댑터 구현 진행, 실제 모델 RPC smoke 통과, Lemmy·실기기 인수 미완료 |
| 문서 기준 | project-sample의 standard 티어 |
| 담당 | 프로젝트 소유자 |
| 마지막 검토 | 2026-10-02, Asia/Seoul |

## 구현 방향

- 로컬 호출어 → 반향 제거·VAD → 스트리밍 STT → 로컬 LLM → 구절별 TTS 구성
- 입력·생성·출력의 동시 실행과 대화 제어기의 세션·취소 관리
- 현재 우선순위: 독립 테스트 브라우저와 자체 대화 API, Lemmy 추가 수정은 후속 단계
- 추후 Lemmy는 배포된 real-PA API의 클라이언트, 업무 정책·데이터 소유권 유지
- 모델·의존성 최초 확보 후 핵심 대화·메모·알림의 외부 통신 없는 실행
- 날씨·뉴스 등 외부 정보 기능은 오프라인 핵심 인수 범위에서 제외

## 빠른 시작

현재 실행 가능: 환경 검사·설정 검증·추론 worker·독립 대화 API·테스트 브라우저.
API 서버에서 세션·모델 파이프라인·취소 제어, 브라우저에서 마이크·AEC·스피커 처리.
개발 GPU는 로컬 RTX 3090, 대상 OS는 Ubuntu 26. 실제 Ubuntu 26 검증 전.
최종 Lemmy 배치는 로봇의 입출력·대화 제어와 자체 GPU 서버의 추론을 분리.
회사 장비 확정 전에는 로컬 GPU 사용. [배치 결정](docs/decisions/ADR-0007-confirmed-robot-control.md).

```bash
cd /home/joon/code/real-PA
python3 scripts/check-links.py .
.venv/bin/python -m real_pa.cli api config/local/worker.toml
```

- 문서 검증 요구 환경: Python 3.10 이상
- API 접속 키 검증 없음, 기본 실행 후 브라우저·Lemmy 연결 가능
- 로컬 실행: `.venv/bin/python scripts/start-local-api.py --config config/local/worker.toml`
- 종료: 실행 터미널의 Ctrl+C
- 브라우저: localhost:18484, 텍스트는 마이크 권한 없이 사용, 연결 중 음성 입력 전환 가능
- 모델·GPU 서버 준비: [개발 가이드](docs/guides/development.md#독립-api와-테스트-브라우저)
- 모델 실행 후보 환경: Linux 또는 WSL2, GPU 모델·메모리·오디오 장치 실측 필요
- 기존 LocalForge 문서의 RTX 3090 24GB는 후보 기준이며 이 프로젝트의 지원 인증 결과 아님
- 마크다운 형식 검사: GitHub 문서 CI 제공, 로컬 도구가 있는 경우 `markdownlint-cli2 '**/*.md'`

## 개발 순서

1. 모델·장치·음성 지연 기준선 측정
2. 지속 입력과 스트리밍 인식, 생성·재생 취소 구현
3. 로컬 LLM·TTS 연결과 한국어 연속 대화 검증
4. 테스트 브라우저의 지속 텍스트·음성·끼어들기·장시간 대화 검증
5. 클라우드 배포와 API 안정화 후 Lemmy 연동·로봇 실측

단계별 범위와 인수 조건: [작업 목록](docs/tasks/README.md).

## 저장소 구조

- `src/`: 공통 포트·설정·registry·대화 제어·모델/RPC/Lemmy 어댑터
- `tests/`: 취소·재생·설정·RPC·입력 동시성·Lemmy schema 계약 테스트
- `scripts/`: 독립 실행 가능한 문서 링크 검사
- `docs/requirements/`: 기능·품질·Lemmy 연동 요구사항
- `docs/architecture/`: 현재 상태와 목표 구조를 구분한 통합 아키텍처
- `docs/decisions/`: 결정 및 제안 이력
- `docs/tasks/`: 구현 계획과 문서 구축 완료 이력
- `docs/guides/`: 개발·검증·변경·릴리스 절차

## 문서와 기여

- [문서 안내](docs/README.md)
- [에이전트 작업 규칙](AGENTS.md)
- [기여 안내](CONTRIBUTING.md)
- [커밋 규칙](COMMIT_RULES.md)
- [변경 이력](CHANGELOG.md)

## 라이선스

프로젝트 소스 라이선스 미정. 모델·음성 샘플·외부 코드의 라이선스는 개별 확인 후 사용 및 배포 여부 결정.

## AI 모델 교체

LLM·STT·TTS·KWS·VAD는 역할별 포트와 설정 주입으로 독립 교체하도록 설계.
동일 엔진의 호환 모델은 설정·manifest 변경, 엔진 교체는 어댑터 추가.
포트·설정 loader·registry·manifest hash 검사·자체 서버/RPC 어댑터 구현.
실제 서로 다른 모델/엔진 2개씩의 교체 인수는 미완료.
실제 모델의 direct/company_rpc 두 경로 smoke: `scripts/model-adapter-smoke.py`.
동일 가중치의 adapter 경로 검증과 서로 다른 모델·엔진 교체 검증은 구분.
세부 계약: [모델 교체 설계](docs/architecture/system.md#모델-교체-계약).

## 실행과 검증

```bash
uv sync --locked --extra audio --extra dev
.venv/bin/python -m real_pa.cli doctor
.venv/bin/python -m unittest discover -s tests -v
```

- 실제 모델·개발 gateway 실행: [개발 가이드](docs/guides/development.md#자체-gpu-개발-실행)
- 회사/클라우드 서버 실행 템플릿: [배포 안내](docs/guides/deployment.md)
- 현재 실제 모델 결과: [검증 기록](docs/guides/testing.md#2026-10-01-검증-기록)
- 브라우저 콘솔: API 서버의 `/`, 마이크 권한과 브라우저 반향 제거 지원 필요
- 합성 입력 검증은 실제 로봇 마이크·스피커·사용자 인증·도구 저장 검증을 대체하지 않음
