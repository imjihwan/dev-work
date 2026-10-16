# COMMAX Cloud for Home Assistant

COMMAX IP Home IoT 계정으로 조명을 제어하는 Home Assistant 사용자 통합입니다. 토큰 자동 갱신과 갱신 실패 시 저장된 계정으로 자동 로그인을 지원합니다.

## 설치

1. 이 폴더의 `custom_components/commax_cloud`를 Home Assistant의 `/config/custom_components/commax_cloud`로 복사합니다.
2. Home Assistant를 재시작합니다.
3. **설정 → 기기 및 서비스 → 통합 추가 → COMMAX Cloud**에서 본인 계정으로 로그인합니다.

자세한 설치 방법은 [INSTALL_KO.txt](INSTALL_KO.txt), 검증 결과는 [VERIFICATION.txt](VERIFICATION.txt)를 참고하세요. 계정 정보와 토큰은 소스에 포함되어 있지 않습니다.

## 구성

- `custom_components/commax_cloud/`: 통합 소스와 한국어·영어 번역
- `tests/`: API 인증 및 Home Assistant 통합 테스트
- `pyproject.toml`, `pytest.ini`: 개발 도구 설정
