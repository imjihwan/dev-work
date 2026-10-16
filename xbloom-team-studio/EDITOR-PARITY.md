# 앱 레시피 설정 대조

대상: APKPure에서 확보한 xBloom Coffee 2.2.3, base APK SHA-256 `7cb23483fa9a0db29e4fb6670c1aa039cc8acaad0e29c6a49990cc88ed350f29`.

앞선 UI는 API 경로 위주로 만들면서 레시피 설정 일부를 누락했다. 실제 APK의 편집 화면과 설정 범위 코드를 추가 디컴파일해 다음과 같이 수정했다. 앱 전체 기능을 재현했다는 의미는 아니다.

| 설정 | 웹 반영 | APK 근거 |
|---|---|---|
| 커피 / 차 레시피 | 종류별 별도 설정·검증 | RecipeEditActivity, TeaRecipeEditFragment |
| xPod / xDripper / Other / Tea | 코드 1/2/3/4 구분 | CupType |
| 원두량 | 드리퍼별 입력 범위, g 단위 | CoffeeConstantUtil.getDose |
| 비율 | 1:5~1:25, 0.5 간격 | CoffeeConstantUtil.getCoffeeWater |
| Studio 그라인더 | ON/OFF, 1~80단계, RPM 60~120·10 간격 | getGrindSizeJ15, getRotatingSpeedJ15ForEdit |
| 그라인더 OFF | Studio 커피 요청에서 grinderSize 생략, 기존 편집 데이터 유지 | RecipeEditActivity.setEditBaseForm |
| 바이패스 | ON/OFF, 5~100mL, 온도/RT/BP | RecipeBypassViewHolder, getBypassVolume |
| 커피 푸어 수 | 최대 9단계, 추가/삭제/순서 변경/복제 | RecipeEditActivity.initListener, submit, DragTouchItemHelper |
| 푸어 물량 | 1~240mL, 추출 목표와 합계 비교 | getVolumeForEdit, submit |
| 푸어 온도 | 지정 온도와 RT/BP 구분, °C/°F 표시 | RecipePourViewHolder, TemperatureConstant |
| 물줄기 | 중앙=1, 나선형=2, 원형=3 | PatternType |
| 유량 | 3.0~3.5mL/s, 0.1 간격 | getFlowRateJ15 |
| 대기 | 커피 0~59초 | getPause |
| 진동 | 푸어 전·후 각각 ON/OFF | RecipePourViewHolder |
| 차 | 찻잎 1~5g, 1~3회 우림 | getTeaDose, TeaRecipeEditFragment.setPourNumber |
| 차의 회차별 설정 | 1~90mL, 5~360초, 온도/패턴 | TeaRecipePourItemView, getTeaSoakVolume/getTeaSteep |
| 차 사이펀 물량 | 기기 자동 설정임을 표시, 임의 조절 기능을 만들지 않음 | TeaRecipePourItemView: trigger 입력 비활성 |
| 레시피 색상 | 선택·저장 | RecipeAddForm.theColor |
| 보관 폴더 | API에서 가져와 선택 | SubsetListForSelectTransfer, RecipeEditActivity.saveData |
| Save as | 새 레시피로 복사, 원본 ID/푸어 ID 초기화 | setEditBaseForm(isSaveAs) |
| 연결된 원두 | 원본 메타데이터 유지·표시 | RecipeAddForm pods 필드 |

RT/BP의 저장값은 편집 종류별로 다르다. 커피 푸어는 RT=20, BP=98이고 차는 슬라이더 끝점 39/96을 저장하는 경로다. Studio 바이패스는 RT=20, BP 표시 끝점=96이다. 이를 일반 숫자 범위로 잘라 버리지 않도록 구분했다.

이전 앱/펌웨어의 레시피 값이 현재 UI 범위를 벗어나더라도, 그 값을 수정하지 않았다면 그대로 유지할 수 있다. 저장·전송을 위해 원본 값을 자동으로 최소/최댓값에 맞추지 않는다. 복사할 때 원본 레코드 ID는 제거하고 설정과 원두 메타데이터는 유지한다.

원본 읽기 데이터는 DB에 보존한다. API 전송은 실제 편집 Form에 해당하는 허용 필드만 구성하고, 푸어 내부의 원본 메타데이터는 유지한다. 전송 후 새 조회의 설정값을 비교해 불일치하면 충돌 상태로 남긴다.

검증: 프로토콜/설정 테스트 15개, 브라우저에서 커피·차 설정 변경 → 저장 → 재조회 검사. 실제 xBloom 계정·물리 기기를 대상으로 한 검증은 아직 수행하지 않았다.

범위 밖: 앱의 원두 마켓플레이스 탐색, NFC, 펌웨어 업데이트, 물리 기기 BLE 제어는 레시피 웹 편집기와 별도 기능이다. 기기 Auto Mode 실제 반영에는 Bluetooth 연결이 필요하다.
