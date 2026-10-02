# 자동화 테스트

제어·설정·RPC·입력 동시성·Lemmy schema 변환 테스트 구현.
실행: `.venv/bin/python -m unittest discover -s tests -v`.
모델·장치 품질은 scripts의 실제 모델 smoke와 검증 가이드의 별도 인수 기준 적용.

계획된 단위·통합·실제 모델·실기기·Lemmy E2E 검증은 [검증 가이드](../docs/guides/testing.md) 기준.
실제 테스트 추가 시 실행 명령·관련 요구사항·Task 연결 필수.
