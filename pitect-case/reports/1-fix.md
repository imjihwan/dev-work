[← 요약으로](../README.md) · [다음: 리포트 2. 개선 목록](2-improve.md)

# 리포트 1. 수정 목록

원본 도면에서 **안 고치면 조립, 기능, 출력 중 하나가 안 되는 10가지**입니다. 수치는 PDF의 벡터 좌표를 직접 추출해 확인했습니다.

<img src="../docs/img/badge_match.svg" alt="일치" height="20"> Claude와 Codex가 같은 결론 &nbsp; <img src="../docs/img/badge_hold.svg" alt="보류" height="20"> 실측 전까지 판단 보류

| # | 원본 도면의 문제 | 모델에 반영한 내용 | 교차 검토 | 연결된 모델 |
|:---:|---|---|:---:|---|
| **1** | **왼쪽 뚜껑 기둥 2개**<br>왼쪽 안벽에서 0.5~7 mm 구간. 라파이 USB/랜 포트 자리와 겹침 | 왼쪽 기둥을 없앰. A는 후크, B는 레일, C는 스냅으로 대체 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | [A 후크](../models/A_case.stl) · [B 레일](../models/B_case.stl) · [C 스냅](../models/C_case.stl) |
| **2** | **라파이 스탠드오프**<br>안벽에서 20.5 / 78.5 mm. 규격으로 계산한 값과 7~10 mm 어긋남 | 안벽에서 27.5 / 85.5 mm. USB 돌출 3 mm 가정이며 실측값을 넣어 다시 생성 가능. 뒤벽 창과 GPIO 틈도 같은 기준 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`usbOver` `piGap` |
| **3** | **빵판 위 틈**<br>1.2 mm. 점퍼선을 꽂을 수 없음 | 20.2 mm (듀폰 점퍼 기준) | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`jumper` |
| **4** | **웹캠 케이블 구멍**<br>14 x 10. 웹캠 본체 밑이고 아래는 빵판과 선반에 막힘 | 구멍 삭제. 케이블은 바깥으로 돌려 USB 창에 연결하고, 뒤벽에 케이블 타이 고리 추가 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 뚜껑 [A](../models/A_lid.stl) · [B](../models/B_lid.stl) · [C](../models/C_lid.stl) |
| **5** | **너트 포켓**<br>받침 바닥 쪽으로 열려 케이스가 조여지지 않음 | 케이스 안쪽 보스에 위에서 넣음. 너트 아래 살 1.6 mm. 보스는 SD 카드를 빼는 길을 피해 중심에서 28 mm 오른쪽 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`nutX` `nutFloor` |
| **6** | **LED 구멍**<br>Ø5.5인데 LED가 뚜껑 위로 24.3 mm 돌출. 테두리가 걸림 | A·C는 Ø6.4 + 아래쪽 유도 모따기. B는 LED를 뚜껑 아래에 두고 Ø5 창 | <img src="../docs/img/badge_hold.svg" alt="보류" height="20"> | 뚜껑 [A](../models/A_lid.stl) · [B](../models/B_lid.stl) · [C](../models/C_lid.stl)<br>`ledHole` `ledWindow` |
| **7** | **오른쪽 뚜껑 나사 2개**<br>웹캠 밑에 깔리고 M3 x 8이 2.2 mm만 물림 | 웹캠 받침을 왼쪽으로 10 mm 옮겨 나사와 잠금 핀 자리를 받침 밖에 둠 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 뚜껑 [A](../models/A_lid.stl) · [B](../models/B_lid.stl) · [C](../models/C_lid.stl)<br>[잠금 핀](../models/B_lock_pin.stl) |
| **8** | **받침 90 x 44 x 8**<br>베드에 놓으면 케이스 바닥이 양쪽 47.9 mm 허공 | 받침 삭제. 바닥이 평평해 그대로 베드에 놓음 | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl) |
| **9** | **선반 턱 3 x 3**<br>직각 오버행. 개구부 58.1 mm가 라파이 58.7 mm보다 좁음 | 아래 45° 모따기. 라파이 구간은 폭 2 mm(개구부 60.1), 그 밖은 3.5 mm | <img src="../docs/img/badge_match.svg" alt="일치" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>[선반](../models/shelf.stl) · `piClear` |
| **10** | **뒤벽 창 54 x 8**<br>아랫변이 PCB 윗면 높이라 플러그 몸통이 걸림 | 아랫변을 PCB 윗면보다 4 mm 낮춤. 오디오 잭부터 USB-C까지 57 x 12.5 | <img src="../docs/img/badge_hold.svg" alt="보류" height="20"> | 케이스 [A](../models/A_case.stl) · [B](../models/B_case.stl) · [C](../models/C_case.stl)<br>`usbOver` |

마지막 열의 링크는 그 항목이 반영된 STL이고, `글자`는 [파라메트릭 모델](parametric.md)의 변수입니다. GitHub에서 STL을 열면 3D로 돌려 볼 수 있습니다.

## 교차 검토 메모

- 1번 왼쪽 뚜껑 기둥 2개: 독립 검토에서도 치명으로 지적
- 2번 라파이 스탠드오프: 원본대로면 PCB가 벽을 침범
- 4번 웹캠 케이블 구멍: 구멍 아래 연속 틈은 0.55 mm뿐
- 6번 LED 구멍: LED 형번이 도면에 없음
- 8번 받침 90 x 44 x 8: 독립 검토에서도 치명으로 지적
- 10번 뒤벽 창 54 x 8: 플러그 실측 필요

교차 검토에서 8개는 같은 결론이었고, 2개(6번, 10번)는 실측 전까지 판단 보류이며, 반박된 항목은 없습니다.
