'use strict';

/* ============================================================
   北谷町 統計マップ
   国勢調査の町丁字別データを MapLibre のコロプレスで見る。
   ============================================================ */

const PALETTES = {
  teal:   ['#e7f0f3', '#b7d6dd', '#7fb8c4', '#4794a5', '#0f6d7a'],
  warm:   ['#fdf0e3', '#f9d5ab', '#f2b174', '#e08748', '#b85c25'],
  green:  ['#eaf2e5', '#c3ddb7', '#95c286', '#63a45c', '#357a3d'],
  purple: ['#efeaf4', '#d0c3e0', '#ad98cb', '#8a6db3', '#644694'],
  diverge: ['#2f6ab4', '#8fb4dc', '#eeece7', '#e6a08f', '#b4402f'],
};

const METRICS = [
  { group: '人口', items: [
    { id: 'pop_2020', label: '人口', unit: '人', palette: 'teal', digits: 0,
      desc: '2020年10月1日時点の常住人口。基地内など人が住んでいない区域は「—」。' },
    { id: 'pop_density', label: '人口密度', unit: '人/km²', palette: 'teal', digits: 0,
      desc: '人口を区域面積で割った値。北谷町は面積13.9km²に約2.8万人が住む。' },
    { id: 'pop_change_ratio', label: '人口増減率', unit: '%', palette: 'diverge', digits: 1,
      diverging: true, suffixSign: true,
      desc: '2015年→2020年の人口の増減。赤が増加、青が減少。町全体では −0.4% とほぼ横ばいだが、字ごとの動きは大きい。' },
  ]},
  { group: '年齢', items: [
    { id: 'ratio_o65', label: '高齢化率', unit: '%', palette: 'warm', digits: 1,
      desc: '65歳以上が人口に占める割合。町全体では20.4%（2015年は18.4%）。' },
    { id: 'ratio_o75', label: '75歳以上', unit: '%', palette: 'warm', digits: 1,
      desc: '75歳以上が人口に占める割合。介護・医療の需要と結びつきやすい層。' },
    { id: 'aging_change_pt', label: '高齢化の進み方', unit: 'pt', palette: 'diverge', digits: 1,
      diverging: true, suffixSign: true,
      desc: '2015年→2020年で高齢化率が何ポイント動いたか。赤ほど高齢化が速く進んだ区域。' },
    { id: 'ratio_u15', label: '年少人口率', unit: '%', palette: 'green', digits: 1,
      desc: '15歳未満が人口に占める割合。町全体では16.9%で、全国平均（11.9%）より高い。' },
  ]},
  { group: '世帯', items: [
    { id: 'hh_with_o65_ratio', label: '高齢者のいる世帯', unit: '%', palette: 'warm', digits: 1,
      desc: '65歳以上の世帯員がいる一般世帯の割合。見守りや在宅支援の当たりをつける手がかり。' },
    { id: 'hh_with_u18_ratio', label: '子どものいる世帯', unit: '%', palette: 'green', digits: 1,
      desc: '18歳未満の世帯員がいる一般世帯の割合。' },
    { id: 'hh_single_ratio', label: '単身世帯率', unit: '%', palette: 'purple', digits: 1,
      desc: '世帯人員1人の一般世帯の割合。町全体では36.0%。' },
    { id: 'hh_avg_members', label: '平均世帯人員', unit: '人', palette: 'purple', digits: 2,
      desc: '一般世帯1世帯あたりの人数。町全体では2.39人。' },
  ]},
];

const ALL_METRICS = METRICS.flatMap((g) => g.items);
const byId = (id) => ALL_METRICS.find((m) => m.id === id);

const state = { metric: 'ratio_o65', areas: null, town: null, breaks: {}, selected: null };

/* ---------- 数値の見せ方 ---------- */

const fmt = (v, digits = 0) =>
  v === null || v === undefined
    ? '—'
    : v.toLocaleString('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits });

const signed = (v, digits = 1) =>
  v === null || v === undefined ? '—' : (v > 0 ? '+' : '') + fmt(v, digits);

function display(metric, v) {
  if (v === null || v === undefined) return '—';
  return (metric.suffixSign ? signed(v, metric.digits) : fmt(v, metric.digits)) + metric.unit;
}

/* ---------- 色の割り当て ---------- */

// 値を5階級に分ける。通常は分位数、増減系は0を中央にした対称区分。
function computeBreaks(metric, features) {
  const vals = features
    .map((f) => f.properties[metric.id])
    .filter((v) => v !== null && v !== undefined)
    .sort((a, b) => a - b);
  if (!vals.length) return [];

  if (metric.diverging) {
    // 増減系は0を境に対称にする。最大値で割ると外れ値（字伊平の+377%など）に
    // 全体が引きずられるので、絶対値の分位で外側の境界を決める。
    const abs = vals.map(Math.abs).sort((a, b) => a - b);
    const at = (p) => abs[Math.min(abs.length - 1, Math.floor(p * abs.length))];
    const inner = Math.max(at(0.55), 0.1);
    const outer = Math.max(at(0.88), inner * 2);
    return [-outer, -inner, inner, outer];
  }
  const q = (p) => vals[Math.min(vals.length - 1, Math.floor(p * vals.length))];
  return [q(0.2), q(0.4), q(0.6), q(0.8)];
}

function colorFor(metric, breaks, v) {
  if (v === null || v === undefined) return '#dcdad4';
  const pal = PALETTES[metric.palette];
  let i = 0;
  while (i < breaks.length && v >= breaks[i]) i++;
  return pal[i];
}

/* ---------- 地図 ---------- */

const map = new maplibregl.Map({
  container: 'map',
  style: {
    version: 8,
    sources: {
      gsi: {
        type: 'raster',
        tiles: ['https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png'],
        tileSize: 256,
        maxzoom: 18,
        attribution:
          '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noopener">国土地理院</a>',
      },
    },
    layers: [
      { id: 'bg', type: 'background', paint: { 'background-color': '#eef0ef' } },
      { id: 'gsi', type: 'raster', source: 'gsi', paint: { 'raster-opacity': 0.82 } },
    ],
  },
  center: [127.7644, 26.3197],
  zoom: 13.1,
  minZoom: 10,
  maxZoom: 17,
  attributionControl: { compact: false },
});

window.__map = map; // デバッグ用
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: 'metric' }), 'bottom-left');
map.on('error', (e) => console.error('[map]', e && e.error ? e.error.message : e));

/* ---------- 起動 ---------- */

// 地図の準備とデータ取得のどちらが先に終わっても取りこぼさないよう、両方を待ち合わせる。
const mapReady = new Promise((resolve) => {
  if (map.isStyleLoaded()) resolve();
  else map.on('load', resolve);
});

Promise.all([
  fetch('data/chatan_areas.geojson').then((r) => r.json()),
  fetch('data/chatan_town.json').then((r) => r.json()),
  mapReady,
])
  .then(([areas, town]) => {
    state.areas = areas;
    state.town = town;
    for (const m of ALL_METRICS) state.breaks[m.id] = computeBreaks(m, areas.features);

    renderTown();
    renderMetricButtons();
    initLayers();
  })
  .catch((err) => {
    console.error('[init]', err);
    document.getElementById('metric-desc').textContent =
      'データの読み込みに失敗しました。時間をおいて再読み込みしてください。';
  });

function initLayers() {
  map.addSource('areas', { type: 'geojson', data: state.areas, promoteId: 'key' });

  map.addLayer({
    id: 'areas-fill',
    type: 'fill',
    source: 'areas',
    paint: {
      'fill-color': ['coalesce', ['get', '_color'], '#dcdad4'],
      'fill-opacity': [
        'case',
        ['boolean', ['feature-state', 'hover'], false], 0.92,
        0.74,
      ],
    },
  });

  map.addLayer({
    id: 'areas-line',
    type: 'line',
    source: 'areas',
    paint: {
      'line-color': '#ffffff',
      'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 3.2, 1.1],
      'line-opacity': 0.9,
    },
  });

  map.addLayer({
    id: 'areas-outline-sel',
    type: 'line',
    source: 'areas',
    paint: {
      'line-color': '#17242c',
      'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 1.6, 0],
    },
  });

  applyMetric();
  addLabels();
  bindInteractions();
  watchSize();
}

/* コンテナのサイズが後から決まる場合があるので、変化を見て resize する。 */
function watchSize() {
  const wrap = document.getElementById('map-wrap');
  map.resize();
  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => map.resize()).observe(wrap);
  }
  window.addEventListener('orientationchange', () => setTimeout(() => map.resize(), 200));
  // 初期表示は町域がちょうど収まる位置に合わせる
  map.fitBounds(bounds(state.areas), { padding: 36, duration: 0 });
}

function bounds(fc) {
  let minX = 180, minY = 90, maxX = -180, maxY = -90;
  const walk = (c) => {
    if (typeof c[0] === 'number') {
      minX = Math.min(minX, c[0]); maxX = Math.max(maxX, c[0]);
      minY = Math.min(minY, c[1]); maxY = Math.max(maxY, c[1]);
    } else c.forEach(walk);
  };
  fc.features.forEach((f) => walk(f.geometry.coordinates));
  return [[minX, minY], [maxX, maxY]];
}

/* 区域名のラベル。フォント配信に依存しないよう HTML マーカーで置く。 */
function addLabels() {
  for (const f of state.areas.features) {
    if (!f.properties.pop_2020) continue;
    const el = document.createElement('div');
    el.className = 'area-label';
    el.textContent = f.properties.name;
    new maplibregl.Marker({ element: el, anchor: 'center' })
      .setLngLat(centroid(f.geometry))
      .addTo(map);
  }
}

// ポリゴンの重心。面積で重み付けして、飛び地があっても本体側に寄せる。
function centroid(geom) {
  const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
  let cx = 0, cy = 0, total = 0;
  for (const poly of polys) {
    const ring = poly[0];
    let a = 0, x = 0, y = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x1, y1] = ring[i], [x2, y2] = ring[i + 1];
      const cross = x1 * y2 - x2 * y1;
      a += cross;
      x += (x1 + x2) * cross;
      y += (y1 + y2) * cross;
    }
    a /= 2;
    if (!a) continue;
    cx += x / (6 * a) * Math.abs(a);
    cy += y / (6 * a) * Math.abs(a);
    total += Math.abs(a);
  }
  return total ? [cx / total, cy / total] : polys[0][0][0];
}

/* ---------- 指標の切り替え ---------- */

function applyMetric() {
  const metric = byId(state.metric);
  const breaks = state.breaks[metric.id];
  // 色は地物のプロパティに書き込んで setData で流す。
  // feature-state はソース読み込み完了前だと取りこぼすため、塗りには使わない。
  for (const f of state.areas.features) {
    f.properties._color = colorFor(metric, breaks, f.properties[metric.id]);
  }
  const src = map.getSource('areas');
  if (src) src.setData(state.areas);
  document.getElementById('metric-desc').textContent = metric.desc;
  renderLegend(metric, breaks);
  renderRanking(metric);
  if (state.selected) renderDetail(state.selected);
}

function renderMetricButtons() {
  const wrap = document.getElementById('metrics');
  wrap.innerHTML = '';
  for (const g of METRICS) {
    const lab = document.createElement('div');
    lab.className = 'group-label';
    lab.textContent = g.group;
    wrap.appendChild(lab);
    for (const m of g.items) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = m.label;
      b.setAttribute('aria-pressed', String(m.id === state.metric));
      b.onclick = () => {
        state.metric = m.id;
        wrap.querySelectorAll('button').forEach((x) =>
          x.setAttribute('aria-pressed', String(x.textContent === m.label))
        );
        applyMetric();
      };
      wrap.appendChild(b);
    }
  }
}

function renderLegend(metric, breaks) {
  const pal = PALETTES[metric.palette];
  const body = document.getElementById('legend-body');
  const rows = [];
  for (let i = 0; i < pal.length; i++) {
    const lo = i === 0 ? null : breaks[i - 1];
    const hi = i === pal.length - 1 ? null : breaks[i];
    let text;
    if (lo === null) text = `${display(metric, hi)} 未満`;
    else if (hi === null) text = `${display(metric, lo)} 以上`;
    else text = `${display(metric, lo)} 〜 ${display(metric, hi)}`;
    rows.push(
      `<div class="legend-row"><span class="swatch" style="background:${pal[i]}"></span><span class="lbl">${text}</span></div>`
    );
  }
  rows.push(
    '<div class="legend-row"><span class="swatch" style="background:#dcdad4"></span><span class="lbl">データなし（居住者なし等）</span></div>'
  );
  body.innerHTML = rows.join('');
}

function renderRanking(metric) {
  const list = state.areas.features
    .filter((f) => f.properties[metric.id] !== null && f.properties[metric.id] !== undefined)
    .sort((a, b) => b.properties[metric.id] - a.properties[metric.id])
    .slice(0, 8);
  const max = Math.max(...list.map((f) => Math.abs(f.properties[metric.id])), 1);
  const pal = PALETTES[metric.palette];
  const body = document.getElementById('ranking-body');
  body.innerHTML = list
    .map((f) => {
      const v = f.properties[metric.id];
      const w = Math.round((Math.abs(v) / max) * 100);
      return `<li data-key="${f.properties.key}">
        <span class="nm">${f.properties.label}</span>
        <span class="bar"><i style="width:${w}%;background:${pal[4]}"></i></span>
        <span class="vl">${display(metric, v)}</span>
      </li>`;
    })
    .join('');
  body.querySelectorAll('li').forEach((li) => {
    li.onclick = () => {
      const f = state.areas.features.find((x) => x.properties.key === li.dataset.key);
      if (f) select(f);
    };
  });
}

/* ---------- 町全体 ---------- */

function renderTown() {
  const t = state.town;
  const cells = [
    ['人口', fmt(t.pop_2020), '人', `${signed(t.pop_change, 0)}人 (2015年比)`, t.pop_change < 0 ? 'down' : 'up'],
    ['世帯数', fmt(t.households_2020), '世帯', `1世帯 ${t.hh_avg_members}人`, ''],
    ['面積', fmt(t.area_km2, 2), 'km²', `${fmt(Math.round(t.pop_2020 / t.area_km2))}人/km²`, ''],
    ['高齢化率', fmt(t.ratio_o65, 1), '%', `${signed(t.aging_change_pt)}pt (2015年比)`, 'up'],
    ['年少人口率', fmt(t.ratio_u15, 1), '%', `15歳未満 ${fmt(t.u15_2020)}人`, ''],
    ['75歳以上', fmt(t.ratio_o75, 1), '%', `${fmt(t.o75_2020)}人`, ''],
    ['単身世帯', fmt(t.hh_single_ratio, 1), '%', '一般世帯に占める割合', ''],
    ['高齢者のいる世帯', fmt(t.hh_with_o65_ratio, 1), '%', '65歳以上の世帯員あり', ''],
    ['子どものいる世帯', fmt(t.hh_with_u18_ratio, 1), '%', '18歳未満の世帯員あり', ''],
  ];
  document.getElementById('town-grid').innerHTML = cells
    .map(
      ([k, v, u, d, cls]) => `<div class="cell">
        <span class="k">${k}</span>
        <span class="v">${v}<span class="u">${u}</span></span>
        <span class="d ${cls}">${d}</span>
      </div>`
    )
    .join('');
  document.getElementById('town-note').textContent =
    `町内を ${t.areas} の区域（字・丁目）に分けて表示しています。`;
}

/* ---------- 詳細 ---------- */

function renderDetail(f) {
  const p = f.properties;
  const card = document.getElementById('detail');
  card.classList.remove('is-empty');
  const t = state.town;

  const row = (k, v, note) =>
    `<div class="row"><span class="k">${k}</span><span class="v">${v}${note ? `<small>${note}</small>` : ''}</span></div>`;
  const sec = (s) => `<div class="sec">${s}</div>`;
  const vs = (v, base, unit, digits = 1) =>
    v === null ? '' : `町平均 ${fmt(base, digits)}${unit}`;

  const html = [
    `<h3>${p.label}</h3>`,
    `<p class="meta">面積 ${fmt(p.area_km2, 2)} km²　/　区域コード ${p.key}</p>`,
    p.pop_2020 !== null && p.pop_2020 < 100
      ? '<p class="caution">人口が少ない区域です。数人の増減で割合が大きく動くため、比率はそのまま比べないでください。</p>'
      : '',
    '<div class="rows">',
    sec('人口'),
    row('人口 (2020年)', `${fmt(p.pop_2020)} 人`),
    row('人口密度', p.pop_density === null ? '—' : `${fmt(p.pop_density)} 人/km²`),
    row('2015年', `${fmt(p.pop_2015)} 人`),
    row('増減', p.pop_change === null ? '—' : `${signed(p.pop_change, 0)} 人`,
        p.pop_change_ratio === null ? '' : `${signed(p.pop_change_ratio)}%`),
    row('男 / 女', `${fmt(p.male_2020)} / ${fmt(p.female_2020)} 人`),
    sec('年齢構成'),
    row('15歳未満', p.ratio_u15 === null ? '—' : `${fmt(p.ratio_u15, 1)}%`,
        p.u15_2020 === null ? '' : `${fmt(p.u15_2020)}人`),
    row('15〜64歳', p.ratio_w15_64 === null ? '—' : `${fmt(p.ratio_w15_64, 1)}%`,
        p.w15_64_2020 === null ? '' : `${fmt(p.w15_64_2020)}人`),
    row('65歳以上', p.ratio_o65 === null ? '—' : `${fmt(p.ratio_o65, 1)}%`,
        p.o65_2020 === null ? '' : `${fmt(p.o65_2020)}人`),
    row('うち75歳以上', p.ratio_o75 === null ? '—' : `${fmt(p.ratio_o75, 1)}%`,
        p.o75_2020 === null ? '' : `${fmt(p.o75_2020)}人`),
    row('高齢化率の変化', p.aging_change_pt === null ? '—' : `${signed(p.aging_change_pt)} pt`,
        p.ratio_o65_2015 === null ? '' : `2015年 ${fmt(p.ratio_o65_2015, 1)}%`),
    sec('世帯'),
    row('世帯数', `${fmt(p.households_2020)} 世帯`),
    row('平均世帯人員', p.hh_avg_members === null ? '—' : `${fmt(p.hh_avg_members, 2)} 人`,
        vs(p.hh_avg_members, t.hh_avg_members, '人', 2)),
    row('単身世帯', p.hh_single_ratio === null ? '—' : `${fmt(p.hh_single_ratio, 1)}%`,
        vs(p.hh_single_ratio, t.hh_single_ratio, '%')),
    row('高齢者のいる世帯', p.hh_with_o65_ratio === null ? '—' : `${fmt(p.hh_with_o65_ratio, 1)}%`,
        vs(p.hh_with_o65_ratio, t.hh_with_o65_ratio, '%')),
    row('子どものいる世帯', p.hh_with_u18_ratio === null ? '—' : `${fmt(p.hh_with_u18_ratio, 1)}%`,
        vs(p.hh_with_u18_ratio, t.hh_with_u18_ratio, '%')),
    row('6歳未満のいる世帯', p.hh_with_u6_ratio === null ? '—' : `${fmt(p.hh_with_u6_ratio, 1)}%`,
        vs(p.hh_with_u6_ratio, t.hh_with_u6_ratio, '%')),
    '</div>',
  ].join('');

  document.getElementById('detail-body').innerHTML = html;
}

/* ---------- 操作 ---------- */

function select(f) {
  if (state.selected) {
    map.setFeatureState({ source: 'areas', id: state.selected.properties.key }, { selected: false });
  }
  state.selected = f;
  map.setFeatureState({ source: 'areas', id: f.properties.key }, { selected: true });
  renderDetail(f);
  document.getElementById('detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function bindInteractions() {
  const tip = document.getElementById('tooltip');
  let hovered = null;

  map.on('mousemove', 'areas-fill', (e) => {
    const f = e.features[0];
    if (hovered !== null && hovered !== f.properties.key) {
      map.setFeatureState({ source: 'areas', id: hovered }, { hover: false });
    }
    hovered = f.properties.key;
    map.setFeatureState({ source: 'areas', id: hovered }, { hover: true });
    map.getCanvas().style.cursor = 'pointer';

    const metric = byId(state.metric);
    tip.hidden = false;
    tip.innerHTML =
      `<span class="t-name">${f.properties.label}</span>` +
      `<span class="t-val">${metric.label} ${display(metric, f.properties[metric.id])}</span>`;
    tip.style.left = `${e.point.x}px`;
    tip.style.top = `${e.point.y}px`;
  });

  map.on('mouseleave', 'areas-fill', () => {
    if (hovered !== null) map.setFeatureState({ source: 'areas', id: hovered }, { hover: false });
    hovered = null;
    map.getCanvas().style.cursor = '';
    tip.hidden = true;
  });

  map.on('click', 'areas-fill', (e) => {
    const key = e.features[0].properties.key;
    const f = state.areas.features.find((x) => x.properties.key === key);
    if (f) select(f);
  });

  const toggle = document.getElementById('panel-toggle');
  toggle.onclick = () => {
    const panel = document.getElementById('panel');
    panel.classList.toggle('is-collapsed');
    toggle.textContent = panel.classList.contains('is-collapsed') ? '指標' : '地図を広く';
    map.resize();
  };
}
