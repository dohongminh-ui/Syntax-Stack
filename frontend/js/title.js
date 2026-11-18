// Per-screen document.title (tiny helper; no game logic).
const BASE = 'Syntax Stack — Học Python bằng cách xếp khối mã';
const TITLES = {
  'screen-start': BASE,
  'screen-game': 'Code Rescue — Syntax Stack',
  'screen-rows-select': 'Syntax Rows — Syntax Stack',
  'screen-practice': 'Luyện tập — Syntax Stack',
  'screen-skills': 'Bản đồ kỹ năng — Syntax Stack',
  'screen-custom': 'Tạo câu đố từ code — Syntax Stack',
  'screen-end': 'Kết quả — Syntax Stack',
};

export function setScreenTitle(id) {
  if (TITLES[id]) document.title = TITLES[id];
}

export function setLevelTitle(order, title) {
  document.title = `Màn ${order} · ${title} — Syntax Stack`;
}
