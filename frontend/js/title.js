// Per-screen document.title (tiny helper; no game logic).
const BASE = 'Syntax Stack — Học Python bằng cách xếp khối mã';
const TITLES = {
  'screen-start': BASE,
  'screen-game': 'Code Rescue — Syntax Stack',
  'screen-rows-select': 'Syntax Rows — Syntax Stack',
  'screen-practice': 'Luyện tập — Syntax Stack',
  'screen-skills': 'Bản đồ kỹ năng — Syntax Stack',
  'screen-custom': 'Tạo câu đố từ code — Syntax Stack',
  'screen-room-new': 'Lớp học trực tiếp — Syntax Stack',
  'screen-room-teach': 'Bảng điều khiển lớp — Syntax Stack',
  'screen-room-join': 'Vào phòng — Syntax Stack',
  'screen-end': 'Kết quả — Syntax Stack',
  'screen-leaderboard': 'Bảng xếp hạng — Syntax Stack',
  'screen-race-new': 'Đấu tốc độ — Syntax Stack',
  'screen-race': 'Đấu tốc độ — Syntax Stack',
  'screen-pvp': 'Đối kháng 1v1 — Syntax Stack',
  'screen-pvp-end': 'Kết quả đối kháng — Syntax Stack',
};

export function setScreenTitle(id) {
  if (TITLES[id]) document.title = TITLES[id];
}

export function setLevelTitle(order, title) {
  document.title = `Màn ${order} · ${title} — Syntax Stack`;
}
