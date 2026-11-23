// PI-TECT 삼각대용 통합 케이스: 파라메트릭 모델 (단위 mm)
// 좌표: x = 길이(중심 0, -x 쪽이 라파이 USB/랜), y = 폭(중심 0, +y = 뒤, 전원/HDMI 쪽), z = 높이(케이스 바깥 바닥 0)
// 버전: A = 나사 4개(후크 + M3 2개, 라파이 핀 2 + 나사 2) / B = 슬라이드 뚜껑 + 잠금 핀 / C = 스냅락 뚜껑

export const DEFAULTS = {
  // ---- 실측값 ----
  camL: 105.6, camD: 63.3, camH: 55.3,   // 웹캠 (클립 접은 상태)
  bbL: 165, bbW: 56.4, bbH: 10,          // 풀사이즈 빵판
  piEnvW: 58.7, piTop: 19,               // 라파이 폭(포트 돌출 포함), PCB 밑면부터 최고 높이
  usbOver: 3.0,                          // USB 포트 끝면 → PCB 끝 거리. 실측 필요 (포트 끝면~가까운 구멍 중심 거리 - 23.5)
  nutAF: 11.1, nutT: 5.6,                // 1/4"-20 육각 너트 대변, 두께
  // ---- 설계값 ----
  wall: 2.4, floor: 2.4, standoff: 5,
  piGap: 1.0,                            // USB 포트 끝면과 왼쪽 안벽 사이
  piClear: 8,                            // 라파이 최고점과 선반 밑면 사이
  shelfT: 2.4,
  jumper: 20.2,                          // 빵판 윗면과 뚜껑 밑면 사이 (듀폰 점퍼 기준 20)
  camFit: 0.8,                           // 웹캠 받침 여유 (전체)
  nutFloor: 1.6,                         // 너트 아래 남기는 살
  nutX: 28,                              // 너트 보스 x 위치. SD 카드를 빼는 길(약 16 mm)을 비워 둠
  ledX: -55, ledHole: 6.4, ledWindow: 5.0,
  fit: 0.4,                              // 끼움 여유 (슬라이드 레일, 스냅 홈)
};

export function dims(P) {
  const inL = P.bbL + 16, inW = P.camD + P.camFit;
  const ix = inL / 2, iy = inW / 2, hx = ix + P.wall, hy = iy + P.wall;
  const zPcbBot = P.floor + P.standoff, zPcbTop = zPcbBot + 1.6, zPiTop = zPcbBot + P.piTop;
  const zShelf = zPiTop + P.piClear, zShelfTop = zShelf + P.shelfT, zBbTop = zShelfTop + P.bbH;
  const zRim = Math.round((zBbTop + P.jumper) * 10) / 10;
  const xFace = -ix + P.piGap, pcbX0 = xFace + P.usbOver, pcbX1 = pcbX0 + 85;
  const pcbY0 = -P.piEnvW / 2, pcbY1 = pcbY0 + 56, pcbYc = pcbY0 + 28;
  const h1 = pcbX1 - 3.5 - 58, h2 = pcbX1 - 3.5;
  const holes = [
    { x: h1, y: pcbYc - 24.5 }, { x: h1, y: pcbYc + 24.5 },
    { x: h2, y: pcbYc - 24.5 }, { x: h2, y: pcbYc + 24.5 },
  ];
  const gpioC = pcbX1 - 32.5, gpio0 = gpioC - 28, gpio1 = gpioC + 28;
  const bwX0 = pcbX1 - 54.0 - 6.5, bwX1 = pcbX1 - 11.2 + 7.5;        // 뒤벽 창: 오디오 잭 ~ USB-C
  const cx1 = hx - 10, cx0 = cx1 - (P.camL + P.camFit + 2 * P.wall);   // 웹캠 받침 바깥 x 범위
  const zWin0 = zPcbBot - 0.5, zWin1 = zPiTop + 1.6;                   // USB/랜 창 (브리지 처짐 여유 1.6)
  const bx0 = P.bbL / 2 + 0.8, bossX = (bx0 + ix) / 2, bossY = 18;     // 오른쪽 보스
  const nutTop = P.nutFloor + P.nutT + 0.8;
  return { inL, inW, ix, iy, hx, hy, zPcbBot, zPcbTop, zPiTop, zShelf, zShelfTop, zBbTop, zRim, xFace, pcbX0, pcbX1,
    pcbY0, pcbY1, pcbYc, holes, gpio0, gpio1, bwX0, bwX1, cx0, cx1, zWin0, zWin1, bx0, bossX, bossY, nutTop,
    outL: 2 * hx, outW: 2 * hy, xw: 8, snapXs: [{ x: -60, w: 8 }, { x: 86.5, w: 6 }] };
}

function kit(wasm) {
  const { Manifold } = wasm;
  const ccw = (pts) => {
    let a = 0;
    for (let i = 0; i < pts.length; i++) { const p = pts[i], q = pts[(i + 1) % pts.length]; a += p[0] * q[1] - q[0] * p[1]; }
    return a < 0 ? pts.slice().reverse() : pts;
  };
  const box = (x0, x1, y0, y1, z0, z1) => Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0]);
  const cyl = (x, y, z0, z1, r, seg = 48) => Manifold.cylinder(z1 - z0, r, r, seg).translate([x, y, z0]);
  const cone = (x, y, z0, z1, r0, r1, seg = 48) => Manifold.cylinder(z1 - z0, r0, r1, seg).translate([x, y, z0]);
  const hex = (x, y, z0, z1, af) => { const r = af / 2 / Math.cos(Math.PI / 6); return Manifold.cylinder(z1 - z0, r, r, 6).translate([x, y, z0]); };
  // 단면 [y, z]를 x 방향으로 밀기 / 단면 [x, z]를 y 방향으로 밀기
  const prismX = (pts, x0, x1) => Manifold.extrude([ccw(pts)], x1 - x0).rotate([90, 0, 90]).translate([x0, 0, 0]);
  const prismY = (pts, y0, y1) => Manifold.extrude([ccw(pts)], y1 - y0).rotate([90, 0, 0]).translate([0, y1, 0]);
  const prismZ = (pts, z0, z1) => Manifold.extrude([ccw(pts)], z1 - z0).translate([0, 0, z0]);
  // 중심 (cx, cy)에서 반지름 방향으로 r0~r1에 놓인 가는 리브 (deg 방향)
  const rib = (cx, cy, r0, r1, w, z0, z1, deg) => Manifold.cube([r1 - r0, w, z1 - z0]).translate([r0, -w / 2, z0]).rotate([0, 0, deg]).translate([cx, cy, 0]);
  const circle = (cx, cz, r, n = 20) => Array.from({ length: n }, (_, i) => [cx + r * Math.cos((2 * Math.PI * i) / n), cz + r * Math.sin((2 * Math.PI * i) / n)]);
  const U = (list) => Manifold.union(list);
  const vol = (m) => (typeof m.volume === 'function' ? m.volume() : m.getProperties().volume);
  return { Manifold, box, cyl, cone, hex, prismX, prismY, prismZ, rib, circle, U, vol };
}

function buildCase(P, D, K, ver) {
  const { box, cyl, cone, hex, prismX, prismY, rib, circle, U } = K;
  const { ix, iy, hx, hy, zRim, zShelf } = D;
  const add = [], cut = [];
  const shell = box(-hx, hx, -hy, hy, 0, zRim).subtract(box(-ix, ix, -iy, iy, P.floor, zRim + 1));

  // 라파이 스탠드오프 4개. 대각선 2개(1, 2번)는 위치 핀, 나머지는 A에서만 나사 구멍
  D.holes.forEach((h, i) => {
    add.push(cyl(h.x, h.y, P.floor - 0.3, D.zPcbBot, 3.0));
    if (i === 1 || i === 2) {
      add.push(cyl(h.x, h.y, D.zPcbBot - 0.1, D.zPcbBot + 2.2, 1.2, 32));
      add.push(cone(h.x, h.y, D.zPcbBot + 2.2, D.zPcbBot + 2.8, 1.2, 0.8, 32));
    } else {
      cut.push(cyl(h.x, h.y, 1.4, D.zPcbBot + 1, 1.1, 32));   // M2.5 셀프탭용 Ø2.2 (A는 필수, B·C는 선택)
    }
  });

  // 선반 턱: 아래 45° 모따기. 라파이 구간은 폭 2, 그 밖은 3.5. 앞쪽은 GPIO 선 통과 구간을 비움
  const ledge = (s, w, x0, x1) => prismX([[s * (iy + 0.3), zShelf], [s * (iy - w), zShelf], [s * (iy - w), zShelf - 1], [s * (iy + 0.3), zShelf - 1 - w - 0.3]], x0, x1);
  add.push(ledge(1, 2.0, -ix - 0.3, D.xw), ledge(1, 3.5, D.xw, ix + 0.3));
  add.push(ledge(-1, 2.0, -ix - 0.3, D.gpio0), ledge(-1, 2.0, D.gpio1, D.xw), ledge(-1, 3.5, D.xw, ix + 0.3));

  // 선반·빵판 왼쪽 멈춤 리브 (USB/랜 창 위, 아래 45°)
  const rz = D.zWin1 + 0.5;
  for (const s of [-1, 1]) {
    add.push(prismY([[-ix - 0.3, rz - 0.3], [-ix + 7.2, rz + 7.2], [-ix + 7.2, D.zBbTop - 2.8], [-ix - 0.3, D.zBbTop - 2.8]], s * D.bossY - 1.5, s * D.bossY + 1.5));
  }

  // 오른쪽 보스 2개 (선반 멈춤 겸용). A는 M3 셀프탭 Ø2.6, B는 잠금 핀 Ø4.4
  for (const s of [-1, 1]) {
    add.push(box(D.bx0, ix + 0.3, s * D.bossY - 3.7, s * D.bossY + 3.7, P.floor - 0.3, zRim));
    if (ver === 'A') cut.push(cyl(D.bossX, s * D.bossY, zRim - 12, zRim + 1, 1.3, 32));
    if (ver === 'B') cut.push(cyl(D.bossX, s * D.bossY, zRim - 12, zRim + 1, 2.2, 32));
  }

  // 삼각대 너트 보스: 케이스 안쪽에서 너트를 넣고, 너트 아래에 살을 남김
  add.push(cyl(P.nutX, 0, P.floor - 0.3, D.nutTop, 10, 64));
  cut.push(hex(P.nutX, 0, P.nutFloor, D.nutTop + 1, P.nutAF + 0.4));
  cut.push(cyl(P.nutX, 0, -1, P.nutFloor + 0.5, 3.4));

  // 포트 창
  cut.push(box(-hx - 1, -ix + 0.01, D.pcbY0 - 1, D.pcbY1 + 1, D.zWin0, D.zWin1));       // USB/랜 (왼쪽 벽)
  cut.push(box(D.bwX0, D.bwX1, iy - 0.01, hy + 1, D.zPcbTop - 4, D.zPcbTop + 8.5));      // 전원/HDMI/오디오 (뒤벽)

  // 통풍: 바닥 슬롯 5개 + 앞벽 슬롯 7개
  for (let k = 0; k < 5; k++) { const x = D.holes[0].x + 11 + 9 * k; cut.push(box(x - 1.25, x + 1.25, D.pcbYc - 15, D.pcbYc + 15, -1, P.floor + 1)); }
  for (let k = 0; k < 7; k++) { const x = D.holes[0].x + 7 + 7 * k; cut.push(box(x - 1.25, x + 1.25, -hy - 1, -iy + 0.01, D.zPcbTop + 1, D.zPcbTop + 13)); }

  // 케이블 타이 고리 (뒤벽 바깥): 아래 45° 받침 + 세로 막대 + 위 브리지
  const lx0 = 47.5, lx1 = 52.5;
  add.push(box(lx0, lx1, hy + 3.55, hy + 6.55, 30, 46));
  add.push(prismX([[hy - 0.3, 23.15], [hy + 6.55, 30], [hy + 3.55, 30], [hy - 0.3, 26.15]], lx0, lx1));
  add.push(box(lx0, lx1, hy - 0.3, hy + 6.55, 46, 48.5));

  if (ver === 'A') {
    // 왼쪽 벽을 올려 뚜껑 끝을 누르는 45° 후크 + 모서리 귀
    add.push(box(-hx, -ix, -hy, hy, zRim - 0.3, zRim + 3.9));
    add.push(prismY([[-ix - 0.3, zRim + 0.9], [-ix + 2.7, zRim + 3.9], [-ix - 0.3, zRim + 3.9]], -28, 28));
    for (const s of [-1, 1]) add.push(box(-ix - 0.3, -ix + 6, Math.min(s * hy, s * (hy - 1.2)), Math.max(s * hy, s * (hy - 1.2)), zRim - 0.3, zRim + 3.4));
  }
  if (ver === 'B') {
    // 긴 벽 위 45° 레일 + 왼쪽 멈춤
    for (const s of [-1, 1]) add.push(prismX([[s * hy, zRim - 0.3], [s * (hy - 1.2), zRim - 0.3], [s * (hy - 1.2), zRim], [s * (hy - 2.7), zRim + 1.5], [s * hy, zRim + 1.5]], -hx, hx));
    add.push(box(-hx, -ix, -10, 10, zRim - 0.3, zRim + 4.5 + P.fit));   // 뚜껑 홈에 맞물리는 멈춤 블록
  }
  if (ver === 'C') {
    // 스냅 후크 4개: 벽에 세로 홈 2개를 내어 만든 외팔보 + 45° 걸림턱
    for (const h of D.snapXs) for (const s of [-1, 1]) {
      const y0 = Math.min(s * (iy - 0.5), s * (hy + 0.5)), y1 = Math.max(s * (iy - 0.5), s * (hy + 0.5));
      const zs = zRim - 16 + 0.75;
      for (const xs of [h.x - h.w / 2 - 0.75, h.x + h.w / 2 + 0.75]) {
        cut.push(box(xs - 0.75, xs + 0.75, y0, y1, zs, zRim + 1));
        cut.push(prismY(circle(xs, zs, 0.75), y0, y1));              // 응력 집중을 줄이는 둥근 뿌리
      }
      add.push(box(h.x - h.w / 2, h.x + h.w / 2, Math.min(s * iy, s * hy), Math.max(s * iy, s * hy), zRim - 0.3, zRim + 6.2));
      add.push(prismX([[s * (iy + 0.3), zRim + 2.9], [s * (iy - 1.5), zRim + 4.7], [s * iy, zRim + 6.2], [s * (iy + 0.3), zRim + 6.2]], h.x - h.w / 2, h.x + h.w / 2));
    }
  }
  // 넓은 창 2곳의 브리지를 3등분하는 떼어내는 리브 (두께 0.8, 출력 후 니퍼로 제거)
  const tear = [], wy0 = D.pcbY0 - 1, wy1 = D.pcbY1 + 1;
  for (const f of [1 / 3, 2 / 3]) {
    const y = wy0 + (wy1 - wy0) * f, x = D.bwX0 + (D.bwX1 - D.bwX0) * f;
    tear.push(box(-hx, -ix, y - 0.4, y + 0.4, D.zWin0 - 0.2, D.zWin1 + 0.2));
    tear.push(box(x - 0.4, x + 0.4, iy, hy, D.zPcbTop - 4.2, D.zPcbTop + 8.7));
  }
  // 눌림 리브: 너트와 잠금 핀이 헐거워 빠지지 않도록 살짝 조이는 가는 세로 리브
  const pf = (P.nutAF + 0.4) / 2;
  for (let k = 0; k < 6; k++) tear.push(rib(P.nutX, 0, pf - 0.3, pf + 0.3, 0.6, P.nutFloor, D.nutTop, 30 + 60 * k));
  if (ver === 'B') for (const s of [-1, 1]) for (const a of [90, 210, 330]) tear.push(rib(D.bossX, s * D.bossY, 1.85, 2.5, 0.6, zRim - 12, zRim - 1, a));
  return U([U([shell, ...add]).subtract(U(cut)), ...tear]);
}

function lidExtras(P, D, K, top) {
  const { box } = K;
  const { iy, hy, cx0, cx1 } = D;
  const add = [], cut = [];
  // 웹캠 받침: 뚜껑 판이 바닥. 앞쪽은 턱 4 mm만 남기고 개방
  add.push(box(cx0, cx1, -hy, hy, top - 0.02, top + 14));
  cut.push(box(cx0 + P.wall, cx1 - P.wall, -iy, iy, top, top + 15));
  cut.push(box(cx0 + P.wall + 8, cx1 - P.wall - 8, -hy - 1, -iy + 0.01, top + 4, top + 15));
  // 벨크로 스트랩 걸이 2개 (받침 좌우)
  for (const x0 of [cx0 - 9, cx1 + 1.5]) {
    add.push(box(x0, x0 + 6, -11.5, -8.5, top - 0.3, top + 3.5), box(x0, x0 + 6, 8.5, 11.5, top - 0.3, top + 3.5));
    add.push(box(x0, x0 + 6, -11.5, 11.5, top + 3.5, top + 6.1));
  }
  return { add, cut };
}

function buildLid(P, D, K, ver) {
  const { box, cyl, cone, prismX, prismY, prismZ, U } = K;
  const { ix, iy, hx, hy, zRim } = D;
  let plate, top;
  const cut = [];
  if (ver === 'A') {
    top = zRim + 3.4;
    const xL = -ix + 0.3;
    plate = box(xL, hx, -hy, hy, zRim, top);
    for (const s of [-1, 1]) cut.push(box(-ix - 1, -ix + 6.3, Math.min(s * (hy - 1.45), s * (hy + 1)), Math.max(s * (hy - 1.45), s * (hy + 1)), zRim - 1, top + 1));
    cut.push(prismY([[xL - 0.5, zRim + 0.5], [xL + 2.41, top + 0.01], [xL - 0.5, top + 0.01]], -hy - 1, hy + 1));   // 후크에 물리는 45° 끝
    for (const s of [-1, 1]) cut.push(cyl(D.bossX, s * D.bossY, zRim - 1, top + 1, 1.7, 32));                        // M3 Ø3.4
    cut.push(cyl(P.ledX, 0, zRim - 1, top + 1, P.ledHole / 2), cone(P.ledX, 0, zRim - 0.01, zRim + 1, P.ledHole / 2 + 1, P.ledHole / 2));
  }
  if (ver === 'B') {
    const b = hy - 1.2 - P.fit, n = hy - 2.7 - P.fit;
    top = zRim + 1.8 + (hy - n);
    plate = prismX([[-b, zRim], [b, zRim], [n, zRim + 1.5], [n, zRim + 1.8], [hy, top], [-hy, top], [-n, zRim + 1.8], [-n, zRim + 1.5]], -hx, hx);
    cut.push(box(-hx - 1, -ix + 0.3, -10.4, 10.4, zRim - 1, top + 1));                 // 멈춤 블록이 들어오는 홈 (수직 관통)
    for (const s of [-1, 1]) cut.push(prismZ([[-hx - 1, s * (b - 3)], [-hx + 3, s * (b + 1)], [-hx - 1, s * (b + 1)]], zRim - 1, zRim + 1.5));   // 레일 진입 모따기 2 mm
    for (const s of [-1, 1]) cut.push(cyl(D.bossX, s * D.bossY, zRim - 1, top + 1, 2.2, 32));   // 잠금 핀 Ø4.4
    cut.push(cyl(P.ledX, 0, zRim - 1, top + 1, P.ledWindow / 2));                       // LED 빛 창 (LED는 뚜껑 아래)
  }
  if (ver === 'C') {
    top = zRim + 3.4;
    plate = box(-hx, hx, -hy, hy, zRim, top);
    for (const h of D.snapXs) for (const s of [-1, 1]) {
      cut.push(box(h.x - h.w / 2 - 0.4, h.x + h.w / 2 + 0.4, Math.min(s * (iy - P.fit), s * (hy + 1)), Math.max(s * (iy - P.fit), s * (hy + 1)), zRim - 1, top + 1));
    }
    cut.push(cyl(P.ledX, 0, zRim - 1, top + 1, P.ledHole / 2), cone(P.ledX, 0, zRim - 0.01, zRim + 1, P.ledHole / 2 + 1, P.ledHole / 2));
  }
  const ex = lidExtras(P, D, K, top);
  return { solid: U([plate, ...ex.add]).subtract(U([...cut, ...ex.cut])), top };
}

function buildShelf(P, D, K) {
  const { box, U } = K;
  const hw = (D.inW - 0.8) / 2, hl = P.bbL / 2 + 0.5, r = P.bbW / 2 + 0.4;
  const plate = box(-hl, hl, -hw, hw, 0, P.shelfT);
  const rails = [box(-hl + 3, hl - 3, r, r + 1.8, P.shelfT - 0.3, P.shelfT + 6), box(D.gpio1 + 4, hl - 3, -r - 1.8, -r, P.shelfT - 0.3, P.shelfT + 6)];
  return U([plate, ...rails]).subtract(box(D.gpio0, D.gpio1, -hw - 1, -hw + 4.5, -1, P.shelfT + 1));
}

function buildPin(K) {
  const { cyl, cone, U } = K;
  return U([cyl(0, 0, 0, 1.6, 3.75), cyl(0, 0, 1.5, 2.4, 2.5, 32), cyl(0, 0, 2.3, 14.3, 2.0, 32), cone(0, 0, 14.3, 14.9, 2.0, 1.5, 32)]);
}

function keepouts(P, D, K) {
  const { box, cyl, hex, U } = K;
  const pcb = box(D.pcbX0, D.pcbX1, D.pcbY0, D.pcbY1, D.zPcbBot, D.zPcbTop).subtract(U(D.holes.map((h) => cyl(h.x, h.y, D.zPcbBot - 1, D.zPcbTop + 1, 1.35, 32))));
  return {
    'PCB': pcb,
    'USB/랜 포트': box(D.xFace, D.xFace + 21, D.pcbY0 + 1, D.pcbY1 - 1, D.zPcbTop, D.zPiTop),
    'GPIO 헤더': box(D.pcbX1 - 57.9, D.pcbX1 - 7.1, D.pcbY0 + 1, D.pcbY0 + 6, D.zPcbTop, D.zPcbTop + 8.5),
    '전원/HDMI 돌출': box(D.bwX0 + 1, D.bwX1 - 1, D.pcbY1, P.piEnvW / 2, D.zPcbTop, D.zPcbTop + 4),
    'SD 카드': box(D.pcbX1, D.pcbX1 + 3, D.pcbYc - 6, D.pcbYc + 6, D.zPcbBot - 1.4, D.zPcbBot),
    '너트': hex(P.nutX, 0, P.nutFloor, P.nutFloor + P.nutT, P.nutAF),
  };
}

// Manifold 출력에는 한 변 위에 꼭짓점이 놓인 자리마다 면적 0 삼각형이 남는다.
// 그 삼각형을 지우고 맞은편 이웃 삼각형을 그 꼭짓점에서 둘로 나누면, 닫힌 상태를 유지한 채 깨끗한 메시가 된다.
function cleanMesh(pos, idxIn) {
  let tris = [];
  for (let i = 0; i < idxIn.length; i += 3) tris.push([idxIn[i], idxIn[i + 1], idxIn[i + 2]]);
  const pt = (i) => [pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]];
  const d2 = (a, b) => { const p = pt(a), q = pt(b); return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2; };
  const area2 = (t) => { const a = pt(t[0]), b = pt(t[1]), c = pt(t[2]); const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = c[0] - a[0], vy = c[1] - a[1], vz = c[2] - a[2]; return Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx); };
  const E = [[0, 1, 2], [1, 2, 0], [2, 0, 1]];
  for (let pass = 0; pass < 500; pass++) {
    const k = tris.findIndex((t) => area2(t) < 1e-6);
    if (k < 0) break;
    const t = tris[k];
    const e = E.map(([i, j, m]) => ({ a: t[i], b: t[j], m: t[m], l: d2(t[i], t[j]) })).sort((x, y) => y.l - x.l)[0];
    if (d2(e.m, e.a) < 1e-12 || d2(e.m, e.b) < 1e-12) {            // 두 꼭짓점이 같은 자리: 하나로 합침
      const keep = d2(e.m, e.a) < 1e-12 ? e.a : e.b;
      tris = tris.map((u) => u.map((v) => (v === e.m ? keep : v))).filter((u) => u[0] !== u[1] && u[1] !== u[2] && u[2] !== u[0]);
      continue;
    }
    const n = tris.findIndex((u, ui) => ui !== k && E.some(([i, j]) => u[i] === e.b && u[j] === e.a));
    if (n < 0) break;
    const d = tris[n].find((v) => v !== e.a && v !== e.b);
    tris = tris.filter((_, i) => i !== k && i !== n).concat([[e.b, e.m, d], [e.m, e.a, d]]);
  }
  const edges = new Map();
  for (const t of tris) for (const [i, j] of E) edges.set(t[i] + '>' + t[j], (edges.get(t[i] + '>' + t[j]) || 0) + 1);
  let open = 0;
  for (const [key, c] of edges) { const [a, b] = key.split('>'); if (c !== 1 || edges.get(b + '>' + a) !== 1) open++; }
  return { idx: new Uint32Array(tris.flat()), degenerate: tris.filter((t) => area2(t) < 1e-6).length, openEdges: open };
}

function meshOf(m) {
  const g = m.getMesh();
  const np = g.numProp, vp = g.vertProperties, tv = g.triVerts;
  const pos = new Float32Array((vp.length / np) * 3);
  for (let i = 0, j = 0; i < vp.length; i += np, j += 3) { pos[j] = vp[i]; pos[j + 1] = vp[i + 1]; pos[j + 2] = vp[i + 2]; }
  const c = cleanMesh(pos, tv);
  return { pos, idx: c.idx, degenerate: c.degenerate, openEdges: c.openEdges, rawDegenerate: (() => { let n = 0; for (let i = 0; i < tv.length; i += 3) { const a = [pos[3 * tv[i]], pos[3 * tv[i] + 1], pos[3 * tv[i] + 2]], b = [pos[3 * tv[i + 1]], pos[3 * tv[i + 1] + 1], pos[3 * tv[i + 1] + 2]], q = [pos[3 * tv[i + 2]], pos[3 * tv[i + 2] + 1], pos[3 * tv[i + 2] + 2]]; const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = q[0] - a[0], vy = q[1] - a[1], vz = q[2] - a[2]; if (Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) < 1e-6) n++; } return n; })() };
}

export function toSTL(mesh, name) {
  const { pos, idx } = mesh, n = idx.length / 3;
  const buf = new ArrayBuffer(84 + 50 * n), dv = new DataView(buf);
  const head = 'PI-TECT ' + name;
  for (let i = 0; i < Math.min(head.length, 79); i++) dv.setUint8(i, head.charCodeAt(i) & 0x7f);
  dv.setUint32(80, n, true);
  let o = 84;
  for (let t = 0; t < n; t++) {
    const a = idx[3 * t] * 3, b = idx[3 * t + 1] * 3, c = idx[3 * t + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz) || 1; nx /= l; ny /= l; nz /= l;
    dv.setFloat32(o, nx, true); dv.setFloat32(o + 4, ny, true); dv.setFloat32(o + 8, nz, true); o += 12;
    for (const k of [a, b, c]) { dv.setFloat32(o, pos[k], true); dv.setFloat32(o + 4, pos[k + 1], true); dv.setFloat32(o + 8, pos[k + 2], true); o += 12; }
    o += 2;
  }
  return buf;
}

// 전체 빌드: 부품, 검증 결과, 미리보기용 배치 정보를 돌려준다
export function build(wasm, userP = {}) {
  const P = { ...DEFAULTS, ...userP }, D = dims(P), K = kit(wasm);
  const { box, U, vol } = K;
  const r1 = (v) => Math.round(v * 10) / 10;
  const parts = [], checks = [];
  const bb = (m) => { const b = m.boundingBox(); return [r1(b.max[0] - b.min[0]), r1(b.max[1] - b.min[1]), r1(b.max[2] - b.min[2])]; };
  const zmin = (m) => m.boundingBox().min[2];
  const push = (id, ver, label, solid, asm, color, note) => {
    const dz = zmin(solid), print = solid.translate([0, 0, -dz]);
    const status = typeof print.status === 'function' ? print.status() : 'NoError';
    const st = typeof status === 'object' && status !== null && 'value' in status ? status.value : status;
    const mesh = meshOf(print);
    parts.push({ id, ver, label, note, color, size: bb(print), volume: r1(vol(print) / 1000), tris: mesh.idx.length / 3, genus: print.genus(),
      ok: !print.isEmpty() && (st === 0 || st === 'NoError') && mesh.degenerate === 0 && mesh.openEdges === 0, asm: asm ? [asm[0], asm[1], asm[2] + dz] : null, mesh, solid });
  };
  const chk = (name, value, ok, detail) => checks.push({ name, value: typeof value === 'number' ? Math.round(value * 100) / 100 : value, ok, detail });
  const ivol = (a, b) => vol(a.intersect(b));

  const shelf = buildShelf(P, D, K), shelfAsm = shelf.translate([0, 0, D.zShelf]);
  const ko = keepouts(P, D, K);
  const bread = box(-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zShelfTop, D.zBbTop);
  const names = { A: '나사형', B: '슬라이드형', C: '스냅락형' };
  const ghosts = {};

  for (const ver of ['A', 'B', 'C']) {
    const cs = buildCase(P, D, K, ver), lid = buildLid(P, D, K, ver);
    const cam = box(D.cx0 + P.wall + P.camFit / 2, D.cx1 - P.wall - P.camFit / 2, -P.camD / 2, P.camD / 2, lid.top, lid.top + P.camH);
    push(`${ver}_case`, ver, `케이스 (${names[ver]})`, cs, [0, 0, 0], 'case', '바닥을 베드에');
    push(`${ver}_lid`, ver, `뚜껑 (${names[ver]})`, lid.solid, [0, 0, 0], 'lid', '판을 베드에, 받침이 위');
    ghosts[ver] = { cam: [D.cx0 + P.wall + P.camFit / 2, D.cx1 - P.wall - P.camFit / 2, -P.camD / 2, P.camD / 2, lid.top, lid.top + P.camH], total: r1(lid.top + P.camH), lidTop: r1(lid.top) };

    for (const [k, s] of Object.entries(ko)) {
      if (k === '너트') chk(`${ver}: 케이스 눌림 리브 ↔ 너트`, ivol(cs, s), ivol(cs, s) > 0.2 && ivol(cs, s) < 4, '의도한 조임 간섭 mm³ (0.2~4)');
      else chk(`${ver}: 케이스 ↔ ${k}`, ivol(cs, s), ivol(cs, s) < 0.01, '겹침 부피 mm³');
    }
    { const sd = box(D.pcbX1, D.pcbX1 + 16, D.pcbYc - 6.5, D.pcbYc + 6.5, D.zPcbBot - 1.6, D.zPcbBot); chk(`${ver}: SD 카드를 빼는 경로`, ivol(cs, sd), ivol(cs, sd) < 0.01, '겹침 부피 mm³'); }
    chk(`${ver}: 케이스 ↔ 선반`, ivol(cs, shelfAsm), ivol(cs, shelfAsm) < 0.01, '겹침 부피 mm³');
    chk(`${ver}: 케이스 ↔ 빵판`, ivol(cs, bread), ivol(cs, bread) < 0.01, '겹침 부피 mm³');
    chk(`${ver}: 케이스 ↔ 뚜껑`, ivol(cs, lid.solid), ivol(cs, lid.solid) < 0.01, '겹침 부피 mm³');
    chk(`${ver}: 뚜껑 ↔ 웹캠`, ivol(lid.solid, cam), ivol(lid.solid, cam) < 0.01, '겹침 부피 mm³');
    chk(`${ver}: 뚜껑 ↔ 빵판 위 20 mm 공간`, ivol(lid.solid, box(-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zBbTop, D.zBbTop + 20)), ivol(lid.solid, box(-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zBbTop, D.zBbTop + 20)) < 0.01, '겹침 부피 mm³');
    const lift = ivol(cs, lid.solid.translate([0, 0, 1.2]));
    chk(`${ver}: 뚜껑을 1.2 mm 들면 걸리는가`, lift, lift > 0.05, '걸림 부피 mm³ (0보다 커야 고정됨)');
    if (ver === 'B') {
      let worst = 0;
      for (let d = 5; d <= 190; d += 5) worst = Math.max(worst, ivol(cs, lid.solid.translate([d, 0, 0])));
      chk('B: 뚜껑을 오른쪽으로 밀어 빼는 경로', worst, worst < 0.01, '경로 중 최대 겹침 mm³');
      const pin = buildPin(K);
      push('B_lock_pin', 'B', '잠금 핀 (2개 출력)', pin, null, 'pin', '머리를 베드에');
      const pinAsm = pin.rotate([180, 0, 0]).translate([D.bossX, D.bossY, lid.top + 2.4]);
      chk('B: 잠금 핀 ↔ 뚜껑', ivol(pinAsm, lid.solid), ivol(pinAsm, lid.solid) < 0.01, '겹침 부피 mm³');
      chk('B: 잠금 핀 ↔ 케이스 눌림 리브', ivol(pinAsm, cs), ivol(pinAsm, cs) > 0.2 && ivol(pinAsm, cs) < 4, '의도한 조임 간섭 mm³ (0.2~4)');
    }
    // 시험 조각
    if (ver === 'A') push('test_window', '공통', '시험 조각: USB/랜 창 + 떼어내는 리브', cs.intersect(box(-D.hx - 1, -D.ix + 8, -D.hy - 1, D.hy + 1, -1, D.zWin1 + 3)), null, 'test', '브리지 처짐과 리브 제거 확인');
    if (ver === 'A') push('test_A_floor', 'A', '시험 조각: 라파이 바닥 + 너트 보스', cs.intersect(box(-D.hx - 1, P.nutX + 13, -D.hy - 10, D.hy + 10, -1, 12)), null, 'test', '스탠드오프·핀·창·너트 맞춤 확인');
    if (ver === 'B') {
      const zc = box(20, 50, -D.hy - 1, D.hy + 1, D.zRim - 8, D.zRim + 6);
      push('test_B_rail_case', 'B', '시험 조각: 레일 (케이스 쪽)', U([cs.intersect(zc), box(20, 50, -D.hy, D.hy, D.zRim - 8, D.zRim - 6.4)]), null, 'test', '슬라이드 공차 확인');
      push('test_B_rail_lid', 'B', '시험 조각: 레일 (뚜껑 쪽)', lid.solid.intersect(box(-70, -40, -D.hy - 1, D.hy + 1, D.zRim - 1, lid.top)), null, 'test', '슬라이드 공차 확인');
    }
    if (ver === 'C') {
      const zc = box(-72, -48, -D.hy - 1, D.hy + 1, D.zRim - 20, D.zRim + 8);
      push('test_C_snap_case', 'C', '시험 조각: 스냅 후크 (케이스 쪽)', U([cs.intersect(zc), box(-72, -48, -D.hy, D.hy, D.zRim - 20, D.zRim - 18.4)]), null, 'test', '스냅 걸림 확인');
      push('test_C_snap_lid', 'C', '시험 조각: 스냅 후크 (뚜껑 쪽)', lid.solid.intersect(box(-72, -48, -D.hy - 1, D.hy + 1, D.zRim - 1, lid.top)), null, 'test', '스냅 걸림 확인');
    }
  }
  push('shelf', '공통', '선반 (공통)', shelf, [0, 0, D.zShelf], 'shelf', '판을 베드에, 레일이 위');
  for (const [k, s] of Object.entries(ko)) if (k !== '너트') chk(`선반 ↔ ${k}`, ivol(shelfAsm, s), ivol(shelfAsm, s) < 0.01, '겹침 부피 mm³');

  for (const p of parts) chk(`메시 상태: ${p.id}`, `${p.tris} 삼각형`, p.ok, `닫힌 메시, 면적 0 삼각형 ${p.mesh.rawDegenerate}개 정리 후 ${p.mesh.degenerate}개, 열린 모서리 ${p.mesh.openEdges}개`);
  chk('전체 높이 (A·C)', ghosts.A.total, true, 'mm, 삼각대 플레이트 면 기준');
  chk('전체 높이 (B)', ghosts.B.total, true, 'mm, 삼각대 플레이트 면 기준');
  chk('스탠드오프 x (왼쪽 안벽 기준)', `${r1(D.holes[0].x + D.ix)} / ${r1(D.holes[2].x + D.ix)}`, true, 'mm');

  const info = { P, zRim: D.zRim, zShelf: D.zShelf, outL: r1(D.outL), outW: r1(D.outW),
    pi: [D.xFace, D.pcbX1, D.pcbY0, P.piEnvW / 2, D.zPcbBot, D.zPiTop], bread: [-P.bbL / 2, P.bbL / 2, -P.bbW / 2, P.bbW / 2, D.zShelfTop, D.zBbTop], ghosts };
  return { parts, checks, info };
}
