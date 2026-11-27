// Knot-free planar software architecture sheet (Sheet 03).
// Grounded in the booted 62 GB USB drive (/Volumes/bootfs, /dev/disk4) and repository code.
(function () {
  const NS = {};

  const modules = {
    boot: {
      name: 'USB Boot & systemd',
      eyebrow: 'FOUNDATION · /dev/disk4 (62 GB)',
      host: 'USB Stick → Raspberry Pi',
      layer: 'OS & Process Supervisor',
      summary:
        'Boots Raspberry Pi OS 64-bit (Debian Trixie) from the 62 GB USB drive, enables the OV5647 camera overlay while freeing I2S pins, and launches mischief-bot.service automatically after network-online.',
      interfaces: 'FAT32 bootfs (537 MB) + ext4 rootfs (61.4 GB) → web/web_interface.py',
      sources: 'systemd/mischief-bot.service · /Volumes/bootfs/config.txt · bin/deploy-pi.sh',
      specs: [
        ['Partitions', 'disk4s1 FAT32 536.9 MB (bootfs) + disk4s2 ext4 61.4 GB (rootfs)'],
        ['Camera Overlay', 'camera_auto_detect=0, dtoverlay=ov5647 (confirmed OV5647)'],
        ['Freed GPIO', 'i2s & respeaker-2mic disabled → frees GPIO 18–21 (pins 35/38/40)'],
        ['Supervisor', 'Restart=always (3 s) · MOTOR_POWER=70 · EDGE_SAFETY_ENABLED=1'],
        ['Deploy', 'bin/deploy-pi.sh syncs via rsync/SSH and restarts the unit']
      ],
      jumps: [
        ['wiring/usb', 'View USB hardware →'],
        ['wiring/cam', 'View camera CSI →']
      ]
    },
    api: {
      name: 'Cockpit & RobotAPI',
      eyebrow: 'ENTRY POINT · ON-PI + BROWSER',
      host: 'Browser ↔ Raspberry Pi',
      layer: 'Transport & Central Facade',
      summary:
        'Serves the browser cockpit over HTTP :8080, accepts low-latency UDP motion on :8766, and owns the single-skill claim lock. RobotAPI guards sequence order and checks Level 0 edge safety before any wheel moves.',
      interfaces: 'HTTP :8080 (REST + MJPEG + UI) · UDP :8766 (latest-wins velocity)',
      sources: 'web/web_interface.py · web/static/cockpit.js · robot_api.py · hardware/motion_udp.py',
      specs: [
        ['Read Routes', '/, /stream.mjpg, /frame/latest.jpg, /api/state, /api/detections, /api/autonomy, /api/odometry'],
        ['Control Routes', '/drive, /motion/set_velocity, /motion/stop, /camera/settings, /autonomy/*, /skill/*'],
        ['Concurrency', 'Single _skill_claim lock; manual /drive stops active skills first'],
        ['Sequence Guard', '_fresh_motion_seq drops stale/out-of-order HTTP & UDP packets']
      ],
      jumps: [['assembly/pi', 'View Pi component →']]
    },
    camera: {
      name: 'Camera & Odometry',
      eyebrow: 'SENSING · OV5647 CSI',
      host: 'Raspberry Pi',
      layer: 'Capture & Visual Speed',
      summary:
        'Runs rpicam-vid for 640×480 @ 30 fps MJPEG streaming and rpicam-still for 2592×1944 stills. Decodes an in-memory 320×240 grayscale stream at 15 Hz for edge safety and computes 160×120 visual angular/linear speed.',
      interfaces: 'OV5647 CSI → MJPEG 30 fps · 320×240 gray @ 15 Hz · 160×120 odom',
      sources: 'perception/camera.py · perception/odometry/runtime.py · angular.py · linear.py',
      specs: [
        ['Stream / Stills', '640×480 @ 30 fps MJPEG · 2592×1944 JPEG stills (q=95)'],
        ['Grayscale Feed', '320×240 @ 15 Hz (CAMERA_GRAY_HZ) via OpenCV'],
        ['Visual Odometry', '160×120 gray (fx_px=48.5, angular_sign=-1, min_score=0.08)'],
        ['Live Tuning', 'fps (1–30), hflip, vflip, digital crop (resets edge baseline)']
      ],
      jumps: [['wiring/cam', 'View camera wiring →']]
    },
    vision: {
      name: 'Vision & Spatial Map',
      eyebrow: 'PERCEPTION · 4 HZ + MEMORY',
      host: 'Raspberry Pi ↔ Mac',
      layer: 'Detection & Egocentric Map',
      summary:
        'Polls the Mac YOLO server at 4 Hz (pausing cleanly via vision.exclusive() for active skills), enriches boxes with non-metric relative depth (1/scale), and fuses sightings with Motion command history into a 120 s landmark map.',
      interfaces: 'POST JPEG → :8081 · Motion command observer → 30 s pose + 120 s map',
      sources: 'perception/vision.py · receiver.py · spatial_map.py · mischief_common/',
      specs: [
        ['Scanner Rate', '4 Hz background /detect-all · one targeted detection for follow / lock-on · up to three samples per find / approach observation'],
        ['Geometry', 'Normalized center, area, truncated flag, relative_depth = 1/scale'],
        ['Spatial Map', 'HFOV=62°, EMA merge (α=0.35), 120 s TTL, capture-timestamp pose'],
        ['Motion Sync', 'Subscribes to Motion so watchdog stops update dead reckoning']
      ],
      jumps: []
    },
    safety: {
      name: 'L0 · Edge Safety',
      eyebrow: 'LEVEL 0 · 20 HZ FAIL-CLOSED',
      host: 'Raspberry Pi',
      layer: 'Hard Safety Guard',
      summary:
        'Inspects the forward support surface in the 320×240 grayscale feed every 50 ms. Learns floor texture only while stopped and vetoes all forward motion on table edges, missing calibration, or stale frames.',
      interfaces: 'Camera 15 Hz gray → 20 Hz monitor → RobotAPI / Motion veto',
      sources: 'hardware/safety/safety.py · hardware/safety/danger.py',
      specs: [
        ['Detection Cues', 'Sobel texture drop (<0.42× baseline) + horizontal edge boundary'],
        ['Latch Policy', '8 stationary warmup · latch after 2 danger · clear after 4 safe'],
        ['Fail-Closed', 'Vetoes forward if frame age > 0.5 s, uncalibrated, or OpenCV unavailable'],
        ['Recovery', 'Reverse (linear < 0) and in-place turns (linear == 0) stay allowed']
      ],
      jumps: []
    },
    motion: {
      name: 'L1 · Motion & GPIO',
      eyebrow: 'LEVEL 1 · SOLE MOTOR OWNER',
      host: 'Raspberry Pi → TB6612FNG',
      layer: 'Hardware Actuation',
      summary:
        'Sole owner of both drive motors. Clamps tank wheel commands to the configured 70% cap, drives 1 kHz PWM via lgpio, stops automatically after 0.75 s without commands, and releases GPIO pins after 5 s idle.',
      interfaces: 'lgpio gpiochip0 (BCM 6/12/13/16/20/21/26) → TB6612FNG → wheels',
      sources: 'hardware/motion.py · hardware/motors.py · hardware/gpio_mappings.yaml',
      specs: [
        ['Power Cap', '70% max (MOTOR_POWER=70); tank(linear+angular, linear-angular)'],
        ['Watchdog', '0.75 s stale-command auto-stop (polled every 100 ms)'],
        ['GPIO Release', 'Closes lgpio chip handle after 5.0 s idle'],
        ['Pin Map', 'Left=A (rev, BCM 12/16/6) · Right=B (BCM 13/20/21) · STBY=26']
      ],
      jumps: [
        ['wiring/driver', 'View TB6612FNG pins →'],
        ['wiring/left', 'View motors →']
      ]
    },
    skills: {
      name: 'L2 · Skills & Emotes',
      eyebrow: 'LEVEL 2 · BOUNDED BEHAVIORS',
      host: 'Raspberry Pi',
      layer: 'Closed-Loop Skills',
      summary:
        'Stop-and-look visual navigation and contact skills (find, go_to, push, push_to, follow, lock_on) plus 11 expressive emotes. Follow and lock-on interleave a single detection with a short pulse. Find and approach stop to sample. Contact skills check a protected-label list.',
      interfaces: 'VisionScanner.exclusive() + SkillMovement → RobotAPI.set_velocity()',
      sources: 'skills/objects.py · find.py · follow.py · lock_on.py · emotes.py · tuning.py',
      specs: [
        ['Operating Band', 'Follow / lock-on: 80 ms pulses · find: 120 ms settle · approach: 150 ms settle'],
        ['Skills', 'find, go_to (0.43), push (0.60), push_to (12 pulses), follow, lock_on'],
        ['Emotes (11)', 'nod, wiggle, shake, slow_no, TORNADO, double_take, happy_dance…'],
        ['Living Guard', 'NO_CONTACT blocks push/push_to on person, cat, dog, bird, animals']
      ],
      jumps: []
    },
    autonomy: {
      name: 'L3 · Autonomy',
      eyebrow: 'LEVEL 3 · SENSE-PLAN-ACT',
      host: 'Raspberry Pi ↔ Mac Planner',
      layer: 'Bounded Deliberation',
      summary:
        'Runs a bounded sense-plan-act loop (12 steps by default). Captures one frame, runs YOLO on that exact JPEG, asks the offboard VLM for one allowed skill, and discards any late reply if stopped mid-flight.',
      interfaces: 'Exact-frame YOLO + POST :8090/plan → 1 validated L2 skill',
      sources: 'autonomy/controller.py · autonomy/remote.py',
      specs: [
        ['Allowed Schema', 'observe, find, go_to, push, push_to, emote, wait (≤5 s), stop'],
        ['Motor Isolation', 'Never exposes raw motor powers — only bounded skills'],
        ['Contact Gate', 'AUTONOMY_ALLOW_CONTACT=0 by default (rejects push/push_to)'],
        ['Stop Guards', 'Default 12 steps (cap 50), halts after 3 consecutive failed actions']
      ],
      jumps: []
    },
    yolo: {
      name: 'YOLO + Label Resolver',
      eyebrow: 'OFFBOARD · MAC MPS :8081',
      host: 'Mac (192.168.0.24)',
      layer: 'Visual Detection Service',
      summary:
        'Serialized Apple Silicon MPS detection server running YOLO11s, paired with an MLX bge-micro embedding resolver that maps free-form natural language queries to the closest COCO-80 label.',
      interfaces: 'HTTP :8081 · POST /detect, /detect-all · GET /resolve-label, /health',
      sources: 'pc_inference/object_detection.py · resolve_label.py · bin/start-pc-inference.sh',
      specs: [
        ['Model & Device', 'yolo11s.pt on Apple Silicon MPS (serialized threading.Lock)'],
        ['Resolution', 'imgsz=640 stream default · up to 1920 for full-sensor stills'],
        ['Label Resolver', 'Exact COCO-80 match or cached MLX bge-micro cosine similarity'],
        ['Launcher', 'uv run --python 3.11 (ultralytics, mlx, pillow)']
      ],
      jumps: []
    },
    vlm: {
      name: 'VLM Planner & Model',
      eyebrow: 'OFFBOARD · :8090 → :8000',
      host: 'Mac / GPU Host',
      layer: 'Vision-Language Planning',
      summary:
        'FastAPI gateway (:8090) checks optional Bearer auth, downscales the frame to 320 px, enforces JSON output, and calls local MLX Qwen3-VL-8B-4bit (:8000) or any remote OpenAI-compatible GPU host.',
      interfaces: 'HTTP :8090 /plan → upstream :8000 /v1/chat/completions',
      sources: 'pc_inference/vlm_server.py · bin/start-vlm-inference.sh · bin/start-vlm-planner.sh',
      specs: [
        ['Planner Shim', 'FastAPI + Uvicorn · Bearer auth · --mock testing mode'],
        ['Image Prep', 'Thumbnails base64 JPEG to 320 px max side (q=85) · temp 0.1'],
        ['Local Model', 'mlx-community/Qwen3-VL-8B-Instruct-4bit (4096 KV cache)'],
        ['Remote Option', 'Set VLM_BASE_URL + VLM_API_KEY for any OpenAI-compatible GPU']
      ],
      jumps: []
    }
  };

  // Clean 10-node planar layout (viewBox 0 0 940 524) — ZERO wire crossings!
  const nodes = [
    // Foundation row (Pi top)
    { id: 'boot',     x: 32,  y: 44,  w: 248, h: 52, tag: 'USB /dev/disk4',        meta: 'Debian Trixie · mischief-bot.svc', tier: 'usb' },
    { id: 'api',      x: 336, y: 44,  w: 266, h: 52, tag: 'HTTP :8080 · UDP :8766', meta: 'Browser cockpit · RobotAPI facade', tier: 'core' },
    // Left lane (Pi hardware I/O & Level 0 guard)
    { id: 'camera',   x: 32,  y: 138, w: 230, h: 58, tag: 'OV5647 CSI',            meta: '30 fps MJPEG · 15 Hz gray · odom', tier: 'sense' },
    { id: 'safety',   x: 32,  y: 342, w: 230, h: 58, tag: 'LEVEL 0 · 20 HZ',       meta: 'Fail-closed table-edge veto',      tier: 'l0' },
    // Center lane (Pi perception & high-level control)
    { id: 'vision',   x: 336, y: 138, w: 266, h: 58, tag: '4 HZ + SPATIAL MAP',    meta: 'Detections · depth 1/s · 120 s',   tier: 'sense' },
    { id: 'autonomy', x: 336, y: 240, w: 266, h: 58, tag: 'LEVEL 3 · DELIBERATE',  meta: '12 steps by default · contact gated', tier: 'ctrl' },
    { id: 'skills',   x: 336, y: 342, w: 266, h: 58, tag: 'LEVEL 2 · BEHAVIORS',   meta: 'follow · lock-on · find · approach',  tier: 'ctrl' },
    // Bottom hardware floor (spans both L0 and L2 cleanly!)
    { id: 'motion',   x: 32,  y: 448, w: 570, h: 56, tag: 'LEVEL 1 · SOLE MOTOR OWNER', meta: '1 kHz PWM via lgpio · 70% cap · 0.75 s watchdog → TB6612FNG', tier: 'l1' },
    // Offboard Mac / GPU column (aligned 1:1 with Vision & Autonomy!)
    { id: 'yolo',     x: 700, y: 138, w: 212, h: 58, tag: 'MAC MPS · :8081',       meta: 'YOLO11s + bge-micro',              tier: 'offboard' },
    { id: 'vlm',      x: 700, y: 240, w: 212, h: 58, tag: 'FASTAPI :8090 → :8000', meta: 'Qwen3-VL-8B-4bit / GPU',           tier: 'offboard' }
  ];

  // Every single edge is planar (0 crossings!) and cleanly routed in dedicated corridors.
  const edges = [
    // Foundation
    { from: 'boot',     to: 'api',      d: 'M280 70 H336',                label: 'starts',      lx: 308, ly: 63,  anchor: 'middle', flows: ['overview'] },
    // Straight horizontal perception & Wi-Fi links (98 px Wi-Fi span!)
    { from: 'camera',   to: 'vision',   d: 'M262 167 H336',               label: 'JPEG',        lx: 299, ly: 160, anchor: 'middle', flows: ['vision', 'autonomy'] },
    { from: 'vision',   to: 'yolo',     d: 'M602 167 H700',               label: 'POST :8081',  lx: 651, ly: 158, anchor: 'middle', flows: ['vision', 'autonomy'], bi: true },
    { from: 'autonomy', to: 'vlm',      d: 'M602 269 H700',               label: 'POST :8090',  lx: 651, ly: 260, anchor: 'middle', flows: ['autonomy'], bi: true },
    // Straight vertical control & safety drops
    { from: 'camera',   to: 'safety',   d: 'M147 196 V342',               label: '15 Hz gray',  lx: 155, ly: 273, anchor: 'start',  flows: ['safety'] },
    { from: 'vision',   to: 'autonomy', d: 'M469 196 V240',               label: 'scene + map', lx: 477, ly: 222, anchor: 'start',  flows: ['autonomy'] },
    { from: 'autonomy', to: 'skills',   d: 'M469 298 V342',               label: '1 action',    lx: 477, ly: 324, anchor: 'start',  flows: ['autonomy'] },
    { from: 'safety',   to: 'motion',   d: 'M147 400 V448',               label: 'veto / allow',lx: 155, ly: 428, anchor: 'start',  flows: ['safety', 'manual', 'vision', 'autonomy'] },
    { from: 'skills',   to: 'motion',   d: 'M469 400 V448',               label: 'velocity',    lx: 477, ly: 428, anchor: 'start',  flows: ['vision', 'autonomy'] },
    // Dedicated uncrossed middle-corridor spines (Vision→Skills at x=308, API→Safety at x=284)
    { from: 'vision',   to: 'skills',   d: 'M336 182 H308 V371 H336',     label: 'targets',     lx: 303, ly: 294, anchor: 'end',    flows: ['vision'] },
    { from: 'api',      to: 'safety',   d: 'M364 96 V114 H284 V371 H262', label: 'drive gate',  lx: 278, ly: 332, anchor: 'end',    flows: ['manual'], subtle: true },
    { from: 'api',      to: 'autonomy', d: 'M562 96 V114 H616 V254 H602', label: 'goal',        lx: 610, ly: 126, anchor: 'end',    flows: ['autonomy'], subtle: true }
  ];

  const flows = [
    {
      id: 'overview',
      label: 'Overview',
      nodes: null,
      caption: 'All 10 modules across the Raspberry Pi and offboard Mac. Hover or click any block for its ports, limits, and source files.'
    },
    {
      id: 'safety',
      label: 'Safety · 20 Hz',
      nodes: ['camera', 'safety', 'motion'],
      caption: 'Every 50 ms, L0 checks 320×240 grayscale frames for table edges and vetoes unsafe forward motion before L1 touches the motors.'
    },
    {
      id: 'vision',
      label: 'Perception & skills',
      nodes: ['camera', 'vision', 'yolo', 'skills', 'safety', 'motion'],
      caption: 'The background scanner aims for 4 Hz. An active tracking skill pauses it and issues its own JPEG requests. The returned boxes feed L2 steering. The map also records sightings for later planning.'
    },
    {
      id: 'autonomy',
      label: 'Autonomy · L3',
      nodes: ['api', 'camera', 'vision', 'yolo', 'autonomy', 'vlm', 'skills', 'safety', 'motion'],
      caption: 'Bounded sense-plan-act loop (default 12 steps) pairs an exact frame and map with the VLM planner, validates one skill, and keeps contact off.'
    },
    {
      id: 'manual',
      label: 'Manual drive',
      nodes: ['api', 'safety', 'motion'],
      caption: 'Browser WASD uses HTTP /drive. UDP clients send linear and angular commands on :8766. Both paths check supplied sequence numbers and forward safety. The HTTP skill claim applies only to the web dispatch path.'
    }
  ];

  const sections = {
    overview: ['System map', '#software'],
    tracking: ['Follow & lock-on', '#software/tracking'],
    diagnosis: ['Failure analysis', '#software/diagnosis']
  };
  let section = 'overview';

  function sectionLinks() {
    return '<div class="sw-sections" role="navigation" aria-label="Software views">' +
      Object.entries(sections).map(([key, [title, href]]) =>
        `<a href="${href}"${key === section ? ' aria-current="page"' : ''}>${title}</a>`
      ).join('') + '</div>';
  }

  function levelContracts() {
    return `<section class="sw-reading"><h3>Who makes each decision?</h3>
    <p>The USB stick holds the OS and code. On the Pi, systemd starts one Python service. Its camera worker reads a separate <code>rpicam-vid</code> process. The four levels share RobotAPI state inside that service. The Pi calls offboard detection and planning services over HTTP. The browser uses a separate connection to the Pi for controls, video and status.</p>
    <dl class="sw-contracts">
    <dt><a href="#software/autonomy">L3 · Choose an action</a></dt><dd>The Pi sends a scene and its matching image to the planner shim. It checks the returned action and arguments against a fixed list, runs one action and records the result. The cockpit can start follow and lock-on directly at L2. Neither is in the L3 action schema.</dd>
    <dt><a href="#software/skills">L2 · Choose a movement</a></dt><dd>A skill turns a box or an object pair into a timed linear and angular command. Follow and lock-on take one detection per decision. Find and approach can take several samples while stopped. Each skill owns its loop and cancellation event.</dd>
    <dt><a href="#software/motion">L1 · Apply wheel duty</a></dt><dd>Motion mixes linear and angular commands into signed left and right duty, caps each independently, and writes both through one motor backend. Its watchdog can stop the wheels. Its observer sends commanded motion to the map.</dd>
    <dt><a href="#software/safety">L0 · Permit forward travel</a></dt><dd>RobotAPI checks the local edge verdict before positive linear motion reaches L1. A separate monitor can cut an ongoing forward command. Reverse and pure rotation remain available. L0 can intervene during an L2 or L3 action.</dd>
    </dl>
    <p class="sw-source">Entry points · systemd/mischief-bot.service · web/web_interface.py · robot_api.py · autonomy/controller.py · hardware/safety/safety.py</p></section>`;
  }

  function trackingSheet() {
    return `<article class="sw-reading"><p class="sw-kicker">L2 TRACKING LOOP · CAMERA TO WHEEL</p>
    <h3>One observation, one pulse</h3>
    <p>Follow combines steering and approach. Lock-on turns in place. Both resolve the target label, acquire exclusive perception, and repeat the same serial loop. The 4 Hz scanner pauses while the skill holds the inference lock.</p>
    <div class="sw-stage"><svg viewBox="0 0 760 164" class="sw-loop" role="img" aria-label="Frame to Mac detector, box to Pi steering, command through safety and motion, wheel motion back into the next camera frame">
    <defs><marker id="loop-tip" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0 L8 4 L0 8Z" class="sw-loop-tip"/></marker></defs>
    <g class="sw-loop-box"><rect x="9" y="27" width="121" height="49"/><rect x="175" y="27" width="125" height="49"/><rect x="345" y="27" width="126" height="49"/><rect x="516" y="27" width="122" height="49"/><rect x="670" y="27" width="82" height="49"/></g>
    <g class="sw-signal" text-anchor="middle"><text x="69" y="47">Pi camera</text><text x="237" y="47">Mac detector</text><text x="408" y="47">L2 steering</text><text x="577" y="47">L0 gate / L1</text><text x="711" y="47">Wheels</text></g>
    <g class="sw-signal-sub" text-anchor="middle"><text x="69" y="65">fresh frame ID</text><text x="237" y="65">box + score</text><text x="408" y="65">linear, turn</text><text x="577" y="65">left, right PWM</text><text x="711" y="65">yaw / travel</text></g>
    <g class="sw-loop-wire" marker-end="url(#loop-tip)"><path d="M130 52h41"/><path d="M300 52h41"/><path d="M471 52h41"/><path d="M638 52h28"/><path d="M711 76v57H69V80"/></g>
    <text x="390" y="121" text-anchor="middle" class="sw-signal-sub">Feedback arrives in the next image after the command stops.</text>
    </svg></div>
    <ol class="sw-stages">
    <li><b>Pi · Acquire</b>Wait for a JPEG with a higher frame ID. The Pi stamps it after parsing and cropping. Exposure and camera buffering precede this stamp.</li>
    <li><b>Mac → Pi · Detect</b>POST that JPEG to <code>/detect</code>. Pick the matching label with the highest score minus 0.35 × distance from the previous center. A miss or request error stops motion for this cycle.</li>
    <li><b>Pi · Steer</b>Subtract 0.5 from the normalized box center. Smooth the result, check its sign, then convert it to angular duty. Follow also uses box height to choose forward duty.</li>
    <li><b>L0 → L1 · Apply</b>Check forward safety, mix and cap wheel duties, request 80 ms of movement, then command zero. A stop request can shorten the pulse. The next detection starts after the pulse.</li>
    </ol>
    <h4>Where the time goes</h4><p class="sw-equation">Cycle ≈ max(target period, fresh-frame wait + JPEG round trip + local work + pulse)</p>
    <p>The nominal periods are 125 ms for follow and 83 ms for lock-on. An 80 ms pulse leaves about 45 ms and 3 ms respectively for everything else. A new frame ID guarantees ordering. A slow successful reply can still steer from an old box. Neither skill checks its age again before issuing the command.</p>
    <h4>What changes at the wheel</h4>
    <dl class="sw-contracts">
    <dt>Turn demand</dt><dd>The first sample seeds the filter. Later samples use 45% new error and 55% previous filtered error. Inside ±1% of image width, turn is zero. Between 1% and 2.5% a floor ramps toward 35%. From 2.5% through 25%, duty stays at 35%. Beyond that it rises with gain 140, up to 45%.</dd>
    <dt>Direction change</dt><dd>The first filtered sample asking for the opposite direction suppresses the turn. A second opposite sample permits it. Entering the stop band clears direction history. Missed detections stop the wheels but retain filter and target-center history.</dd>
    <dt>Approach</dt><dd>Follow sets forward duty to zero for |filtered error| &gt; 0.28 or box height ≥ 0.68. Below that height, positive demand is clamped to 35–45%. The separate 0.82 stop test adds no further stopping range. The robot can hold position when a target comes closer but cannot back away through this rule.</dd>
    <dt>Wheel output</dt><dd>Left = linear + turn. Right = linear − turn. When either wheel exceeds ±70% in the service configuration, L1 scales both down together. A request of (40, 35) becomes (70, 4.7). One wheel can sit below its breakaway duty even when both L2 inputs meet their floors.</dd>
    </dl>
    <h4>Replay a target crossing center</h4><p>These four synthetic detections use the current follow defaults, a constant box height of 0.40 and a clear safety gate. Positive error means the target is right of center. Wheel values are commanded duty percentages.</p>
    <div class="sw-table-scroll"><table class="sw-trace"><thead><tr><th>Frame</th><th>Raw error</th><th>Filtered</th><th>Turn</th><th>Left / right</th><th>Decision</th></tr></thead><tbody>
    <tr><th>1</th><td>+0.140</td><td>+0.140</td><td>+35</td><td>70 / 0</td><td>Turn right</td></tr>
    <tr><th>2</th><td>−0.080</td><td>+0.041</td><td>0</td><td>35 / 35</td><td>Target crossed left. Suppress the old right turn.</td></tr>
    <tr><th>3</th><td>−0.080</td><td>−0.013</td><td>0</td><td>35 / 35</td><td>Hold reversal. Forward drive continues.</td></tr>
    <tr><th>4</th><td>−0.080</td><td>−0.043</td><td>−35</td><td>0 / 70</td><td>Turn left</td></tr>
    </tbody></table></div>
    <p>For scale, the spatial map assumes 1.611 rad/s at turn duty 35. At that steady rate an 80 ms pure-turn pulse would rotate 7.4°. That is a model prediction. The calibration segments span seconds, and the pulse starts from rest. Measuring the actual angle of one pulse is more informative than tuning gain against the map estimate.</p><p>Lock-on feeds the same errors into steering with zero linear demand. Its second and third pulses command two stopped wheels. The same sign filter can therefore produce a different path in follow.</p>
    <p class="sw-source">Code path · perception/vision.py · skills/follow.py · skills/lock_on.py · skills/runtime.py · skills/tuning.py · robot_api.py (SkillMovement.turn, _velocity) · hardware/motion.py</p>
    <a class="jump" href="#software/diagnosis">Trace a tracking fault →</a></article>`;
  }

  function diagnosticSheet() {
    return `<article class="sw-reading"><p class="sw-kicker">REIMPLEMENTATION · DIAGNOSTIC CHECKS</p>
    <h3>Which stage made the error?</h3>
    <p>The reported symptom is alternating under- and overcorrection. A box crossing center, a late steering reversal and a wheel still turning after stop can look identical in cockpit video. Check them in this order.</p>
    <ol class="sw-faults">
    <li><h4>Observation delay or controller lag?</h4><p>Join each detection to its Pi frame ID. Compare raw and filtered error signs at the command. If the raw sign has already changed but the filter or reversal guard persists, replay those boxes through L2. If both signs agreed at frame time but the target has crossed by actuation, measure frame-to-command age. Replay the same boxes with the original and delayed timestamps. The current filter advances once per observation, so an extra 100 ms changes its wall-clock lag without changing its output sequence.</p></li>
    <li><h4>Stiction, saturation or coast?</h4><p>Use a fixed target and repeat short pulses on the same surface, first turning in place, then adding forward duty. Record each wheel’s requested and capped duty, time to first wheel motion, yaw at stop, and yaw after settling. Separate left from right and positive from negative. Repeated zero travel at low duty identifies breakaway. Extra travel after duty reaches zero identifies coast. A clipped outer wheel and a stalled inner wheel point to the mixer. The existing one-shot calibration can measure target shift after settling.</p></li>
    <li><h4>Did the same object stay selected?</h4><p>Replay two instances of the same label crossing, then a short occlusion. Log every candidate box, score and selected center. A label match plus proximity can switch identity. Lock-on accepts a track ID at its entry point but never uses it to choose a box. A missed frame also leaves the old steering state in place for reacquisition.</p></li>
    <li><h4>Did L1 accept the request?</h4><p>Replay an L0 veto on a combined forward-and-turn pulse. RobotAPI stops both wheels and returns the veto. The timed helper discards that return value, so follow can report nonzero demand after the gate rejected it. Record requested, accepted and observed motion separately. Also replay overlapping UDP and skill input. The UDP receiver calls RobotAPI directly and bypasses the web skill claim.</p></li>
    </ol>
    <h4>What the saved runs can tell us</h4>
    <div class="sw-table-scroll"><table class="sw-trace"><thead><tr><th>Turn duty</th><th>Frame pairs</th><th>Median phase-correlation score</th><th>Below runtime cutoff 0.08</th></tr></thead><tbody>
    <tr><th>35</th><td>117</td><td>0.905</td><td>0</td></tr><tr><th>40</th><td>86</td><td>0.859</td><td>5</td></tr><tr><th>45</th><td>70</td><td>0.810</td><td>3</td></tr><tr><th>50</th><td>27</td><td>0.206</td><td>4</td></tr>
    </tbody></table></div>
    <p>One marked segment per duty, using start &lt; frame ≤ stop in <code>calibrations/odometry/segments.csv</code> and the corresponding <code>samples.csv</code>. Visual shift estimates lose confidence sharply in the 50 run. The 25 segment has only one frame pair. These recordings do not establish either wheel’s start threshold for an 80 ms pulse. Follow and lock-on currently steer from box centers alone.</p>
    <h4>Faults outside the tracking loop</h4>
    <dl class="sw-contracts">
    <dt>L0 · Camera loss</dt><dd>Freeze the gray frame while requesting forward travel. The guard should veto a frame older than 0.5 s even if JPEG streaming or Mac detection appears healthy. Check the frame age and edge reason before attributing a stopped wheel to friction. Repeated checks of one frame must not count as new evidence.</dd>
    <dt>L1 · Lost command source</dt><dd>Interrupt the command stream. Verify the zero-duty write after the configured 0.75 s timeout plus watchdog polling delay. Record physical rest separately. The normal tracking pulse issues its own stop at 80 ms.</dd>
    <dt>Map · Pose drift</dt><dd>Compare command-integrated yaw with independently observed yaw over repeated pulses. A stalled wheel still advances the map prediction. The stored turn-rate table even assigns a faster turn to duty 30 than 35 (2.246 vs 1.611 rad/s). A rough landmark can mislead L3 while L2 continues to use a correct box.</dd>
    <dt>L3 · Late plan</dt><dd>Delay the planner and move the target between observation and reply. The Pi validates the action schema and checks cancellation after the call. It has no general observation-age cutoff at dispatch. Check that an explicit stop discards the reply, and that target-directed skills reacquire the correct object when the scene changes.</dd>
    </dl>
    <h4>What to carry into a rewrite</h4><dl class="sw-contracts">
    <dt>Join one cycle</dt><dd>Carry frame ID, Pi frame-ready time, request start/end, selected box, raw/filtered error, reversal decision, L0 verdict, applied left/right duty and actual stop time in one record. Add observed wheel onset or independent yaw for physical tests. Keep elapsed-time measurements on one monotonic clock.</dd>
    <dt>Use existing signals</dt><dd><code>/api/state</code> exposes the latest skill and motor status. <code>/api/detections</code> exposes snapshot, round-trip and inference times. These are snapshots with different update times. The residual called network_ms also includes server and HTTP overhead. The map integrates commanded wheel motion and cannot confirm travel.</dd>
    <dt>Compare revisions</dt><dd>On identical box sequences and timed dropouts, compare wrong-sign pulses, reversals and time spent acting on old observations. On matched physical runs, compare peak overshoot, settling time within a stated image tolerance, target loss rate and zero-motion pulses per wheel. Keep the L0 forward veto, cancellation stop and L1 watchdog as separate pass/fail checks.</dd>
    </dl><p class="sw-source">Evidence · progress.md (May 28 and June 13) · calibrations/turn_centering.py · perception/receiver.py · perception/odometry/{angular,runtime}.py · hardware/motion_udp.py · tests/test_skills.py</p></article>`;
  }

  let activeFlow = 'overview';
  let selectedId = 'boot';
  let boardEl = null;
  let detailEl = null;

  function currentFlow() {
    return flows.find((f) => f.id === activeFlow) || flows[0];
  }

  function renderToolbar() {
    const btns = flows
      .map(
        (f) =>
          `<button type="button" class="sw-btn" data-sw-flow="${f.id}" aria-pressed="${activeFlow === f.id}">${f.label}</button>`
      )
      .join('');
    return (
      `<div class="sw-toolbar">` +
      `<div class="sw-flows" role="group" aria-label="Runtime flow highlight">` +
      `<span class="sw-label">Trace loop</span>${btns}` +
      `</div>` +
      `<p class="sw-caption" id="sw-caption">${currentFlow().caption}</p>` +
      `</div>`
    );
  }

  function renderGraph() {
    const edgesSvg = edges
      .map((e, idx) => {
        const cls = `sw-edge${e.subtle ? ' is-subtle' : ''}`;
        const markerStart = e.bi ? ' marker-start="url(#sw-arrow)"' : '';
        const lbl = e.label
          ? `<text class="sw-edge-label${e.subtle ? ' is-subtle' : ''}" data-sw-elabel="${idx}" x="${e.lx}" y="${e.ly}" text-anchor="${e.anchor}">${e.label}</text>`
          : '';
        return (
          `<path class="${cls}" data-sw-edge="${idx}" data-from="${e.from}" data-to="${e.to}" data-flows="${e.flows.join(' ')}" d="${e.d}" marker-end="url(#sw-arrow)"${markerStart}>` +
          `<title>${modules[e.from].name} → ${modules[e.to].name}${e.label ? ' (' + e.label + ')' : ''}</title></path>${lbl}`
        );
      })
      .join('');

    const nodesSvg = nodes
      .map((n) => {
        const mod = modules[n.id];
        return (
          `<a class="sw-node tier-${n.tier}" data-sw-mod="${n.id}" href="#software/${n.id}" aria-label="${mod.name}">` +
          `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="3"/>` +
          `<text class="sw-tag" x="${n.x + 11}" y="${n.y + 15}">${n.tag}</text>` +
          `<text class="sw-name" x="${n.x + 11}" y="${n.y + 33}">${mod.name}</text>` +
          `<text class="sw-meta" x="${n.x + 11}" y="${n.y + 47}">${n.meta}</text>` +
          `</a>`
        );
      })
      .join('');

    // Clean Control Hierarchy Reference Card in open bottom-right space
    const hierarchyCard =
      `<g class="sw-key" transform="translate(700 342)">` +
      `<rect x="0" y="0" width="212" height="162" rx="3" class="sw-key-box"/>` +
      `<text x="12" y="20" class="sw-key-head">4-LEVEL CONTROL STACK</text>` +
      `<line x1="12" y1="28" x2="200" y2="28" class="sw-key-rule"/>` +
      `<text x="12" y="49" class="sw-key-lv">L3</text><text x="34" y="49" class="sw-key-txt">Autonomy · VLM planner</text>` +
      `<text x="12" y="75" class="sw-key-lv">L2</text><text x="34" y="75" class="sw-key-txt">Skills · find / go_to / push</text>` +
      `<text x="12" y="101" class="sw-key-lv">L1</text><text x="34" y="101" class="sw-key-txt">Motion · sole motor owner</text>` +
      `<text x="12" y="127" class="sw-key-lv is-l0">L0</text><text x="34" y="127" class="sw-key-txt">Safety · 20 Hz edge veto</text>` +
      `<line x1="12" y1="139" x2="200" y2="139" class="sw-key-rule"/>` +
      `<text x="12" y="153" class="sw-key-foot">Higher levels never drive PWM.</text>` +
      `</g>`;

    return (
      `<div class="sw-stage"><svg class="sw-svg" viewBox="0 0 940 524" aria-label="Mischief Bot software architecture">` +
      `<defs><marker id="sw-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse"><path d="M1 1.2L7 4L1 6.8Z" fill="context-stroke"/></marker></defs>` +
      // Zone 1: Raspberry Pi
      `<rect class="sw-zone" x="14" y="14" width="616" height="500" rx="4"/>` +
      `<text class="sw-zone-title" x="32" y="32">RASPBERRY PI  ·  raspberrypi.local</text>` +
      `<text class="sw-zone-sub" x="612" y="32" text-anchor="end">USB-BOOTED DEBIAN TRIXIE</text>` +
      `<line class="sw-band-rule" x1="32" y1="114" x2="604" y2="114"/>` +
      // Wi-Fi divider
      `<line class="sw-divider" x1="651" y1="14" x2="651" y2="514"/>` +
      `<rect x="638" y="390" width="26" height="82" rx="3" class="sw-wifi-pill"/>` +
      `<text class="sw-divider-label" x="654.5" y="431" text-anchor="middle" transform="rotate(-90 654.5 431)">WI-FI LAN</text>` +
      // Zone 2: Offboard Mac / GPU
      `<rect class="sw-zone sw-zone-offboard" x="682" y="14" width="244" height="302" rx="4"/>` +
      `<text class="sw-zone-title" x="700" y="32">OFFBOARD MAC / GPU</text>` +
      `<text class="sw-zone-sub" x="700" y="48">192.168.0.24 · HTTP JSON</text>` +
      `<text class="sw-zone-sub" x="700" y="80">Heavy vision &amp; VLM inference</text>` +
      `<text class="sw-zone-sub" x="700" y="95">runs offboard so the Pi stays</text>` +
      `<text class="sw-zone-sub" x="700" y="110">responsive for 20 Hz safety.</text>` +
      edgesSvg +
      nodesSvg +
      hierarchyCard +
      `</svg></div>`
    );
  }

  function applyHighlight() {
    if (!boardEl) return;
    const flow = currentFlow();
    const fSet = flow.nodes ? new Set(flow.nodes) : null;

    boardEl.querySelectorAll('[data-sw-mod]').forEach((el) => {
      const id = el.dataset.swMod;
      el.classList.toggle('active', id === selectedId);
      el.classList.toggle('dim', Boolean(fSet && !fSet.has(id)));
    });

    boardEl.querySelectorAll('[data-sw-edge]').forEach((el) => {
      const idx = el.dataset.swEdge;
      const from = el.dataset.from;
      const to = el.dataset.to;
      const edgeFlows = (el.dataset.flows || '').split(' ');
      const inFlow = activeFlow === 'overview' || edgeFlows.includes(activeFlow);
      const touchesSelected = from === selectedId || to === selectedId;
      const hot = activeFlow === 'overview' ? touchesSelected : inFlow;
      const dim = activeFlow === 'overview' ? false : !inFlow;

      el.classList.toggle('hot', hot);
      el.classList.toggle('dim', dim);

      const lbl = boardEl.querySelector(`[data-sw-elabel="${idx}"]`);
      if (lbl) {
        lbl.classList.toggle('hot', hot);
        lbl.classList.toggle('dim', dim);
      }
    });

    const cap = boardEl.querySelector('#sw-caption');
    if (cap) cap.textContent = flow.caption;
  }

  function renderDetail(id) {
    if (!detailEl || !modules[id]) return;
    selectedId = id;
    const m = modules[id];
    detailEl.replaceChildren();

    const add = (parent, tag, text, cls) => {
      const el = document.createElement(tag);
      if (text) el.textContent = text;
      if (cls) el.className = cls;
      parent.append(el);
      return el;
    };

    add(detailEl, 'span', m.eyebrow, 'over');
    add(detailEl, 'h2', m.name);

    const badges = add(detailEl, 'div', '', 'sw-badges');
    add(badges, 'span', m.host, 'sw-badge');
    add(badges, 'span', m.layer, 'sw-badge');

    add(detailEl, 'p', m.summary);

    const dl = add(detailEl, 'dl');
    add(dl, 'dt', 'INTERFACES');
    add(dl, 'dd', m.interfaces);
    add(dl, 'dt', 'SOURCE');
    add(dl, 'dd', m.sources);

    if (m.specs && m.specs.length) {
      const table = add(detailEl, 'table', '', 'sw-spec');
      for (const [k, v] of m.specs) {
        const tr = add(table, 'tr');
        add(tr, 'th', k);
        add(tr, 'td', v);
      }
    }

    if (m.jumps && m.jumps.length) {
      const links = add(detailEl, 'div', '', 'detail-actions');
      for (const [hash, label] of m.jumps) {
        const a = add(links, 'a', label, 'jump');
        a.href = '#' + hash;
      }
    }

    applyHighlight();
  }

  function drawBoard() {
    if (!boardEl) return;
    const content = section === 'overview' ? renderToolbar() + renderGraph() + levelContracts()
      : section === 'tracking' ? trackingSheet() : diagnosticSheet();
    boardEl.innerHTML = sectionLinks() + content;
    boardEl.scrollLeft = 0;

    boardEl.querySelectorAll('[data-sw-flow]').forEach((btn) => {
      btn.addEventListener('click', () => {
        activeFlow = btn.dataset.swFlow || 'overview';
        boardEl.querySelectorAll('[data-sw-flow]').forEach((b) => {
          b.setAttribute('aria-pressed', String(b.dataset.swFlow === activeFlow));
        });
        applyHighlight();
      });
    });

    applyHighlight();
  }

  // Legacy & cross-sheet aliases map cleanly onto the 10-module planar model
  const aliases = {
    usb_bootfs: 'boot',
    systemd: 'boot',
    cockpit: 'api',
    web_server: 'api',
    robot_api: 'api',
    cockpit_ui: 'api',
    frames: 'camera',
    odometry: 'camera',
    scene: 'vision',
    spatial_map: 'vision',
    auto: 'autonomy',
    detect: 'yolo',
    yolo_server: 'yolo',
    planner: 'vlm',
    vlm_shim: 'vlm',
    vlm_model: 'vlm'
  };

  NS.resolveId = function (id) {
    if (id && modules[id]) return id;
    if (id && aliases[id]) return aliases[id];
    return 'boot';
  };

  NS.mount = function (board, detail, id) {
    boardEl = board;
    detailEl = detail;
    section = null;
    activeFlow = 'overview';
    NS.inspect(id);
    document.getElementById('sheets')?.scrollIntoView({block: 'start'});
  };

  NS.inspect = function (id) {
    const next = id === 'tracking' || id === 'diagnosis' ? id : 'overview';
    if (next !== section) {
      section = next;
      drawBoard();
    }
    const owner = section === 'tracking' ? 'skills' : section === 'diagnosis' ? 'motion' : id;
    renderDetail(NS.resolveId(owner));
  };

  window.MischiefSoftware = NS;
})();
