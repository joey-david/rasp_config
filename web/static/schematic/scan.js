async function openScan() {
  const host = document.querySelector('#orbit');
  const status = document.querySelector('#scan-status');
  const resetBtn = document.querySelector('#reset-view');
  const camBtns = Array.from(document.querySelectorAll('[data-cam]'));

  // Calibrated world frame from the 12,000-step dual-pass reconstruction.
  const target = [-0.134, 0.138, 0.161];
  const up = [0.003, -0.765, -0.644];
  const presets = {
    front: [0.557, 0.011, -2.503],
    rear: [-0.824, -2.265, 0.764],
    underside: [0.006, 2.278, 1.664]
  };

  const renderer = new Splat.WebGLRenderer({ antialias: false, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(host.clientWidth, host.clientHeight);
  host.append(renderer.domElement);

  const viewer = new Splat.Viewer({
    rootElement: host,
    renderer,
    cameraUp: up,
    initialCameraPosition: presets.front,
    initialCameraLookAt: target,
    sceneRevealMode: 2,
    sharedMemoryForWorkers: false,
    gpuAcceleratedSort: false,
    sphericalHarmonicsDegree: 2
  });

  // Register the metric glTF to the splat's arbitrary world units.
  // The basis comes from the outer wheel hubs and battery lid.
  const assemblyFile = new Splat.GLTFLoader().loadAsync('robot-assembly.glb');
  const [asset] = await Promise.all([
    assemblyFile, viewer.addSplatScene('robot.ksplat', { showLoadingUI: false })
  ]);
  const factor = 1000 / 79.670298;
  const assembly = asset.scene;
  assembly.matrixAutoUpdate = false;
  assembly.matrix.set(
    .885087*factor, .009371*factor, -.465331*factor, -.130454-.009371*32.5/79.670298,
    .303928*factor, -.768831*factor, .562607*factor, .386352+.768831*32.5/79.670298,
    -.352489*factor, -.639383*factor, -.683330*factor, .341067+.639383*32.5/79.670298,
    0, 0, 0, 1
  );
  viewer.threeScene.add(assembly, new Splat.HemisphereLight(0xffffff,0xc5d0e0,1.45));
  const key = new Splat.DirectionalLight(0xfff1df,2.1);
  key.position.set(-2,-4,-3);
  viewer.threeScene.add(key);
  const selector = document.querySelector('#inspect-part');
  const groups = [];
  assembly.traverse(node => {if(node.children.some(c => c.isMesh)) groups.push(node)});
  selector.add(new Option('Under the upper deck', 'cutaway'));
  groups.forEach((group,i) => selector.add(new Option(group.name.replaceAll('_',' '),String(i))));
  selector.onchange = () => {
    groups.forEach((g,i) => {
      const part = g.name.replaceAll('_',' ');
      g.visible = selector.value === 'cutaway'
        ? !['Anker battery','Upper acrylic deck'].includes(part)
        : selector.value === '' || String(i) === selector.value;
    });
    viewer.forceRenderNextFrame();
  };
  function display(mode) {
    const model = mode === 'assembly';
    assembly.visible = model;
    viewer.splatMesh.visible = !model;
    selector.disabled = !model;
    document.querySelector('.scan-label').textContent = model ? 'PARTS MODEL · 65 MM TIRE ASSUMED' : 'GAUSSIAN SPLAT · DUAL PASS';
    document.querySelectorAll('[data-model]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.model === mode)));
    viewer.forceRenderNextFrame();
  }
  document.querySelectorAll('[data-model]').forEach(b => b.onclick = () => display(b.dataset.model));
  display('assembly');
  viewer.start();
  status.hidden = true;

  let animFrame = 0;
  function setActiveCam(name) {
    camBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.cam === name)));
  }

  function moveCameraTo(eyeArr, activeName) {
    cancelAnimationFrame(animFrame);
    setActiveCam(activeName);
    const startPos = viewer.camera.position.clone();
    const startTarget = viewer.controls.target.clone();
    const endPos = startPos.clone().fromArray(eyeArr);
    const endTarget = startTarget.clone().fromArray(target);
    const t0 = performance.now();
    const duration = 360;

    function step(now) {
      const u = Math.min(1, (now - t0) / duration);
      const ease = 1 - Math.pow(1 - u, 3);
      viewer.camera.position.lerpVectors(startPos, endPos, ease);
      viewer.controls.target.lerpVectors(startTarget, endTarget, ease);
      viewer.controls.update();
      viewer.forceRenderNextFrame();
      if (u < 1) animFrame = requestAnimationFrame(step);
    }
    animFrame = requestAnimationFrame(step);
  }

  camBtns.forEach((btn) => {
    btn.addEventListener('click', () => {
      const name = btn.dataset.cam;
      if (presets[name]) moveCameraTo(presets[name], name);
    });
  });

  resetBtn.addEventListener('click', () => moveCameraTo(presets.front, 'front'));

  host.addEventListener('pointerdown', () => {
    cancelAnimationFrame(animFrame);
    setActiveCam('');
  });

  new ResizeObserver(() => {
    if (!host.clientWidth || !host.clientHeight) return;
    renderer.setSize(host.clientWidth, host.clientHeight);
    viewer.camera.aspect = host.clientWidth / host.clientHeight;
    viewer.camera.updateProjectionMatrix();
    viewer.forceRenderNextFrame();
  }).observe(host);

  host.addEventListener('keydown', (e) => {
    const dirs = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: 1, ArrowDown: -1 };
    if (!(e.key in dirs || ['+', '=', '-'].includes(e.key))) return;
    e.preventDefault();
    cancelAnimationFrame(animFrame);
    setActiveCam('');
    const offset = viewer.camera.position.clone().sub(viewer.controls.target);
    if (e.key.startsWith('Arrow')) {
      let axis = viewer.camera.up.clone().normalize();
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') axis.cross(offset).normalize();
      offset.applyAxisAngle(axis, dirs[e.key] * 0.13);
    } else {
      offset.multiplyScalar(e.key === '-' ? 1.12 : 0.89);
    }
    viewer.camera.position.copy(viewer.controls.target).add(offset);
    viewer.controls.update();
    viewer.forceRenderNextFrame();
  });

  host.dataset.ready = 'true';
}

document.querySelector('#expand-view').addEventListener('click', async () => {
  if (document.fullscreenElement) await document.exitFullscreen();
  else await document.querySelector('figure').requestFullscreen();
});

openScan().catch((error) => {
  document.querySelector('#scan-status').textContent =
    location.protocol === 'file:'
      ? 'Open the local website over HTTP to load the 3D scan.'
      : 'The 3D viewer needs WebGL 2. The component sheets are available below.';
  console.error(error);
});
