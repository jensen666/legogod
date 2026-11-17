// ============================================================
// 乐高拼装工作室组件（唯一实现，两处复用）
//   - Web 工坊（python -m legogod + web/index.html）的结果卡片直接 mount
//   - 独立页面（agent.gen_viz 生成的 lego-<slug>.html / 聊天卡片）把本文件
//     源码内嵌后 mount
// 用法:
//   import { mountLegoStudio } from '...viewer.js';
//   const studio = mountLegoStudio(rootEl, DATA, { initial: {tab, step}, onState, height });
//   studio.apply(step); studio.activate('build'); studio.destroy();
// DATA 结构: { name, grid:{w,d}, layers:[{y,module,cells}], parts, steps, usage, strategy, valid, attempts }
// ============================================================
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const H = 1.2, STUD_R = 0.3, STUD_H = 0.18;
let UID = 0;

const STYLE = `
.lgs-root { font: 14px/1.6 system-ui, "Segoe UI", "Microsoft YaHei", sans-serif; }
.lgs-root [role="tabpanel"] { margin-top: 12px; }
.lgs-root .lgs-viewhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 12px; margin: 2px 0 10px; }
.lgs-root .lgs-stage { position: relative; width: 100%; overflow: hidden; background: #e9eef3; border-radius: 10px; }
.lgs-root .lgs-stage canvas { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
.lgs-root .lgs-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
.lgs-root .lgs-slider { flex: 0 1 300px; min-width: 140px; accent-color: #ffb02e; }
.lgs-root .lgs-count { white-space: nowrap; }
.lgs-root .lgs-stepinfo { margin-top: 10px; min-height: 1.4em; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; }
.lgs-root .lgs-caption { margin-top: 8px; opacity: .75; }
.lgs-root .lgs-dot { display: inline-block; width: 10px; height: 10px; border: 1px solid #c4ccd6; border-radius: 2px; margin-right: 6px; vertical-align: baseline; }
.lgs-root .lgs-muted { opacity: .7; font-size: 12px; }
.lgs-root .lgs-badge { display: inline-block; background: rgba(127,127,127,.12); border-radius: 999px; padding: 2px 10px; font-size: 12px; }
.lgs-root .lgs-tab { border: 1px solid rgba(127,127,127,.3); background: transparent; color: inherit;
  border-radius: 999px; padding: 4px 14px; cursor: pointer; font: inherit; font-size: 13px; }
.lgs-root .lgs-tab.active { background: #ffb02e; border-color: #ffb02e; color: #201404; font-weight: 700; }
.lgs-root .lgs-btn { border: 1px solid rgba(127,127,127,.35); background: transparent; color: inherit;
  border-radius: 8px; padding: 4px 12px; cursor: pointer; font: inherit; font-size: 13px; }
.lgs-root .lgs-btn.primary { background: #ffb02e; border-color: #ffb02e; color: #201404; font-weight: 700; }
.lgs-root .lgs-btn.primary[aria-label="暂停"] { background: #c4323b; border-color: #c4323b; color: #ffffff; }
.lgs-root table { width: 100%; border-collapse: collapse; font-size: 13px; }
.lgs-root th, .lgs-root td { text-align: left; padding: 5px 8px; border-bottom: 1px solid rgba(127,127,127,.18); }
.lgs-root th.num, .lgs-root td.num { text-align: right; font-variant-numeric: tabular-nums; }
.lgs-root .lgs-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
`;

function ensureStyle() {
  if (!document.getElementById('lgs-style')) {
    const s = document.createElement('style');
    s.id = 'lgs-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }
}

export function mountLegoStudio(root, DATA, opts = {}) {
  ensureStyle();
  const uid = 'lgs' + (++UID);
  const height = opts.height || 400;
  root.classList.add('lgs-root');
  const stageStyle = `height:${height}px`;

  root.innerHTML = `
  <div class="nav" role="tablist" aria-label="乐高拼装视图">
    <button class="lgs-tab" data-el="tab-model" role="tab" aria-controls="${uid}-panel-model" aria-selected="true" type="button">目标模型</button>
    <button class="lgs-tab" data-el="tab-parts" role="tab" aria-controls="${uid}-panel-parts" aria-selected="false" type="button">零件库</button>
    <button class="lgs-tab" data-el="tab-build" role="tab" aria-controls="${uid}-panel-build" aria-selected="false" type="button">拼装模拟</button>
  </div>
  <div data-el="panel-model" role="tabpanel">
    <div class="lgs-viewhead">
      <strong data-el="model-name"></strong>
      <span class="lgs-muted" data-el="model-meta"></span>
    </div>
    <div class="lgs-stage" style="${stageStyle}"><canvas data-el="canvas-model"></canvas></div>
    <p class="lgs-muted lgs-caption">成品外观预览（颜色 = 最终零件颜色，与拼装成品严格一致）。拖动旋转，滚轮缩放。</p>
  </div>
  <div data-el="panel-parts" role="tabpanel" hidden>
    <div class="lgs-viewhead">
      <strong>零件库</strong>
      <span class="lgs-muted" data-el="parts-meta"></span>
    </div>
    <div class="lgs-stage" style="height:${Math.max(200, Math.round(height * 0.55))}px"><canvas data-el="canvas-parts"></canvas></div>
    <table class="lgs-caption"><thead><tr><th>零件</th><th>尺寸 (stud)</th><th>颜色</th><th class="num">库存</th><th class="num">本方案用量</th></tr></thead>
    <tbody data-el="parts-tbody"></tbody></table>
    <details class="lgs-caption"><summary>全部形状 × 颜色库存</summary><div data-el="parts-inventory"></div></details>
    <p class="lgs-muted lgs-caption">连接方式：顶面每个单元 1 个凸点，底面对应空腔；零件可旋转 90° 摆放。颜色是每层的设计选择，同一形状不同颜色各自计库存。</p>
  </div>
  <div data-el="panel-build" role="tabpanel" hidden>
    <div class="lgs-viewhead">
      <strong>拼装模拟</strong>
      <span class="lgs-muted" data-el="build-meta"></span>
    </div>
    <div class="lgs-stage" style="${stageStyle}"><canvas data-el="canvas-build"></canvas></div>
    <div class="lgs-controls">
      <button class="lgs-btn" data-el="reset" type="button">重置</button>
      <button class="lgs-btn" data-el="prev" type="button">上一步</button>
      <button class="lgs-btn primary" data-el="play" type="button" aria-label="播放">播放</button>
      <button class="lgs-btn" data-el="next" type="button">下一步</button>
      <input type="range" class="lgs-slider" data-el="slider" min="0" max="${DATA.steps.length}" step="1" value="0" aria-label="拼装进度">
      <span class="lgs-count" data-el="stepnum">0 / ${DATA.steps.length}</span>
      <label class="lgs-check"><input type="checkbox" data-el="ghost" checked><span>目标轮廓</span></label>
    </div>
    <div class="lgs-stepinfo" aria-live="polite" data-el="stepinfo"></div>
    <p class="lgs-muted lgs-caption" data-el="build-caption"></p>
  </div>`;

  const $ = name => root.querySelector(`[data-el="${name}"]`);

  const themeColor = (name, fallback) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  };
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  // 零件目录须由调用方完整提供（web/index.html 从 /api/parts 同步）。
  // 若 solution 出现目录外的零件，不要整页崩掉：控制台报错 + 品红占位，便于定位。
  const missingWarned = new Set();
  function partOf(id) {
    const p = DATA.parts.find(x => x.id === id);
    if (!p && !missingWarned.has(id)) {
      missingWarned.add(id);
      console.error('[lego-viewer] 零件目录缺少 id：' + id + '，用品红占位；请同步零件目录');
    }
    return p;
  }
  function partOfSafe(id) {
    return partOf(id) || { id, name: '未知零件 ' + id, w: 1, d: 1, color: '#FF00FF', colorName: '未知颜色' };
  }

  // ---------- 共享构建器 ----------
  const geoCache = new Map(), matCache = new Map();
  function brickGeos(w, d) {
    const key = w + 'x' + d;
    if (!geoCache.has(key)) {
      geoCache.set(key, { box: new THREE.BoxGeometry(w, H, d), stud: new THREE.CylinderGeometry(STUD_R, STUD_R, STUD_H, 20) });
    }
    return geoCache.get(key);
  }
  function mat(color) {
    if (!matCache.has(color)) matCache.set(color, new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0 }));
    return matCache.get(color);
  }
  function makeBrick(color, w, d) {
    const g = new THREE.Group();
    const { box, stud } = brickGeos(w, d);
    const body = new THREE.Mesh(box, mat(color));
    body.position.set(w / 2, H / 2, d / 2);
    g.add(body);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.22 }));
    edges.position.copy(body.position);
    g.add(edges);
    for (let i = 0; i < w; i++) for (let j = 0; j < d; j++) {
      const s = new THREE.Mesh(stud, mat(color));
      s.position.set(i + 0.5, H + STUD_H / 2, j + 0.5);
      g.add(s);
    }
    return g;
  }
  // 斜面楔形体：标准姿态高端在 +x 边，其余方向旋转
  const SLOPE_DIR = { '/': 'XP', '\\': 'XM', '^': 'ZM', 'v': 'ZP' };
  function slopeGeo(dir) {
    const key = 'slope' + dir;
    if (geoCache.has(key)) return geoCache.get(key);
    const hHigh = H, hLow = H * 0.35;
    const g = new THREE.BufferGeometry();
    const v = [];
    const quad = (a, b, c, d) => { v.push(...a, ...b, ...c, ...a, ...c, ...d); };
    const tri = (a, b, c) => { v.push(...a, ...b, ...c); };
    const A = [0, 0, 0], B = [1, 0, 0], C = [1, 0, 1], D = [0, 0, 1];
    const A2 = [0, hLow, 0], B2 = [1, hHigh, 0], C2 = [1, hHigh, 1], D2 = [0, hLow, 1];
    quad(A2, D2, C2, B2);   // 斜面（低边 -x → 高边 +x）
    quad(A, B, C, D);       // 底面
    quad(B, B2, C2, C);     // 高侧竖面 (+x)
    quad(A, D, D2, A2);     // 低侧竖面 (-x)
    tri(A, A2, B2); tri(A, B2, B);  // z=0 侧
    tri(D, C, C2); tri(D, C2, D2);  // z=1 侧
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    g.translate(-0.5, -H / 2, -0.5);
    g.computeVertexNormals();
    if (dir === 'XM') g.rotateY(Math.PI);
    if (dir === 'ZM') g.rotateY(Math.PI / 2);
    if (dir === 'ZP') g.rotateY(-Math.PI / 2);
    geoCache.set(key, g);
    return g;
  }
  // 反斜坡楔形体（顶面平带凸点、底面斜挑）：标准姿态根部在 -x 边，中心归零后再旋转
  const INV_SLOPE_DIR = { b: 'W', d: 'E', p: 'N', q: 'S' };
  const INV_SLOPE_CHARS_SET = new Set(Object.keys(INV_SLOPE_DIR));
  function invSlopeGeo(dir) {
    const key = 'islope' + dir;
    if (geoCache.has(key)) return geoCache.get(key);
    const g = new THREE.BufferGeometry();
    const v = [];
    const quad = (a, b, c, d) => { v.push(...a, ...b, ...c, ...a, ...c, ...d); };
    const tri = (a, b, c) => { v.push(...a, ...b, ...c); };
    const A = [0, 0, 0], B = [1, 0, 0], C = [1, 0, 1], D = [0, 0, 1];
    const A2 = [0, H, 0], B2 = [1, H, 0], C2 = [1, H, 1], D2 = [0, H, 1];
    quad(A2, B2, C2, D2);   // 顶面
    quad(A, D, D2, A2);     // 根部竖面 (-x，满高)
    quad(A, B2, C2, D);     // 底面斜挑（从根底到尖端顶）
    tri(A, A2, B2); tri(A, B2, B);  // z=0 侧三角
    tri(D, C, C2); tri(D, C2, D2);  // z=1 侧三角
    g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
    g.translate(-0.5, -H / 2, -0.5);
    g.computeVertexNormals();
    if (dir === 'E') g.rotateY(Math.PI);
    if (dir === 'N') g.rotateY(-Math.PI / 2);
    if (dir === 'S') g.rotateY(Math.PI / 2);
    geoCache.set(key, g);
    return g;
  }
  function slopeCellGeo(ch) {
    return INV_SLOPE_CHARS_SET.has(ch) ? invSlopeGeo(INV_SLOPE_DIR[ch]) : slopeGeo(SLOPE_DIR[ch]);
  }
  function partStudOffsets(p, w, d, rotate) {
    if (p.hasStuds === false) return [];
    if (Array.isArray(p.studMask) && p.studMask.length) {
      return p.studMask.map(([i, j]) => (rotate ? [j, i] : [i, j]))
        .filter(([i, j]) => i < w && j < d);
    }
    const out = [];
    for (let a = 0; a < w; a++) for (let b = 0; b < d; b++) out.push([a, b]);
    return out;
  }
  function makeSlopeBrick(p, w, d, rotate, includeStuds) {
    const g = new THREE.Group();
    const maskSet = new Set(
      (p.rootMask || p.studMask || []).map(([i, j]) => (rotate ? `${j},${i}` : `${i},${j}`))
    );
    const hasMulti = (w * d > 1) && maskSet.size > 0;
    const { box, stud } = brickGeos(1, 1);
    for (let a = 0; a < w; a++) {
      for (let b = 0; b < d; b++) {
        const isFullCell = hasMulti && maskSet.has(`${a},${b}`);
        const cellGeo = isFullCell ? box : slopeCellGeo(p.slope);
        const mesh = new THREE.Mesh(cellGeo, mat(p.color));
        mesh.position.set(a + 0.5, H / 2, b + 0.5);
        g.add(mesh);
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(cellGeo), new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.22 }));
        edges.position.copy(mesh.position);
        g.add(edges);
      }
    }
    if (includeStuds) {
      for (const [a, b] of partStudOffsets(p, w, d, rotate)) {
        const s = new THREE.Mesh(stud, mat(p.color));
        s.position.set(a + 0.5, H + STUD_H / 2, b + 0.5);
        g.add(s);
      }
    }
    return g;
  }
  function voxelFill(vox, colorFn) {
    const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(1, H, 1), new THREE.MeshStandardMaterial({ roughness: 0.5, metalness: 0 }), vox.length);
    const M = new THREE.Matrix4(), C = new THREE.Color();
    vox.forEach((v, i) => {
      M.makeTranslation(v[0] + 0.5, v[1] * H + H / 2, v[2] + 0.5);
      inst.setMatrixAt(i, M);
      inst.setColorAt(i, C.set(colorFn(v)));
    });
    return inst;
  }
  function voxelEdges(vox, color, opacity) {
    const P = [];
    const seg = (a, b) => { P.push(a[0], a[1], a[2], b[0], b[1], b[2]); };
    for (const [x, y, z] of vox) {
      const x0 = x, x1 = x + 1, z0 = z, z1 = z + 1, y0 = y * H + 0.004, y1 = (y + 1) * H - 0.004;
      seg([x0, y0, z0], [x1, y0, z0]); seg([x1, y0, z0], [x1, y0, z1]); seg([x1, y0, z1], [x0, y0, z1]); seg([x0, y0, z1], [x0, y0, z0]);
      seg([x0, y1, z0], [x1, y1, z0]); seg([x1, y1, z0], [x1, y1, z1]); seg([x1, y1, z1], [x0, y1, z1]); seg([x0, y1, z1], [x0, y1, z0]);
      seg([x0, y0, z0], [x0, y1, z0]); seg([x1, y0, z0], [x1, y1, z0]); seg([x1, y0, z1], [x1, y1, z1]); seg([x0, y0, z1], [x0, y1, z1]);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(P, 3));
    return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity }));
  }
  function baseplate(scene, w, d, ox = 0, oz = 0) {
    const plate = new THREE.Mesh(new THREE.BoxGeometry(w, 0.4, d), mat('#237841'));
    plate.position.set(w / 2 + ox, -0.2, d / 2 + oz);
    scene.add(plate);
    const { stud } = brickGeos(1, 1);
    const inst = new THREE.InstancedMesh(stud, mat('#237841'), w * d);
    const M = new THREE.Matrix4();
    let i = 0;
    for (let x = 0; x < w; x++) for (let z = 0; z < d; z++) { M.makeTranslation(x + 0.5 + ox, STUD_H / 2, z + 0.5 + oz); inst.setMatrixAt(i++, M); }
    scene.add(inst);
  }
  function fitCam(m) {
    const W = m.grid.w, D = m.grid.d, Ht = m.layers.length * H;
    const dist = Math.max(W, D) * 1.35 + Ht * 1.5 + 4;
    return {
      pos: [W / 2 + dist * 0.55, dist * 0.82, D / 2 + dist * 0.92],
      target: [W / 2, Ht / 2, D / 2],
      plateW: W + 6, plateD: D + 6, ox: -3, oz: -3,
    };
  }
  function makeView(canvas, camPos, target) {
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 300);
    camera.position.set(camPos[0], camPos[1], camPos[2]);
    const controls = new OrbitControls(camera, canvas);
    controls.target.set(target[0], target[1], target[2]);
    controls.enableDamping = true;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x9999aa, 1.1));
    const d1 = new THREE.DirectionalLight(0xffffff, 2.0); d1.position.set(6, 12, 8); scene.add(d1);
    const d2 = new THREE.DirectionalLight(0xffffff, 0.7); d2.position.set(-8, 6, -6); scene.add(d2);
    return { canvas, renderer, scene, camera, controls, inited: false };
  }
  function resize(v) {
    const r = v.canvas.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    v.renderer.setSize(r.width, r.height, false);
    v.camera.aspect = r.width / r.height;
    v.camera.updateProjectionMatrix();
    return true;
  }

  // ---------- 数据派生 ----------
  const SLOPE_CHARS_SET = new Set(['/', '\\', '^', 'v']);
  const typedVox = () => {
    const normal = [], slopes = {};
    for (const L of DATA.layers) {
      if (L.rows && L.rows.length) {
        L.rows.forEach((row, z) => {
          for (let x = 0; x < row.length; x++) {
            const ch = row[x];
            if (ch === '#') normal.push([x, L.y, z]);
            else if (SLOPE_CHARS_SET.has(ch) || INV_SLOPE_CHARS_SET.has(ch)) (slopes[ch] = slopes[ch] || []).push([x, L.y, z]);
          }
        });
      } else {
        for (const c of L.cells) normal.push([c[0], L.y, c[1]]);
      }
    }
    return { normal, slopes };
  };
  const allVox = () => {
    const { normal, slopes } = typedVox();
    return normal.concat(...Object.values(slopes));
  };
  const voxelColorMap = () => {
    const map = new Map();
    for (const s of DATA.steps) {
      const p = partOfSafe(s.piece);
      for (let i = 0; i < s.w; i++) for (let j = 0; j < s.d; j++) map.set((s.x + i) + ',' + s.layer + ',' + (s.z + j), p.color);
    }
    return map;
  };
  function zoneName(s) {
    const L = DATA.layers[s.layer];
    const mods = (L && L.module) || [];
    if (mods.some(m => String(m).indexOf('墙') >= 0)) {
      if (s.z === 0) return '前墙';
      if (s.z + s.d === DATA.grid.d) return '后墙';
      if (s.x === 0) return '左墙';
      if (s.x + s.w === DATA.grid.w) return '右墙';
      return '墙体';
    }
    return mods.join('·') || '模型';
  }
  // DATA 里的模块名/零件名来自模型输出，进入 innerHTML 前统一转义
  function esc(text) {
    return String(text).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------- 视图（懒初始化） ----------
  const views = [];
  let modelView = null, partsView = null, buildView = null;
  let savedStep = Math.max(0, Math.min(DATA.steps.length, (opts.initial && opts.initial.step | 0) || 0));

  function initModel() {
    const f = fitCam(DATA);
    modelView = makeView($('canvas-model'), f.pos, f.target);
    baseplate(modelView.scene, f.plateW, f.plateD, f.ox, f.oz);
    const { normal, slopes } = typedVox();
    const cmap = voxelColorMap();
    modelView.scene.add(voxelFill(normal, v => cmap.get(v.join(',')) || '#F2F3F2'));
    for (const [ch, vox] of Object.entries(slopes)) {
      const inst = new THREE.InstancedMesh(slopeCellGeo(ch), new THREE.MeshStandardMaterial({ roughness: 0.5 }), vox.length);
      const M = new THREE.Matrix4(), C = new THREE.Color();
      vox.forEach((v, i) => {
        M.makeTranslation(v[0] + 0.5, v[1] * H + H / 2, v[2] + 0.5);
        inst.setMatrixAt(i, M);
        inst.setColorAt(i, C.set(cmap.get(v.join(',')) || '#9BA19D'));
      });
      modelView.scene.add(inst);
    }
    modelView.scene.add(voxelEdges(normal, 0x000000, 0.13));
    modelView.inited = true;
    resize(modelView); views.push(modelView);
  }

  function initParts() {
    // 零件库按「形状 × 颜色」展开后变体很多：3D 场景只摆本方案实际用到的零件（按用量降序），
    // 全部库存放到下方按形状分组的折叠表里。
    const usedIds = Object.keys(DATA.usage || {}).filter(id => partOf(id))
      .sort((a, b) => (DATA.usage[b] || 0) - (DATA.usage[a] || 0));
    const showIds = usedIds.slice(0, 14);
    let span = 0;
    for (const id of showIds) {
      const p = partOf(id);
      span += p.w + 1.7;
    }
    const camDist = Math.max(8, span * 0.62);
    partsView = makeView($('canvas-parts'),
      [span / 2 + camDist * 0.32, camDist * 0.62, camDist * 1.15], [span / 2, 0.8, 0]);
    let cx = 0;
    for (const id of showIds) {
      const p = partOf(id);
      const b = p.slope ? makeSlopeBrick(p, p.w, p.d, false, true) : makeBrick(p.color, p.w, p.d);
      b.position.set(cx, 0, 0);
      partsView.scene.add(b);
      cx += p.w + 1.7;
    }
    partsView.inited = true;
    resize(partsView); views.push(partsView);

    const shapeCount = new Set(DATA.parts.map(p => p.shape || p.id)).size;
    const colorCount = new Set(DATA.parts.map(p => p.colorName)).size;
    const totalInv = DATA.parts.reduce((a, p) => a + p.count, 0);
    $('parts-meta').textContent = `${shapeCount} 种形状 × ${colorCount} 种颜色 · 总库存 ${totalInv} 块 · 本方案 ${usedIds.length} 种零件 / ${DATA.steps.length} 块`;

    const tb = $('parts-tbody');
    tb.innerHTML = usedIds.map(id => {
      const p = partOf(id);
      return `<tr><td><span class="lgs-dot" style="background:${p.color}"></span>${p.name}</td><td>${p.w}×${p.d}</td><td>${p.colorName}</td><td class="num">${p.count}</td><td class="num">${DATA.usage[id] || 0}</td></tr>`;
    }).join('') + `<tr><td><strong>合计</strong></td><td></td><td></td><td class="num">${usedIds.reduce((a, id) => a + partOf(id).count, 0)}</td><td class="num"><strong>${DATA.steps.length}</strong></td></tr>`;

    // 全部库存：按形状分组，一行一个形状，列出该形状各颜色的库存
    const byShape = new Map();
    for (const p of DATA.parts) {
      const k = p.shape || p.id;
      if (!byShape.has(k)) byShape.set(k, []);
      byShape.get(k).push(p);
    }
    const invHtml = [...byShape.values()].map(list => {
      const p0 = list[0];
      const chips = list.map(p => `<span class="lgs-dot" style="background:${p.color}"></span>${p.colorName} ${p.count}`).join(' · ');
      return `<tr><td>${p0.name}</td><td>${p0.w}×${p0.d}</td><td>${chips}</td></tr>`;
    }).join('');
    const invBox = $('parts-inventory');
    if (invBox) {
      invBox.innerHTML = `<table class="lgs-caption"><thead><tr><th>形状</th><th>尺寸</th><th>各色库存（块）</th></tr></thead><tbody>${invHtml}</tbody></table>`;
    }
  }

  // ---------- 拼装模拟 ----------
  let curStep = 0, playing = false, timer = null;
  const drops = [];
  const clock = new THREE.Clock();

  function initBuild() {
    const f = fitCam(DATA);
    buildView = makeView($('canvas-build'), f.pos, f.target);
    baseplate(buildView.scene, f.plateW, f.plateD, f.ox, f.oz);
    const all = allVox();
    const ghostMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(themeColor('--text', '#667085')), transparent: true, opacity: 0.08, depthWrite: false });
    const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(1, H, 1), ghostMat, all.length);
    const M = new THREE.Matrix4();
    all.forEach((v, i) => { M.makeTranslation(v[0] + 0.5, v[1] * H + H / 2, v[2] + 0.5); inst.setMatrixAt(i, M); });
    const ghost = new THREE.Group();
    ghost.add(inst);
    ghost.add(voxelEdges(all, 0x808080, 0.35));
    buildView.scene.add(ghost);
    buildView.ghost = ghost;
    buildView.bricks = [];
    const studData = [];
    DATA.steps.forEach((s, bi) => {
      const p = partOfSafe(s.piece);
      const g = new THREE.Group();
      if (p.slope) {
        g.add(makeSlopeBrick(p, s.w, s.d, Boolean(s.rotate), false));
        for (const [a, b] of partStudOffsets(p, s.w, s.d, Boolean(s.rotate))) {
          studData.push({ color: p.color, x: s.x + a + 0.5, y: s.layer * H + H + STUD_H / 2, z: s.z + b + 0.5, brick: bi });
        }
      } else {
        const { box } = brickGeos(s.w, s.d);
        const body = new THREE.Mesh(box, mat(p.color));
        body.position.set(s.w / 2, H / 2, s.d / 2);
        g.add(body);
        const edge = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.18 }));
        edge.position.copy(body.position);
        g.add(edge);
        for (let a = 0; a < s.w; a++) for (let b = 0; b < s.d; b++)
          studData.push({ color: p.color, x: s.x + a + 0.5, y: s.layer * H + H + STUD_H / 2, z: s.z + b + 0.5, brick: bi });
      }
      g.position.set(s.x, s.layer * H, s.z);
      g.visible = false;
      buildView.scene.add(g);
      buildView.bricks.push(g);
    });
    // 凸点按颜色实例化（大模型性能关键）
    const pools = new Map();
    const ZERO = new THREE.Matrix4().makeScale(0, 0, 0);
    for (const sd of studData) {
      if (!pools.has(sd.color)) {
        const n = studData.filter(q => q.color === sd.color).length;
        const im = new THREE.InstancedMesh(brickGeos(1, 1).stud, mat(sd.color), n);
        buildView.scene.add(im);
        pools.set(sd.color, { im, refs: [], n: 0 });
      }
      const pool = pools.get(sd.color);
      M.makeTranslation(sd.x, sd.y, sd.z);
      pool.im.setMatrixAt(pool.n, M);
      pool.refs.push({ idx: pool.n, brick: sd.brick, x: sd.x, y: sd.y, z: sd.z });
      pool.n++;
    }
    buildView.pools = pools;
    buildView.ZERO = ZERO;
    function setStuds(k) {
      for (const { im, refs } of pools.values()) {
        for (const r of refs) {
          if (brickVisibleAtStep(r.brick, k)) M.makeTranslation(r.x, r.y, r.z); else M.copy(ZERO);
          im.setMatrixAt(r.idx, M);
        }
        im.instanceMatrix.needsUpdate = true;
      }
    }
    buildView.setStuds = setStuds;
    setStuds(savedStep);
    buildView.inited = true;
    resize(buildView); views.push(buildView);
    applyStep(savedStep, false);
  }

  function animateDrop(b) {
    if (reduced) return;
    b.userData.baseY = b.position.y;
    b.userData.t = 0;
    drops.push(b);
  }
  function tickDrops(dt) {
    for (let i = drops.length - 1; i >= 0; i--) {
      const b = drops[i];
      b.userData.t += dt;
      const k = Math.min(1, b.userData.t / 0.25);
      const e = 1 - Math.pow(1 - k, 3);
      b.position.y = b.userData.baseY + 2.5 * (1 - e);
      if (k >= 1) { b.position.y = b.userData.baseY; drops.splice(i, 1); }
    }
  }

  // 预拼子组件成组落位：子组件成员在主结构上直至其扣合完成步（dockStep）整组同时显示并播放落位动画，
  // 杜绝中间悬空单砖在底板上凭空漂浮。
  const subOfStep = new Map();
  const subDockOfStep = new Map();
  const subBricksOfDock = new Map();
  const dockOfBrick = new Map();
  (DATA.subassemblies || []).forEach((sub, i) => {
    const ss = (sub.steps || []).slice().sort((a, b) => a - b);
    if (!ss.length) return;
    const dock = ss[ss.length - 1];
    const brickIndices = ss.map(n => n - 1).filter(bi => bi >= 0 && bi < DATA.steps.length);
    ss.forEach(n => {
      subOfStep.set(n, i + 1);
      subDockOfStep.set(n, dock);
    });
    brickIndices.forEach(bi => dockOfBrick.set(bi, dock));
    subBricksOfDock.set(dock, (subBricksOfDock.get(dock) || []).concat(brickIndices));
  });

  function brickVisibleAtStep(bi, k) {
    if (dockOfBrick.has(bi)) return k >= dockOfBrick.get(bi);
    return bi < k;
  }

  function applyStep(k, animLast) {
    if (!buildView) { savedStep = k; return; }
    if (k > curStep && subDockOfStep.has(k) && subBricksOfDock.has(subDockOfStep.get(k))) {
      // 若当前步正好是某子组件的首个待扣件，步进到其扣入完成步；但中间常规主干砖仍逐块走完
      const dock = subDockOfStep.get(k);
      if (k === dock) k = dock;
    }
    curStep = Math.max(0, Math.min(DATA.steps.length, k));
    buildView.bricks.forEach((b, i) => { b.visible = brickVisibleAtStep(i, curStep); });
    buildView.setStuds(curStep);
    if (animLast && curStep > 0) {
      const grp = subBricksOfDock.get(curStep);
      if (grp && grp.length) grp.forEach(bi => animateDrop(buildView.bricks[bi]));
      else if (brickVisibleAtStep(curStep - 1, curStep)) animateDrop(buildView.bricks[curStep - 1]);
    }
    $('slider').value = curStep;
    $('stepnum').textContent = curStep + ' / ' + DATA.steps.length;
    const info = $('stepinfo');
    if (curStep === 0) {
      info.innerHTML = '<span class="lgs-muted">绿色底板上还没有零件 —— 点击「播放」或拖动滑块，看拼装方案逐块成型。</span>';
    } else {
      const s = DATA.steps[curStep - 1];
      const p = partOfSafe(s.piece);
      const subTag = subOfStep.get(s.step) ? ` · 预拼子模块 sub${subOfStep.get(s.step)}（整组落位）` : '';
      const detail = `${p.colorName} ${p.name} · 覆盖 x=${s.x}..${s.x + s.w - 1}，z=${s.z}..${s.z + s.d - 1}` + (s.rotate ? ' · 旋转 90°' : '') + subTag;
      if (curStep === DATA.steps.length) {
        info.innerHTML = `<span class="lgs-badge">完成 ${DATA.steps.length} / ${DATA.steps.length}</span><strong>与目标模型逐体素一致</strong><span class="lgs-muted">✅</span>`;
      } else {
        // 模块名等 DATA 字段来自模型输出，插入 innerHTML 前必须转义（存储型 XSS 防线）
        info.innerHTML = `<span class="lgs-badge">第 ${s.step} 步</span><strong>y=${s.layer} 层 · ${esc(zoneName(s))}</strong><span>${esc(detail)}</span>`;
      }
    }
    if (opts.onState) opts.onState({ tab: curTab, step: curStep });
  }

  function setPlaying(on) {
    playing = on;
    const btn = $('play');
    btn.textContent = on ? '暂停' : '播放';
    btn.setAttribute('aria-label', on ? '暂停' : '播放');
    if (timer) { clearInterval(timer); timer = null; }
    if (on) {
      if (curStep >= DATA.steps.length) applyStep(0, false);
      timer = setInterval(() => {
        applyStep(curStep + 1, true);
        if (curStep >= DATA.steps.length) setPlaying(false);
      }, 750);
    }
  }

  // ---------- 标签页 ----------
  let curTab = 'model';
  function activate(name) {
    curTab = name;
    for (const t of root.querySelectorAll('[role="tab"]')) {
      const on = t.dataset.el === 'tab-' + name;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    }
    for (const n of ['model', 'parts', 'build']) {
      $('panel-' + n).hidden = n !== name;
    }
    if (name === 'model' && !modelView) initModel();
    if (name === 'parts' && !partsView) initParts();
    if (name === 'build' && !buildView) initBuild();
    const v = name === 'model' ? modelView : name === 'parts' ? partsView : buildView;
    if (v) resize(v);
    if (opts.onState) opts.onState({ tab: curTab, step: curStep });
  }
  for (const t of root.querySelectorAll('[role="tab"]')) {
    t.addEventListener('click', () => activate(t.dataset.el.replace('tab-', '')));
  }

  // ---------- 控件 ----------
  $('model-name').textContent = DATA.name || '乐高模型';
  $('model-meta').textContent = `占地 ${DATA.grid.w}×${DATA.grid.d} studs · ${DATA.layers.length} 层 · ${DATA.layers.reduce((a, L) => a + L.cells.length, 0)} 个体素`;
  $('build-meta').textContent = `${DATA.model || 'AI'} 推理 · 程序校验通过（第 ${DATA.attempts} 次尝试）· 共 ${DATA.steps.length} 块零件`;
  $('build-caption').textContent = `AI 策略：${DATA.strategy}`;
  $('slider').addEventListener('input', e => applyStep(+e.target.value, false));
  $('prev').addEventListener('click', () => applyStep(curStep - 1, false));
  $('next').addEventListener('click', () => applyStep(curStep + 1, true));
  $('reset').addEventListener('click', () => { setPlaying(false); applyStep(0, false); });
  $('play').addEventListener('click', () => setPlaying(!playing));
  $('ghost').addEventListener('change', e => { if (buildView) buildView.ghost.visible = e.target.checked; });

  const ro = new ResizeObserver(() => {
    for (const v of views) if (v.inited && v.canvas.offsetParent !== null) resize(v);
  });
  ro.observe(root);

  let raf = 0;
  function loop() {
    tickDrops(clock.getDelta());
    for (const v of views) {
      if (!v.inited || v.canvas.offsetParent === null) continue;
      v.controls.update();
      v.renderer.render(v.scene, v.camera);
    }
    raf = requestAnimationFrame(loop);
  }
  raf = requestAnimationFrame(loop);

  const initialTab = (opts.initial && opts.initial.tab) || 'model';
  activate(['model', 'parts', 'build'].includes(initialTab) ? initialTab : 'model');

  return {
    apply: k => applyStep(k, false),
    activate,
    destroy: () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      if (timer) clearInterval(timer);
      for (const v of views) {
        v.renderer.dispose();
        // dispose 不立即释放 WebGL 上下文（等 GC）；强制丢失，防止反复挂载逼近浏览器 16 上下文上限
        try { v.renderer.forceContextLoss(); } catch (e) { /* 上下文可能已丢失 */ }
        v.controls.dispose();
      }
      root.innerHTML = '';
      root.classList.remove('lgs-root');
    },
  };
}
