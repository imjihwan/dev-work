[← 요약으로](../README.md) · [이전: 리포트 1. 수정 목록](1-fix.md) · [다음: 리포트 3. 설계 방향](3-direction.md)

# 리포트 2. 개선 목록

원본대로도 동작은 하지만 **고치면 나아지는 9가지**입니다. 7개를 모델에 반영했습니다.

<img src="../docs/img/badge_done.svg" alt="반영" height="20"> 모델에 넣음 &nbsp; <img src="../docs/img/badge_skip.svg" alt="미반영" height="20"> 구조상 그대로 둠 &nbsp; <img src="../docs/img/badge_alt.svg" alt="대체" height="20"> 다른 방식으로 해결

| # | 개선할 점 | 모델 반영 | 연결된 모델 |
|:---:|---|---|---|
| **1** | **발열**<br>통풍구 없음. 라파이 위 여유 3 mm | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 바닥 슬롯 5개, 앞벽 슬롯 7개, 라파이 위 8 mm | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`piClear` |
| **2** | **웹캠 고정**<br>14 mm 벽에 올려두기만 함 | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 받침 좌우에 벨크로 스트랩 걸이 2개 | 뚜껑 [A](../models/A_lid.stl) · [B](../models/B_lid.stl) · [C](../models/C_lid.stl)<br>`camL` `camD` |
| **3** | **포트 창 브리지**<br>윗변 58 mm, 54 mm | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 창마다 떼어내는 리브 2개로 브리지를 약 19 mm 구간 셋으로 나눔. 출력 후 니퍼로 제거 | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>[창 시험 조각](../models/test_window.stl) |
| **4** | **라파이 나사 구멍**<br>Ø2.5 (M2.5가 헛돎) | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 나사 구멍은 Ø2.2로 줄이고, 위치 핀 2개를 함께 씀 | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl) |
| **5** | **뚜껑 기둥 굵기**<br>Ø6.5 (살 약 1.95 mm) | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 벽에 붙은 7.2 x 7.4 보스로 변경 | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl) |
| **6** | **남는 케이블**<br>처리 방법 없음 | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 뒤벽 바깥에 케이블 타이 고리 | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl) |
| **7** | **웹캠 받침 바닥**<br>뚜껑 판 위에 받침 바닥이 이중 | <img src="../docs/img/badge_done.svg" alt="반영" height="20"> 뚜껑 판이 곧 받침 바닥 | 뚜껑 [A](../models/A_lid.stl) · [B](../models/B_lid.stl) · [C](../models/C_lid.stl) |
| **8** | **SD 카드**<br>선반과 빵판을 들어내야 교체 가능 | <img src="../docs/img/badge_skip.svg" alt="미반영" height="20"> 구조상 그대로. 조립 전에 이미지를 준비 | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`nutX` |
| **9** | **도면 표기**<br>위치 치수 누락, 숫자 빠진 치수 2곳 | <img src="../docs/img/badge_alt.svg" alt="대체" height="20"> 모델 하나가 기준이라 도면 간 불일치가 생기지 않음 | [pitect.js](../model/pitect.js) |

> [!NOTE]
> 프린터 베드는 220 mm 이상이 필요합니다. 케이스가 185.8 x 75.4 mm라 180 mm급 베드에는 들어가지 않습니다.
