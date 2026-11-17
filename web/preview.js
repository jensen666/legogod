// ============================================================
// 设计稿实时预览。只吃彩色体素，不复用工作室组件。
// 层高与成品工作室一致（1.2），相机按包围盒取景。换稿复用同一个上下文，
// 用户已经转过的视角不重置。
// ============================================================

const LAYER_H = 1.2;

function cellsOf(design) {
  const palette = design.palette || {};
  const chars = design.chars || {};
  const cells = [];
  for (const layer of design.layers || []) {
    const rows = layer.rows || [];
    const colorRows = layer.colorRows || null;
    const y = Number(layer.y) || 0;
    for (let z = 0; z < rows.length; z++) {
      const row = String(rows[z] || '');
      for (let x = 0; x < row.length; x++) {
        if (row[x] === '.' || row[x] === ' ') continue;
        let name = layer.color || '';
        if (colorRows && colorRows[z] && colorRows[z][x] && colorRows[z][x] !== '.') {
          name = chars[colorRows[z][x]] || name;
        }
        cells.push({ x, y, z, hex: palette[name] || '#A0A5A9' });
      }
    }
  }
  return cells;
}

function hexToInt(hex) {
  const n = parseInt(String(hex).replace('#', ''), 16);
  return Number.isFinite(n) ? n : 0xa0a5a9;
}

function placeMesh(THREE, mesh, cells) {
  const dummy = new THREE.Object3D();
  const color = new THREE.Color();
  cells.forEach((c, i) => {
    dummy.position.set(c.x + 0.5, c.y * LAYER_H + LAYER_H / 2, c.z + 0.5);
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
    mesh.setColorAt(i, color.set(hexToInt(c.hex)));
  });
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  mesh.count = cells.length;
}

function fitCamera(THREE, camera, controls, mesh) {
  const box = new THREE.Box3().setFromObject(mesh);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(1, 0.5 * Math.hypot(size.x, size.y, size.z));
  const fov = camera.fov * Math.PI / 180;
  const dist = radius / Math.sin(fov / 2) * 1.15;
  camera.position.copy(center).add(new THREE.Vector3(dist * 0.55, dist * 0.38, dist * 0.72));
  controls.target.copy(center);
  camera.near = Math.max(0.05, dist / 80);
  camera.far = dist * 24;
  camera.updateProjectionMatrix();
  controls.update();
}

export async function mountPreview(host, design) {
  const cells = cellsOf(design || {});
  host.innerHTML = '<div class="preview-stage"><canvas data-preview-canvas></canvas>' +
    '<p class="preview-cap">设计稿 · 拖动旋转，滚轮缩放</p></div>';
  const canvas = host.querySelector('canvas');
  if (!cells.length) {
    host.querySelector('.preview-cap').textContent = '设计稿还没有体素';
    return {
      destroy() { host.innerHTML = ''; },
      update() {},
    };
  }
  const THREE = await import('three');
  const { OrbitControls } = await import('three/addons/controls/OrbitControls.js');
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xe9eef3);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 500);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const geom = new THREE.BoxGeometry(0.92, LAYER_H * 0.92, 0.92);
  const mat = new THREE.MeshLambertMaterial();
  let mesh = new THREE.InstancedMesh(geom, mat, cells.length);
  placeMesh(THREE, mesh, cells);
  scene.add(mesh);
  scene.add(new THREE.AmbientLight(0xffffff, 0.72));
  const dir = new THREE.DirectionalLight(0xffffff, 0.85);
  dir.position.set(8, 16, 10);
  scene.add(dir);
  const controls = new OrbitControls(camera, canvas);
  let moved = false;
  controls.addEventListener('start', () => { moved = true; });
  fitCamera(THREE, camera, controls, mesh);
  let raf = 0;
  let alive = true;
  function resize() {
    const rect = host.getBoundingClientRect();
    const width = Math.max(1, rect.width);
    const height = Math.max(1, rect.height);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();
  function loop() {
    if (!alive) return;
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }
  console.info('[preview] 设计稿预览挂载', design && design.stamp, cells.length);
  raf = requestAnimationFrame(loop);
  return {
    update(next) {
      const nextCells = cellsOf(next || {});
      if (!nextCells.length || !alive) return;
      scene.remove(mesh);
      mesh = new THREE.InstancedMesh(geom, mat, nextCells.length);
      placeMesh(THREE, mesh, nextCells);
      scene.add(mesh);
      if (!moved) fitCamera(THREE, camera, controls, mesh);
      console.info('[preview] 设计稿已换稿', next && next.stamp, nextCells.length, moved ? '保留视角' : '重新取景');
    },
    destroy() {
      alive = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      geom.dispose();
      mat.dispose();
      renderer.dispose();
      try { renderer.forceContextLoss(); } catch (e) { /* 上下文可能已经丢了 */ }
      host.innerHTML = '';
      console.info('[preview] 设计稿预览销毁');
    },
  };
}
