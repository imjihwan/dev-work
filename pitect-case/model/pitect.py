"""PI-TECT 삼각대용 통합 케이스: 파라메트릭 모델 (파이썬 판, 단위 mm)

model/pitect.js와 같은 형상을 만든다. 실측값을 바꾸면 세 버전의 STL 14개가 다시 계산된다.
  좌표: x = 길이(중심 0, -x 쪽이 라파이 USB/랜), y = 폭(중심 0, +y = 뒤, 전원/HDMI 쪽), z = 높이(케이스 바깥 바닥 0)
  버전: A = 나사 4개(후크 + M3 2개) / B = 슬라이드 뚜껑 + 잠금 핀 / C = 스냅락 뚜껑

필요한 패키지: manifold3d, numpy
  pip install manifold3d==3.5.5 numpy
명령줄에서 쓰기:
  python3 pitect.py                    # 기본값으로 검사만 실행
  python3 pitect.py --out models       # STL을 models 폴더에 저장
  python3 pitect.py usbOver=2.5 --out models
"""
import math
import os
import struct
import sys
from types import SimpleNamespace

import numpy as np
from manifold3d import CrossSection, Manifold, OpType

DEFAULTS = dict(
    # ---- 실측값 ----
    camL=105.6, camD=63.3, camH=55.3,   # 웹캠 (클립 접은 상태)
    bbL=165, bbW=56.4, bbH=10,          # 풀사이즈 빵판
    piEnvW=58.7, piTop=19,              # 라파이 폭(포트 돌출 포함), PCB 밑면부터 최고 높이
    usbOver=3.0,                        # USB 포트 끝면 → PCB 끝 거리. 실측 필요 (포트 끝면~가까운 구멍 중심 거리 - 23.5)
    nutAF=11.1, nutT=5.6,               # 1/4"-20 육각 너트 대변, 두께
    # ---- 설계값 ----
    wall=2.4, floor=2.4, standoff=5,
    piGap=1.0,                          # USB 포트 끝면과 왼쪽 안벽 사이
    piClear=8,                          # 라파이 최고점과 선반 밑면 사이
    shelfT=2.4,
    jumper=20.2,                        # 빵판 윗면과 뚜껑 밑면 사이 (듀폰 점퍼 기준 20)
    camFit=0.8,                         # 웹캠 받침 여유 (전체)
    nutFloor=1.6,                       # 너트 아래 남기는 살
    nutX=28,                            # 너트 보스 x 위치. SD 카드를 빼는 길(약 16 mm)을 비워 둠
    ledX=-55, ledHole=6.4, ledWindow=5.0,
    fit=0.4,                            # 끼움 여유 (슬라이드 레일, 스냅 홈)
)
NAMES = {'A': '나사형', 'B': '슬라이드형', 'C': '스냅락형'}


def dims(P):
    """실측값과 설계값에서 나머지 치수를 모두 계산한다."""
    D = SimpleNamespace()
    D.inL, D.inW = P.bbL + 16, P.camD + P.camFit
    D.ix, D.iy = D.inL / 2, D.inW / 2
    D.hx, D.hy = D.ix + P.wall, D.iy + P.wall
    D.zPcbBot = P.floor + P.standoff
    D.zPcbTop = D.zPcbBot + 1.6
    D.zPiTop = D.zPcbBot + P.piTop
    D.zShelf = D.zPiTop + P.piClear
    D.zShelfTop = D.zShelf + P.shelfT
    D.zBbTop = D.zShelfTop + P.bbH
    D.zRim = math.floor((D.zBbTop + P.jumper) * 10 + 0.5) / 10
    D.xFace = -D.ix + P.piGap
    D.pcbX0 = D.xFace + P.usbOver
    D.pcbX1 = D.pcbX0 + 85
    D.pcbY0 = -P.piEnvW / 2
    D.pcbY1 = D.pcbY0 + 56
    D.pcbYc = D.pcbY0 + 28
    h1, h2 = D.pcbX1 - 3.5 - 58, D.pcbX1 - 3.5
    D.holes = [(h1, D.pcbYc - 24.5), (h1, D.pcbYc + 24.5), (h2, D.pcbYc - 24.5), (h2, D.pcbYc + 24.5)]
    gpio_c = D.pcbX1 - 32.5
    D.gpio0, D.gpio1 = gpio_c - 28, gpio_c + 28
    D.bwX0, D.bwX1 = D.pcbX1 - 54.0 - 6.5, D.pcbX1 - 11.2 + 7.5        # 뒤벽 창: 오디오 잭 ~ USB-C
    D.cx1 = D.hx - 10
    D.cx0 = D.cx1 - (P.camL + P.camFit + 2 * P.wall)                    # 웹캠 받침 바깥 x 범위
    D.zWin0, D.zWin1 = D.zPcbBot - 0.5, D.zPiTop + 1.6                  # USB/랜 창 (브리지 처짐 여유 1.6)
    D.bx0 = P.bbL / 2 + 0.8
    D.bossX, D.bossY = (D.bx0 + D.ix) / 2, 18                           # 오른쪽 보스
    D.nutTop = P.nutFloor + P.nutT + 0.8
    D.outL, D.outW = 2 * D.hx, 2 * D.hy
    D.xw = 8
    D.snapXs = [(-60, 8), (86.5, 6)]
    return D


# ---------------- 기본 도형 ----------------
def _ccw(pts):
    a = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))
    return pts[::-1] if a < 0 else pts


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def cyl(x, y, z0, z1, r, seg=48):
    return Manifold.cylinder(z1 - z0, r, r, seg).translate([x, y, z0])


def cone(x, y, z0, z1, r0, r1, seg=48):
    return Manifold.cylinder(z1 - z0, r0, r1, seg).translate([x, y, z0])


def hexp(x, y, z0, z1, af):
    r = af / 2 / math.cos(math.pi / 6)
    return Manifold.cylinder(z1 - z0, r, r, 6).translate([x, y, z0])


def _extrude(pts, h):
    return CrossSection([[tuple(p) for p in _ccw(list(pts))]]).extrude(h)


def prism_x(pts, x0, x1):
    """단면 [y, z]를 x 방향으로 민다."""
    return _extrude(pts, x1 - x0).rotate([90, 0, 90]).translate([x0, 0, 0])


def prism_y(pts, y0, y1):
    """단면 [x, z]를 y 방향으로 민다."""
    return _extrude(pts, y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0])


def prism_z(pts, z0, z1):
    return _extrude(pts, z1 - z0).translate([0, 0, z0])


def rib(cx, cy, r0, r1, w, z0, z1, deg):
    """중심 (cx, cy)에서 반지름 방향으로 r0~r1에 놓인 가는 리브."""
    return Manifold.cube([r1 - r0, w, z1 - z0]).translate([r0, -w / 2, z0]).rotate([0, 0, deg]).translate([cx, cy, 0])


def circle(cx, cz, r, n=20):
    return [(cx + r * math.cos(2 * math.pi * i / n), cz + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def union(parts):
    return Manifold.batch_boolean(list(parts), OpType.Add)


def _span(a, b):
    return (min(a, b), max(a, b))


# ---------------- 부품 ----------------
def build_case(P, D, ver):
    ix, iy, hx, hy, zRim, zShelf = D.ix, D.iy, D.hx, D.hy, D.zRim, D.zShelf
    add, cut = [], []
    shell = box(-hx, hx, -hy, hy, 0, zRim) - box(-ix, ix, -iy, iy, P.floor, zRim + 1)

    # 라파이 스탠드오프 4개. 대각선 2개(1, 2번)는 위치 핀, 나머지 2개는 M2.5 셀프탭용 Ø2.2 구멍
    for i, (x, y) in enumerate(D.holes):
        add.append(cyl(x, y, P.floor - 0.3, D.zPcbBot, 3.0))
        if i in (1, 2):
            add.append(cyl(x, y, D.zPcbBot - 0.1, D.zPcbBot + 2.2, 1.2, 32))
            add.append(cone(x, y, D.zPcbBot + 2.2, D.zPcbBot + 2.8, 1.2, 0.8, 32))
        else:
            cut.append(cyl(x, y, 1.4, D.zPcbBot + 1, 1.1, 32))

    # 선반 턱: 아래 45° 모따기. 라파이 구간은 폭 2, 그 밖은 3.5. 앞쪽은 GPIO 선 통과 구간을 비움
    def ledge(s, w, x0, x1):
        return prism_x([(s * (iy + 0.3), zShelf), (s * (iy - w), zShelf), (s * (iy - w), zShelf - 1), (s * (iy + 0.3), zShelf - 1 - w - 0.3)], x0, x1)
    add += [ledge(1, 2.0, -ix - 0.3, D.xw), ledge(1, 3.5, D.xw, ix + 0.3)]
    add += [ledge(-1, 2.0, -ix - 0.3, D.gpio0), ledge(-1, 2.0, D.gpio1, D.xw), ledge(-1, 3.5, D.xw, ix + 0.3)]

    # 선반·빵판 왼쪽 멈춤 리브 (USB/랜 창 위, 아래 45°)
    rz = D.zWin1 + 0.5
    for s in (-1, 1):
        add.append(prism_y([(-ix - 0.3, rz - 0.3), (-ix + 7.2, rz + 7.2), (-ix + 7.2, D.zBbTop - 2.8), (-ix - 0.3, D.zBbTop - 2.8)], s * D.bossY - 1.5, s * D.bossY + 1.5))

    # 오른쪽 보스 2개 (선반 멈춤 겸용). A는 M3 셀프탭 Ø2.6, B는 잠금 핀 Ø4.4
    for s in (-1, 1):
        add.append(box(D.bx0, ix + 0.3, s * D.bossY - 3.7, s * D.bossY + 3.7, P.floor - 0.3, zRim))
        if ver == 'A':
            cut.append(cyl(D.bossX, s * D.bossY, zRim - 12, zRim + 1, 1.3, 32))
        if ver == 'B':
            cut.append(cyl(D.bossX, s * D.bossY, zRim - 12, zRim + 1, 2.2, 32))

    # 삼각대 너트 보스: 케이스 안쪽에서 너트를 넣고, 너트 아래에 살을 남김
    add.append(cyl(P.nutX, 0, P.floor - 0.3, D.nutTop, 10, 64))
    cut.append(hexp(P.nutX, 0, P.nutFloor, D.nutTop + 1, P.nutAF + 0.4))
    cut.append(cyl(P.nutX, 0, -1, P.nutFloor + 0.5, 3.4))

    # 포트 창
    cut.append(box(-hx - 1, -ix + 0.01, D.pcbY0 - 1, D.pcbY1 + 1, D.zWin0, D.zWin1))        # USB/랜 (왼쪽 벽)
    cut.append(box(D.bwX0, D.bwX1, iy - 0.01, hy + 1, D.zPcbTop - 4, D.zPcbTop + 8.5))       # 전원/HDMI/오디오 (뒤벽)

    # 통풍: 바닥 슬롯 5개 + 앞벽 슬롯 7개
    for k in range(5):
        x = D.holes[0][0] + 11 + 9 * k
        cut.append(box(x - 1.25, x + 1.25, D.pcbYc - 15, D.pcbYc + 15, -1, P.floor + 1))
    for k in range(7):
        x = D.holes[0][0] + 7 + 7 * k
        cut.append(box(x - 1.25, x + 1.25, -hy - 1, -iy + 0.01, D.zPcbTop + 1, D.zPcbTop + 13))

    # 케이블 타이 고리 (뒤벽 바깥): 아래 45° 받침 + 세로 막대 + 위 브리지
    lx0, lx1 = 47.5, 52.5
    add.append(box(lx0, lx1, hy + 3.55, hy + 6.55, 30, 46))
    add.append(prism_x([(hy - 0.3, 23.15), (hy + 6.55, 30), (hy + 3.55, 30), (hy - 0.3, 26.15)], lx0, lx1))
    add.append(box(lx0, lx1, hy - 0.3, hy + 6.55, 46, 48.5))

    if ver == 'A':
        # 왼쪽 벽을 올려 뚜껑 끝을 누르는 45° 후크 + 모서리 귀
        add.append(box(-hx, -ix, -hy, hy, zRim - 0.3, zRim + 3.9))
        add.append(prism_y([(-ix - 0.3, zRim + 0.9), (-ix + 2.7, zRim + 3.9), (-ix - 0.3, zRim + 3.9)], -28, 28))
        for s in (-1, 1):
            y0, y1 = _span(s * hy, s * (hy - 1.2))
            add.append(box(-ix - 0.3, -ix + 6, y0, y1, zRim - 0.3, zRim + 3.4))
    if ver == 'B':
        # 긴 벽 위 45° 레일 + 왼쪽 멈춤 블록
        for s in (-1, 1):
            add.append(prism_x([(s * hy, zRim - 0.3), (s * (hy - 1.2), zRim - 0.3), (s * (hy - 1.2), zRim), (s * (hy - 2.7), zRim + 1.5), (s * hy, zRim + 1.5)], -hx, hx))
        add.append(box(-hx, -ix, -10, 10, zRim - 0.3, zRim + 4.5 + P.fit))
    if ver == 'C':
        # 스냅 후크 4개: 벽에 세로 홈 2개를 내어 만든 외팔보 + 45° 걸림턱
        for hx_, hw in D.snapXs:
            for s in (-1, 1):
                y0, y1 = _span(s * (iy - 0.5), s * (hy + 0.5))
                zs = zRim - 16 + 0.75
                for xs in (hx_ - hw / 2 - 0.75, hx_ + hw / 2 + 0.75):
                    cut.append(box(xs - 0.75, xs + 0.75, y0, y1, zs, zRim + 1))
                    cut.append(prism_y(circle(xs, zs, 0.75), y0, y1))            # 응력 집중을 줄이는 둥근 뿌리
                b0, b1 = _span(s * iy, s * hy)
                add.append(box(hx_ - hw / 2, hx_ + hw / 2, b0, b1, zRim - 0.3, zRim + 6.2))
                add.append(prism_x([(s * (iy + 0.3), zRim + 2.9), (s * (iy - 1.5), zRim + 4.7), (s * iy, zRim + 6.2), (s * (iy + 0.3), zRim + 6.2)], hx_ - hw / 2, hx_ + hw / 2))

    # 넓은 창 2곳의 브리지를 3등분하는 떼어내는 리브 (두께 0.8, 출력 후 니퍼로 제거)
    tear = []
    wy0, wy1 = D.pcbY0 - 1, D.pcbY1 + 1
    for f in (1 / 3, 2 / 3):
        y = wy0 + (wy1 - wy0) * f
        x = D.bwX0 + (D.bwX1 - D.bwX0) * f
        tear.append(box(-hx, -ix, y - 0.4, y + 0.4, D.zWin0 - 0.2, D.zWin1 + 0.2))
        tear.append(box(x - 0.4, x + 0.4, iy, hy, D.zPcbTop - 4.2, D.zPcbTop + 8.7))
    # 눌림 리브: 너트와 잠금 핀이 헐거워 빠지지 않도록 살짝 조이는 가는 세로 리브
    pf = (P.nutAF + 0.4) / 2
    for k in range(6):
        tear.append(rib(P.nutX, 0, pf - 0.3, pf + 0.3, 0.6, P.nutFloor, D.nutTop, 30 + 60 * k))
    if ver == 'B':
        for s in (-1, 1):
            for a in (90, 210, 330):
                tear.append(rib(D.bossX, s * D.bossY, 1.85, 2.5, 0.6, zRim - 12, zRim - 1, a))
    return union([union([shell] + add) - union(cut)] + tear)


def _lid_extras(P, D, top):
    iy, hy, cx0, cx1 = D.iy, D.hy, D.cx0, D.cx1
    add, cut = [], []
    # 웹캠 받침: 뚜껑 판이 바닥. 앞쪽은 턱 4 mm만 남기고 개방
    add.append(box(cx0, cx1, -hy, hy, top - 0.02, top + 14))
    cut.append(box(cx0 + P.wall, cx1 - P.wall, -iy, iy, top, top + 15))
    cut.append(box(cx0 + P.wall + 8, cx1 - P.wall - 8, -hy - 1, -iy + 0.01, top + 4, top + 15))
    # 벨크로 스트랩 걸이 2개 (받침 좌우)
    for x0 in (cx0 - 9, cx1 + 1.5):
        add += [box(x0, x0 + 6, -11.5, -8.5, top - 0.3, top + 3.5), box(x0, x0 + 6, 8.5, 11.5, top - 0.3, top + 3.5)]
        add.append(box(x0, x0 + 6, -11.5, 11.5, top + 3.5, top + 6.1))
    return add, cut


def build_lid(P, D, ver):
    ix, iy, hx, hy, zRim = D.ix, D.iy, D.hx, D.hy, D.zRim
    cut = []
    if ver == 'A':
        top = zRim + 3.4
        xL = -ix + 0.3
        plate = box(xL, hx, -hy, hy, zRim, top)
        for s in (-1, 1):
            y0, y1 = _span(s * (hy - 1.45), s * (hy + 1))
            cut.append(box(-ix - 1, -ix + 6.3, y0, y1, zRim - 1, top + 1))
        cut.append(prism_y([(xL - 0.5, zRim + 0.5), (xL + 2.41, top + 0.01), (xL - 0.5, top + 0.01)], -hy - 1, hy + 1))   # 후크에 물리는 45° 끝
        for s in (-1, 1):
            cut.append(cyl(D.bossX, s * D.bossY, zRim - 1, top + 1, 1.7, 32))                                             # M3 Ø3.4
        cut += [cyl(P.ledX, 0, zRim - 1, top + 1, P.ledHole / 2), cone(P.ledX, 0, zRim - 0.01, zRim + 1, P.ledHole / 2 + 1, P.ledHole / 2)]
    elif ver == 'B':
        b, n = hy - 1.2 - P.fit, hy - 2.7 - P.fit
        top = zRim + 1.8 + (hy - n)
        plate = prism_x([(-b, zRim), (b, zRim), (n, zRim + 1.5), (n, zRim + 1.8), (hy, top), (-hy, top), (-n, zRim + 1.8), (-n, zRim + 1.5)], -hx, hx)
        cut.append(box(-hx - 1, -ix + 0.3, -10.4, 10.4, zRim - 1, top + 1))                  # 멈춤 블록이 들어오는 홈 (수직 관통)
        for s in (-1, 1):
            cut.append(prism_z([(-hx - 1, s * (b - 3)), (-hx + 3, s * (b + 1)), (-hx - 1, s * (b + 1))], zRim - 1, zRim + 1.5))   # 레일 진입 모따기 2 mm
        for s in (-1, 1):
            cut.append(cyl(D.bossX, s * D.bossY, zRim - 1, top + 1, 2.2, 32))                # 잠금 핀 Ø4.4
        cut.append(cyl(P.ledX, 0, zRim - 1, top + 1, P.ledWindow / 2))                       # LED 빛 창 (LED는 뚜껑 아래)
    else:
        top = zRim + 3.4
        plate = box(-hx, hx, -hy, hy, zRim, top)
        for hx_, hw in D.snapXs:
            for s in (-1, 1):
                y0, y1 = _span(s * (iy - P.fit), s * (hy + 1))
                cut.append(box(hx_ - hw / 2 - 0.4, hx_ + hw / 2 + 0.4, y0, y1, zRim - 1, top + 1))
        cut += [cyl(P.ledX, 0, zRim - 1, top + 1, P.ledHole / 2), cone(P.ledX, 0, zRim - 0.01, zRim + 1, P.ledHole / 2 + 1, P.ledHole / 2)]
    add, ecut = _lid_extras(P, D, top)
    return union([plate] + add) - union(cut + ecut), top


def build_shelf(P, D):
    hw, hl, r = (D.inW - 0.8) / 2, P.bbL / 2 + 0.5, P.bbW / 2 + 0.4
    plate = box(-hl, hl, -hw, hw, 0, P.shelfT)
    rails = [box(-hl + 3, hl - 3, r, r + 1.8, P.shelfT - 0.3, P.shelfT + 6), box(D.gpio1 + 4, hl - 3, -r - 1.8, -r, P.shelfT - 0.3, P.shelfT + 6)]
    return union([plate] + rails) - box(D.gpio0, D.gpio1, -hw - 1, -hw + 4.5, -1, P.shelfT + 1)


def build_pin():
    return union([cyl(0, 0, 0, 1.6, 3.75), cyl(0, 0, 1.5, 2.4, 2.5, 32), cyl(0, 0, 2.3, 14.3, 2.0, 32), cone(0, 0, 14.3, 14.9, 2.0, 1.5, 32)])


def keepouts(P, D):
    """케이스가 침범하면 안 되는 부품 자리."""
    pcb = box(D.pcbX0, D.pcbX1, D.pcbY0, D.pcbY1, D.zPcbBot, D.zPcbTop) - union([cyl(x, y, D.zPcbBot - 1, D.zPcbTop + 1, 1.35, 32) for x, y in D.holes])
    return {
        'PCB': pcb,
        'USB/랜 포트': box(D.xFace, D.xFace + 21, D.pcbY0 + 1, D.pcbY1 - 1, D.zPcbTop, D.zPiTop),
        'GPIO 헤더': box(D.pcbX1 - 57.9, D.pcbX1 - 7.1, D.pcbY0 + 1, D.pcbY0 + 6, D.zPcbTop, D.zPcbTop + 8.5),
        '전원/HDMI 돌출': box(D.bwX0 + 1, D.bwX1 - 1, D.pcbY1, P.piEnvW / 2, D.zPcbTop, D.zPcbTop + 4),
        'SD 카드': box(D.pcbX1, D.pcbX1 + 3, D.pcbYc - 6, D.pcbYc + 6, D.zPcbBot - 1.4, D.zPcbBot),
        '너트': hexp(P.nutX, 0, P.nutFloor, P.nutFloor + P.nutT, P.nutAF),
    }


# ---------------- 메시 정리와 STL ----------------
_E = ((0, 1, 2), (1, 2, 0), (2, 0, 1))


def _area2(pos, t):
    a, b, c = pos[t[0]], pos[t[1]], pos[t[2]]
    u, v = b - a, c - a
    return math.sqrt((u[1] * v[2] - u[2] * v[1]) ** 2 + (u[2] * v[0] - u[0] * v[2]) ** 2 + (u[0] * v[1] - u[1] * v[0]) ** 2)


def clean_mesh(pos, tris):
    """Manifold 출력에는 한 변 위에 꼭짓점이 놓인 자리마다 면적 0 삼각형이 남는다.
    그 삼각형을 지우고 맞은편 이웃 삼각형을 그 꼭짓점에서 둘로 나누면, 닫힌 상태를 유지한 채 깨끗한 메시가 된다."""
    pos = np.asarray(pos, dtype=np.float64)
    tris = [tuple(int(v) for v in t) for t in tris]
    d2 = lambda a, b: float(((pos[a] - pos[b]) ** 2).sum())
    raw = sum(1 for t in tris if _area2(pos, t) < 1e-6)
    for _ in range(500):
        k = next((i for i, t in enumerate(tris) if _area2(pos, t) < 1e-6), None)
        if k is None:
            break
        t = tris[k]
        a, b, m = max(((t[i], t[j], t[o]) for i, j, o in _E), key=lambda e: d2(e[0], e[1]))
        if d2(m, a) < 1e-12 or d2(m, b) < 1e-12:                      # 두 꼭짓점이 같은 자리: 하나로 합침
            keep = a if d2(m, a) < 1e-12 else b
            tris = [tuple(keep if v == m else v for v in u) for u in tris]
            tris = [u for u in tris if len(set(u)) == 3]
            continue
        n = next((i for i, u in enumerate(tris) if i != k and any(u[p] == b and u[q] == a for p, q, _ in _E)), None)
        if n is None:
            break
        d = next(v for v in tris[n] if v not in (a, b))
        tris = [u for i, u in enumerate(tris) if i not in (k, n)] + [(b, m, d), (m, a, d)]
    edges = {}
    for t in tris:
        for i, j, _ in _E:
            edges[(t[i], t[j])] = edges.get((t[i], t[j]), 0) + 1
    open_edges = sum(1 for (a, b), c in edges.items() if c != 1 or edges.get((b, a)) != 1)
    degenerate = sum(1 for t in tris if _area2(pos, t) < 1e-6)
    return np.array(tris, dtype=np.uint32), raw, degenerate, open_edges


def mesh_of(m):
    g = m.to_mesh()
    pos = np.asarray(g.vert_properties, dtype=np.float32)[:, :3]
    idx, raw, degenerate, open_edges = clean_mesh(pos, np.asarray(g.tri_verts))
    return dict(pos=pos, idx=idx, raw_degenerate=raw, degenerate=degenerate, open_edges=open_edges)


def to_stl(mesh, name=''):
    """바이너리 STL 바이트를 만든다."""
    pos, idx = mesh['pos'].astype(np.float32), mesh['idx']
    v = pos[idx]                                           # (n, 3, 3)
    nrm = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    nrm = (nrm / np.where(ln == 0, 1, ln)).astype(np.float32)
    rec = np.zeros(len(idx), dtype=np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')]))
    rec['n'], rec['v'] = nrm, v
    head = ('PI-TECT ' + name).encode('ascii', 'ignore')[:79].ljust(80, b'\0')
    return head + struct.pack('<I', len(idx)) + rec.tobytes()


# ---------------- 전체 빌드와 검사 ----------------
def build(user=None):
    """부품, 검사 결과, 배치 정보를 돌려준다. user = 바꿀 값만 담은 dict."""
    P = SimpleNamespace(**{**DEFAULTS, **(user or {})})
    D = dims(P)
    r1 = lambda v: math.floor(v * 10 + 0.5) / 10
    parts, checks = [], []

    def push(pid, ver, label, solid, asm, color, note):
        bb = solid.bounding_box()
        dz = bb[2]
        pr = solid.translate([0, 0, -dz])
        mesh = mesh_of(pr)
        ok = (not pr.is_empty()) and 'NoError' in str(pr.status()) and mesh['degenerate'] == 0 and mesh['open_edges'] == 0
        parts.append(dict(id=pid, ver=ver, label=label, note=note, color=color, size=[r1(bb[3] - bb[0]), r1(bb[4] - bb[1]), r1(bb[5] - bb[2])],
                          volume=r1(pr.volume() / 1000), tris=len(mesh['idx']), genus=pr.genus(), ok=ok,
                          asm=[asm[0], asm[1], asm[2] + dz] if asm else None, mesh=mesh, solid=solid))

    def chk(name, value, ok, detail=''):
        checks.append(dict(name=name, value=round(value, 2) if isinstance(value, float) else value, ok=bool(ok), detail=detail))

    ivol = lambda a, b: (a ^ b).volume()
    shelf = build_shelf(P, D)
    shelf_asm = shelf.translate([0, 0, D.zShelf])
    ko = keepouts(P, D)
    bread = box(-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zShelfTop, D.zBbTop)
    jz = min(20, P.jumper)                               # 듀폰 점퍼는 20 mm가 필요. jumper를 줄이면 그 높이까지만 확인
    jumper_zone = box(-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zBbTop, D.zBbTop + jz)
    ghosts = {}

    for ver in 'ABC':
        cs = build_case(P, D, ver)
        lid, top = build_lid(P, D, ver)
        cam_box = [D.cx0 + P.wall + P.camFit / 2, D.cx1 - P.wall - P.camFit / 2, -P.camD / 2, P.camD / 2, top, top + P.camH]
        cam = box(*cam_box)
        push(f'{ver}_case', ver, f'케이스 ({NAMES[ver]})', cs, [0, 0, 0], 'case', '바닥을 베드에')
        push(f'{ver}_lid', ver, f'뚜껑 ({NAMES[ver]})', lid, [0, 0, 0], 'lid', '판을 베드에, 받침이 위')
        ghosts[ver] = dict(cam=cam_box, total=r1(top + P.camH), lidTop=r1(top))

        for k, s in ko.items():
            v = ivol(cs, s)
            if k == '너트':
                chk(f'{ver}: 케이스 눌림 리브 ↔ 너트', v, 0.2 < v < 4, '의도한 조임 간섭 mm³ (0.2~4)')
            else:
                chk(f'{ver}: 케이스 ↔ {k}', v, v < 0.01, '겹침 부피 mm³')
        sd = box(D.pcbX1, D.pcbX1 + 16, D.pcbYc - 6.5, D.pcbYc + 6.5, D.zPcbBot - 1.6, D.zPcbBot)
        chk(f'{ver}: SD 카드를 빼는 경로', ivol(cs, sd), ivol(cs, sd) < 0.01, '겹침 부피 mm³')
        chk(f'{ver}: 케이스 ↔ 선반', ivol(cs, shelf_asm), ivol(cs, shelf_asm) < 0.01, '겹침 부피 mm³')
        chk(f'{ver}: 케이스 ↔ 빵판', ivol(cs, bread), ivol(cs, bread) < 0.01, '겹침 부피 mm³')
        chk(f'{ver}: 케이스 ↔ 뚜껑', ivol(cs, lid), ivol(cs, lid) < 0.01, '겹침 부피 mm³')
        chk(f'{ver}: 뚜껑 ↔ 웹캠', ivol(lid, cam), ivol(lid, cam) < 0.01, '겹침 부피 mm³')
        chk(f'{ver}: 뚜껑 ↔ 빵판 위 {jz:g} mm 공간', ivol(lid, jumper_zone), ivol(lid, jumper_zone) < 0.01, '겹침 부피 mm³')
        lift = ivol(cs, lid.translate([0, 0, 1.2]))
        chk(f'{ver}: 뚜껑을 1.2 mm 들면 걸리는가', lift, lift > 0.05, '걸림 부피 mm³ (0보다 커야 고정됨)')
        if ver == 'B':
            worst = max(ivol(cs, lid.translate([d, 0, 0])) for d in range(5, 191, 5))
            chk('B: 뚜껑을 오른쪽으로 밀어 빼는 경로', worst, worst < 0.01, '경로 중 최대 겹침 mm³')
            pin = build_pin()
            push('B_lock_pin', 'B', '잠금 핀 (2개 출력)', pin, None, 'pin', '머리를 베드에')
            pin_asm = pin.rotate([180, 0, 0]).translate([D.bossX, D.bossY, top + 2.4])
            chk('B: 잠금 핀 ↔ 뚜껑', ivol(pin_asm, lid), ivol(pin_asm, lid) < 0.01, '겹침 부피 mm³')
            v = ivol(pin_asm, cs)
            chk('B: 잠금 핀 ↔ 케이스 눌림 리브', v, 0.2 < v < 4, '의도한 조임 간섭 mm³ (0.2~4)')
        # 시험 조각
        if ver == 'A':
            push('test_window', '공통', '시험 조각: USB/랜 창 + 떼어내는 리브', cs ^ box(-D.hx - 1, -D.ix + 8, -D.hy - 1, D.hy + 1, -1, D.zWin1 + 3), None, 'test', '브리지 처짐과 리브 제거 확인')
            push('test_A_floor', 'A', '시험 조각: 라파이 바닥 + 너트 보스', cs ^ box(-D.hx - 1, P.nutX + 13, -D.hy - 10, D.hy + 10, -1, 12), None, 'test', '스탠드오프·핀·창·너트 맞춤 확인')
        if ver == 'B':
            zc = box(20, 50, -D.hy - 1, D.hy + 1, D.zRim - 8, D.zRim + 6)
            push('test_B_rail_case', 'B', '시험 조각: 레일 (케이스 쪽)', union([cs ^ zc, box(20, 50, -D.hy, D.hy, D.zRim - 8, D.zRim - 6.4)]), None, 'test', '슬라이드 공차 확인')
            push('test_B_rail_lid', 'B', '시험 조각: 레일 (뚜껑 쪽)', lid ^ box(-70, -40, -D.hy - 1, D.hy + 1, D.zRim - 1, top), None, 'test', '슬라이드 공차 확인')
        if ver == 'C':
            zc = box(-72, -48, -D.hy - 1, D.hy + 1, D.zRim - 20, D.zRim + 8)
            push('test_C_snap_case', 'C', '시험 조각: 스냅 후크 (케이스 쪽)', union([cs ^ zc, box(-72, -48, -D.hy, D.hy, D.zRim - 20, D.zRim - 18.4)]), None, 'test', '스냅 걸림 확인')
            push('test_C_snap_lid', 'C', '시험 조각: 스냅 후크 (뚜껑 쪽)', lid ^ box(-72, -48, -D.hy - 1, D.hy + 1, D.zRim - 1, top), None, 'test', '스냅 걸림 확인')

    push('shelf', '공통', '선반 (공통)', shelf, [0, 0, D.zShelf], 'shelf', '판을 베드에, 레일이 위')
    for k, s in ko.items():
        if k != '너트':
            chk(f'선반 ↔ {k}', ivol(shelf_asm, s), ivol(shelf_asm, s) < 0.01, '겹침 부피 mm³')
    for p in parts:
        m = p['mesh']
        chk(f"메시 상태: {p['id']}", f"{p['tris']} 삼각형", p['ok'], f"닫힌 메시, 면적 0 삼각형 {m['raw_degenerate']}개 정리 후 {m['degenerate']}개, 열린 모서리 {m['open_edges']}개")
    chk('전체 높이 (A·C)', ghosts['A']['total'], True, 'mm, 삼각대 플레이트 면 기준')
    chk('전체 높이 (B)', ghosts['B']['total'], True, 'mm, 삼각대 플레이트 면 기준')
    chk('스탠드오프 x (왼쪽 안벽 기준)', f"{r1(D.holes[0][0] + D.ix)} / {r1(D.holes[2][0] + D.ix)}", True, 'mm')

    info = dict(P=vars(P), zRim=D.zRim, zShelf=D.zShelf, outL=r1(D.outL), outW=r1(D.outW),
                pi=[D.xFace, D.pcbX1, D.pcbY0, P.piEnvW / 2, D.zPcbBot, D.zPiTop],
                bread=[-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zShelfTop, D.zBbTop], ghosts=ghosts)
    return dict(parts=parts, checks=checks, info=info)


def report(res, show_all=False):
    """검사 결과와 부품 목록을 글로 출력한다."""
    fails = [c for c in res['checks'] if not c['ok']]
    print(f"검사 {len(res['checks'])}건 중 {len(res['checks']) - len(fails)}건 통과, 실패 {len(fails)}건")
    for c in (res['checks'] if show_all else fails):
        print(f"  [{'통과' if c['ok'] else '실패'}] {c['name']}: {c['value']}  ({c['detail']})")
    print(f"전체 높이: A·C {res['info']['ghosts']['A']['total']} mm, B {res['info']['ghosts']['B']['total']} mm")
    print()
    print(f"{'파일':24s} {'크기 (mm)':22s} {'부피(cm³)':>9s}  출력 방향")
    for p in res['parts']:
        print(f"{p['id'] + '.stl':24s} {' x '.join(str(v) for v in p['size']):22s} {p['volume']:>9}  {p['note']}")


def save_all(res, outdir='models'):
    """모든 부품을 STL로 저장하고 파일 경로 목록을 돌려준다."""
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for p in res['parts']:
        path = os.path.join(outdir, p['id'] + '.stl')
        with open(path, 'wb') as f:
            f.write(to_stl(p['mesh'], p['id']))
        paths.append(path)
    return paths


if __name__ == '__main__':
    args, out, user = sys.argv[1:], None, {}
    while args:
        a = args.pop(0)
        if a == '--out':
            out = args.pop(0)
        elif '=' in a:
            k, v = a.split('=', 1)
            if k not in DEFAULTS:
                sys.exit(f'모르는 변수: {k}. 쓸 수 있는 변수: {", ".join(DEFAULTS)}')
            try:
                user[k] = float(v)
            except ValueError:
                sys.exit(f'{k}의 값이 숫자가 아닙니다: {v}')
        else:
            sys.exit(__doc__)
    result = build(user)
    report(result)
    if out:
        print(f"\nSTL {len(save_all(result, out))}개를 {out} 폴더에 저장했습니다.")
    sys.exit(0 if all(c['ok'] for c in result['checks']) else 1)
