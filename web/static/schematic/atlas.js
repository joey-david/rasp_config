// Hardware component registry, assembly trays, and electrical wiring sheet.
// Grounded directly in the physical robot build, photos, USB boot volume, and repository code.
const parts = {
  pi: [
    'Raspberry Pi',
    'Onboard computer',
    'The Raspberry Pi sits lengthwise between the decks with its USB ports facing the rear, opposite the camera. Boots Raspberry Pi OS 64-bit (Debian Trixie) from the USB stick and hosts camera capture, safety, motion, skills, and the web cockpit.',
    'Power cable · USB storage · CSI ribbon · GPIO pins 29–40',
    'robot_api.py · systemd/mischief-bot.service · bootfs/issue.txt'
  ],
  bank: [
    'Portable battery',
    'Anker · dual-branch power',
    'Matte-black Anker power bank strapped atop the upper acrylic deck. One USB output powers the Raspberry Pi; the second feeds the motor power adapter. Four blue LEDs sit on the front-left bezel. Exact model and capacity are unreadable.',
    '2× USB-A outputs → Pi cable and motor branch',
    'Build photos · owner notes'
  ],
  picable: [
    'Pi power cable',
    'Power branch 1',
    'Black USB power lead wrapping from the Anker pack around the rear edge to the Raspberry Pi power input.',
    'Anker USB-A → Raspberry Pi power input',
    'Build photos · owner notes'
  ],
  motorcable: [
    'Motor power cable',
    'Power branch 2',
    'Braided black USB lead running from the second Anker output, under the clear deck, to the front motor power adapter.',
    'Anker USB-A → front USB-C power adapter',
    'Build photos · owner notes'
  ],
  vm: [
    'Power adapter',
    'Motor VM supply',
    'Compact USB-C breakout tucked beneath the front lip of the lower deck. Routes USB VBUS power and common ground to the TB6612FNG VM rail. Exact breakout model and any voltage negotiation remain unverified.',
    'USB-C VBUS → TB6612FNG VM · shared GND',
    'Build photos · hardware/gpio_mappings.yaml'
  ],
  cam: [
    'Camera module',
    'OV5647 · wide-angle CSI',
    'Wide-angle OV5647 CSI board (confirmed via dtoverlay=ov5647 in bootfs/config.txt) mounted on the front face of the Anker pack. Feeds the cockpit stream, YOLO detector, 20 Hz edge safety, and visual odometry.',
    '15-pin CSI ZIF connector → flat ribbon → Pi',
    'perception/camera.py · bootfs/config.txt'
  ],
  ribbon: [
    'Camera ribbon',
    '15-pin FFC flex cable',
    'Flat white AWM-20624 FFC ribbon with a blue stiffener tab at the camera end. Loops through the front slot of the clear upper deck into the Pi CSI port.',
    'Camera ZIF ↔ Pi CSI port',
    'Build photos · Raspberry Pi camera docs'
  ],
  usb: [
    'USB stick',
    '62 GB boot storage',
    'Holds Raspberry Pi OS 64-bit (Debian Trixie) across a 536.9 MB FAT32 bootfs partition and a 61.4 GB ext4 rootfs partition containing all robot code and configs.',
    'USB-A storage → Raspberry Pi boot',
    'bootfs/config.txt · cmdline.txt · /dev/disk4'
  ],
  driver: [
    'Motor driver',
    'Toshiba TB6612FNG',
    'Red SparkFun-style TB6612FNG dual H-bridge breakout mounted at the rear of the lower deck. Switches external VM power to both motors using 3.3 V Pi logic and common ground.',
    'PWMA/B · AIN1/2 · BIN1/2 · STBY · VM · VCC · GND',
    'hardware/gpio_mappings.yaml · build photos · Toshiba datasheet'
  ],
  harness: [
    'GPIO harness',
    'Custom F–F DuPont leads',
    'Custom-length female-to-female jumper wires carrying 1 kHz PWM, direction, standby, 3.3 V logic power, and ground from Pi physical pins 29–40 to the red driver header.',
    'Pi GPIO pins 29–40 → TB6612FNG control header',
    'hardware/gpio_mappings.yaml · progress.md'
  ],
  left: [
    'Left DC motor',
    'Yellow TT gearmotor · Ch A',
    'Brushed 130 DC motor with a yellow dual-shaft TT gearbox, clamped under the lower deck with a clear acrylic bracket. Reversed in software by default. Exact gear ratio is unconfirmed.',
    'TB6612FNG AO1 / AO2 → left wheel shaft',
    'Underside capture · hardware/motors.py'
  ],
  right: [
    'Right DC motor',
    'Yellow TT gearmotor · Ch B',
    'Second yellow TT gearmotor driving the right wheel. Independent channel control lets the robot spin in place within the calibrated 35–45 power band.',
    'TB6612FNG BO1 / BO2 → right wheel shaft',
    'Underside capture · hardware/motors.py'
  ],
  wheels: [
    'Drive wheels ×2',
    '5-spoke traction rims',
    'Chunky chevron-tread black rubber tires on 5-spoke bright yellow plastic rims, press-fit onto the outer TT gearbox shafts.',
    'Left & right outer gearbox double-D shafts',
    'Build photos · underside capture'
  ],
  chassis: [
    'Decks & standoffs',
    '2-tier 2WD frame',
    'Two slotted oval 2WD kit plates separated by four hexagonal brass standoffs. The upper deck is clear acrylic; the lower deck retains its brown kraft backing and holds the drivetrain, casters, and motor driver.',
    '4× M3 brass hex standoffs + slotted decks',
    'Build photos · underside capture'
  ],
  caster: [
    'Swivel casters ×2',
    'Passive support rollers',
    'Two wide white nylon rollers in stamped-steel swivel forks bolted under the front and rear of the lower deck on short brass standoffs.',
    'Lower deck → front & rear swivel brackets',
    'Build photos · underside capture'
  ],
  discs: [
    'Slotted discs',
    '20-slot encoder wheels',
    'Black 20-slot encoder discs mounted on the inner shafts of both TT gearmotors. Runtime currently estimates motion from wheel commands and camera frames; optical readers are unconfirmed.',
    'Inner TT gearmotor shafts',
    'Underside capture · perception/odometry/'
  ]
};

const board = document.querySelector('#board');
const detail = document.querySelector('#detail');

const sheets = {
  assembly: ['01', 'Component sheet', 'ORTHOGRAPHIC DRAWINGS  /  MATCHED TO BUILD', 'pi'],
  wiring: ['02', 'Electrical connections', 'SCHEMATIC BLOCK DIAGRAM  /  POWER & SIGNAL', 'driver'],
  software: ['03', 'Software architecture', 'PLANAR RUNTIME MAP  /  ZERO-CROSSING FLOWS', 'boot']
};

let sheet;
let selected;

const trays = [
  ['Power distribution', ['bank', 'picable', 'motorcable', 'vm']],
  ['Compute & vision', ['pi', 'usb', 'cam', 'ribbon']],
  ['Motor control', ['driver', 'harness', 'left', 'right']],
  ['Running gear & frame', ['wheels', 'chassis', 'caster', 'discs']]
];

const connections = [
  ['bank', 'picable'], ['bank', 'motorcable'], ['picable', 'pi'], ['motorcable', 'vm'], ['vm', 'driver'],
  ['pi', 'usb'], ['pi', 'ribbon'], ['ribbon', 'cam'], ['pi', 'harness'], ['harness', 'driver'],
  ['driver', 'left'], ['driver', 'right'], ['left', 'wheels'], ['right', 'wheels'],
  ['left', 'discs'], ['right', 'discs'], ['chassis', 'left'], ['chassis', 'right'], ['chassis', 'caster']
];

const captions = {
  bank: 'Supplies both USB branches',
  picable: 'Anker → Pi power input',
  motorcable: 'Anker → front VM adapter',
  vm: 'USB-C VBUS → motor rail',
  pi: 'Boots from USB · runs stack',
  usb: '62 GB Debian Trixie OS',
  cam: 'Wide-angle forward vision',
  ribbon: '15-pin FFC with blue tab',
  driver: 'Red dual H-bridge breakout',
  harness: 'Pi pins 29–40 → driver',
  left: 'Channel A → left wheel',
  right: 'Channel B → right wheel',
  wheels: '5-spoke rims · chevron tread',
  caster: 'Front & rear nylon rollers',
  chassis: 'Clear top · brass standoffs',
  discs: '20-slot inner shaft discs'
};

function assembly() {
  let num = 0;
  return trays
    .map(([name, ids]) => {
      const cards = ids
        .map((id) => {
          num += 1;
          const idx = String(num).padStart(2, '0');
          return (
            `<a class="part" data-part="${id}" href="#assembly/${id}">` +
            `<span class="part-num">${idx}</span>` +
            `<svg aria-hidden="true" viewBox="0 0 184 84">${illustrations[id]}</svg>` +
            `<b>${parts[id][0]}</b>` +
            `<small>${captions[id]}</small>` +
            `</a>`
          );
        })
        .join('');
      return `<h3 class="sectiontitle">${name}</h3><div class="tray">${cards}</div>`;
    })
    .join('');
}

// Planar, zero-crossing electrical wiring diagram (viewBox 0 0 900 436)
const wiringLayout = {
  zones: [
    { x: 14, y: 14, w: 636, h: 174, title: 'POWER DISTRIBUTION', sub: 'SINGLE ANKER PACK · TWO BRANCHES', cls: 'w-zone-power' },
    { x: 14, y: 204, w: 636, h: 192, title: 'COMPUTE, SENSING & CONTROL', sub: 'SHARED GND · 3.3 V LOGIC', subX: 520, cls: 'w-zone-ctrl' },
    { x: 668, y: 14, w: 218, h: 382, title: 'DRIVE ACTUATION', sub: '', cls: 'w-zone-drive' }
  ],
  nodes: [
    // Power distribution
    { id: 'bank',       x: 28,  y: 78,  w: 162, h: 48, sub: '2× USB OUTPUT',    kind: 'power' },
    { id: 'motorcable', x: 230, y: 46,  w: 174, h: 48, sub: 'BRANCH 2 · BRAID', kind: 'power' },
    { id: 'vm',         x: 464, y: 46,  w: 172, h: 48, sub: 'USB-C → VBUS',     kind: 'power' },
    { id: 'picable',    x: 230, y: 122, w: 174, h: 48, sub: 'BRANCH 1 · 5 V',   kind: 'power' },
    // Compute, sensing & control
    { id: 'usb',        x: 28,  y: 242, w: 162, h: 48, sub: 'USB 3.0 · BOOT',   kind: 'signal' },
    { id: 'cam',        x: 28,  y: 320, w: 162, h: 48, sub: 'OV5647 · CSI',     kind: 'signal' },
    { id: 'pi',         x: 230, y: 242, w: 174, h: 48, sub: 'CONTROLLER',       kind: 'core' },
    { id: 'driver',     x: 464, y: 242, w: 172, h: 48, sub: 'TB6612FNG',        kind: 'driver' },
    // Actuation column
    { id: 'left',       x: 696, y: 196, w: 172, h: 48, sub: 'CHANNEL A (REV)',  kind: 'drive' },
    { id: 'right',      x: 696, y: 296, w: 172, h: 48, sub: 'CHANNEL B',        kind: 'drive' }
  ],
  edges: [
    // Zero-crossing power rails
    { a: 'bank',       b: 'motorcable', d: 'M190 94 H208 V70 H230',   kind: 'power',  label: '5 V',         lx: 204, ly: 62 },
    { a: 'bank',       b: 'picable',    d: 'M190 110 H208 V146 H230', kind: 'power',  label: '5 V',         lx: 204, ly: 160 },
    { a: 'motorcable', b: 'vm',         d: 'M404 70 H464',            kind: 'power',  label: 'USB',         lx: 434, ly: 62 },
    { a: 'vm',         b: 'driver',     d: 'M550 94 V242',            kind: 'power',  label: 'VM + GND',    lx: 558, ly: 168, anchor: 'start' },
    { a: 'picable',    b: 'pi',         d: 'M317 170 V242',           kind: 'power',  label: '5 V IN',      lx: 325, ly: 222, anchor: 'start' },
    // Sensing & control buses
    { a: 'usb',        b: 'pi',         d: 'M190 266 H230',           kind: 'signal', label: 'EXT4',        lx: 210, ly: 258 },
    { a: 'cam',        b: 'pi',         d: 'M190 344 H210 V278 H230', kind: 'signal', label: 'CSI',         lx: 216, ly: 322, anchor: 'start' },
    { a: 'pi',         b: 'driver',     d: 'M404 266 H464',           kind: 'signal', label: '7× GPIO',     lx: 434, ly: 258, label2: '3.3V · GND', ly2: 280 },
    // Motor channel outputs
    { a: 'driver',     b: 'left',       d: 'M636 256 H662 V220 H696', kind: 'power',  label: 'AO1/2',       lx: 678, ly: 211 },
    { a: 'driver',     b: 'right',      d: 'M636 276 H662 V320 H696', kind: 'power',  label: 'BO1/2',       lx: 678, ly: 335 }
  ]
};

function wiringSvg() {
  const zones = wiringLayout.zones
    .map(
      (z) =>
        `<rect class="w-zone ${z.cls}" x="${z.x}" y="${z.y}" width="${z.w}" height="${z.h}" rx="3"/>` +
        `<text class="w-zone-title" x="${z.x + 12}" y="${z.y + 17}">${z.title}</text>` +
        (z.sub ? `<text class="w-zone-sub" x="${z.subX || z.x + z.w - 12}" y="${z.y + 17}" text-anchor="end">${z.sub}</text>` : '')
    )
    .join('');

  const edges = wiringLayout.edges
    .map((e) => {
      const anchor = e.anchor || 'middle';
      const lbl = e.label
        ? `<text class="w-elabel" data-edge-lbl="${e.a} ${e.b}" x="${e.lx}" y="${e.ly}" text-anchor="${anchor}">${e.label}</text>`
        : '';
      const lbl2 = e.label2
        ? `<text class="w-elabel" data-edge-lbl="${e.a} ${e.b}" x="${e.lx}" y="${e.ly2}" text-anchor="${anchor}">${e.label2}</text>`
        : '';
      return (
        `<path class="wire wire-${e.kind}" data-edge="${e.a} ${e.b}" d="${e.d}">` +
        `<title>${parts[e.a][0]} → ${parts[e.b][0]}</title></path>${lbl}${lbl2}`
      );
    })
    .join('');

  const nodes = wiringLayout.nodes
    .map(
      (n) =>
        `<a class="node node-${n.kind}" data-part="${n.id}" href="#wiring/${n.id}" aria-label="${parts[n.id][0]}">` +
        `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="2.5"/>` +
        `<text class="id" x="${n.x + 10}" y="${n.y + 16}">${n.sub}</text>` +
        `<text class="name" x="${n.x + 10}" y="${n.y + 35}">${parts[n.id][0]}</text>` +
        `</a>`
    )
    .join('');

  const legend =
    `<g class="w-legend" transform="translate(18 416)">` +
    `<line x1="0" y1="0" x2="26" y2="0" class="wire wire-power"/>` +
    `<text x="34" y="3.5">Power rail (5 V USB / motor VM / H-bridge out)</text>` +
    `<line x1="370" y1="0" x2="396" y2="0" class="wire wire-signal"/>` +
    `<text x="404" y="3.5">Data &amp; 3.3 V GPIO control bus</text>` +
    `<text x="864" y="3.5" text-anchor="end" class="w-hint">Hover or click any block to trace</text>` +
    `</g>`;

  return `<svg class="map" viewBox="0 0 900 434" aria-label="Electrical connections">${zones}${edges}${nodes}${legend}</svg>`;
}

function inspect(id) {
  const [name, type, note, port, source] = parts[id];
  board.querySelectorAll('[data-part]').forEach((el) => el.classList.toggle('active', el.dataset.part === id));
  board.querySelectorAll('[data-edge]').forEach((el) => el.classList.toggle('hot', el.dataset.edge.split(' ').includes(id)));
  board.querySelectorAll('[data-edge-lbl]').forEach((el) => el.classList.toggle('hot', el.dataset.edgeLbl.split(' ').includes(id)));

  detail.replaceChildren();
  function append(parent, tag, value) {
    const el = document.createElement(tag);
    el.textContent = value;
    parent.append(el);
    return el;
  }

  append(detail, 'span', type.toUpperCase()).className = 'over';
  append(detail, 'h2', name);
  append(detail, 'p', note);

  if (sheet === 'assembly') {
    const peers = connections.filter((edge) => edge.includes(id)).map((edge) => edge.find((other) => other !== id));
    for (const part of board.querySelectorAll('.part')) part.classList.toggle('related', peers.includes(part.dataset.part));
    const group = append(detail, 'div', '');
    group.className = 'links';
    append(group, 'span', 'CONNECTED PARTS');
    for (const peer of peers) {
      const link = append(group, 'a', parts[peer][0]);
      link.href = '#assembly/' + peer;
    }
  }

  const dl = append(detail, 'dl', '');
  for (const [key, value] of [['INTERFACE', port], ['SOURCE', source]]) {
    append(dl, 'dt', key);
    append(dl, 'dd', value);
  }

  if (id === 'driver') {
    const table = append(detail, 'table', '');
    table.className = 'pins';
    for (const [i, row] of [
      ['Signal', 'BCM', 'Header pin'],
      ['A PWM / IN1 / IN2', '12 / 16 / 6', '32 / 36 / 31'],
      ['B PWM / IN1 / IN2', '13 / 20 / 21', '33 / 38 / 40'],
      ['Standby (STBY)', '26', '37']
    ].entries()) {
      const tr = append(table, 'tr', '');
      row.forEach((value) => append(tr, i === 0 ? 'th' : 'td', value));
    }
  }

  const references = {
    driver: ['Toshiba TB6612FNG datasheet', 'https://toshiba.semicon-storage.com/info/datasheet_en_20141001.pdf?did=10660'],
    cam: ['OV5647 sensor specifications', 'https://www.ovt.com/press-releases/omnivision-introduces-1-4-inch-5-megapixel-raw-sensor-for-high-performance-mobile-applications/'],
    ribbon: ['Raspberry Pi camera pinouts', 'https://www.raspberrypi.com/documentation/accessories/camera.html'],
    left: ['TT gearmotor family reference', 'https://www.adafruit.com/product/3777'],
    right: ['TT gearmotor family reference', 'https://www.adafruit.com/product/3777']
  };

  const actions = append(detail, 'div', '');
  actions.className = 'detail-actions';

  if (references[id]) {
    const [text, url] = references[id];
    const a = append(actions, 'a', text + ' ↗');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.className = 'ref';
  }

  let target;
  if (id === 'pi' || id === 'usb') target = ['software', 'Explore Pi software →'];
  else if (sheet === 'assembly' && !['chassis', 'caster', 'discs'].includes(id)) {
    target = ['wiring/' + ({ wheels: 'left', harness: 'driver', ribbon: 'cam' }[id] || id), 'View wiring →'];
  } else if (sheet === 'wiring' && (id === 'pi' || id === 'cam' || id === 'driver')) {
    target = ['software/' + ({ pi: 'api', cam: 'camera', driver: 'motion' }[id]), 'View software →'];
  }
  if (target) {
    const a = append(actions, 'a', target[1]);
    a.href = '#' + target[0];
    a.className = 'jump';
  }
}

function render() {
  const [page, id] = location.hash.slice(1).split('/');
  const next = Object.hasOwn(sheets, page) ? page : 'assembly';
  const changed = sheet !== next;
  sheet = next;
  const [n, title, type, start] = sheets[sheet];

  if (changed) {
    document.querySelectorAll('nav a').forEach((a) => {
      if (a.hash === '#' + sheet) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    document.querySelector('#fig').textContent = 'FIG. ' + n;
    document.querySelector('#title').textContent = title;
    document.querySelector('#viewtype').textContent = type;
  }

  if (sheet === 'software' && window.MischiefSoftware) {
    if (changed) window.MischiefSoftware.mount(board, detail, id);
    else window.MischiefSoftware.inspect(id);
    return;
  }

  if (changed) {
    board.innerHTML = sheet === 'assembly' ? assembly() : wiringSvg();
    board.scrollLeft = 0;
  }

  selected = Array.from(board.querySelectorAll('[data-part]')).some((el) => el.dataset.part === id) ? id : start;
  inspect(selected);

  if (id && sheet === 'assembly' && matchMedia('(max-width:640px)').matches) {
    const el = board.querySelector('.part.active');
    if (el) {
      board.querySelector('.inline-note')?.remove();
      const copy = document.createElement('span');
      copy.className = 'inline-note';
      copy.textContent = parts[id][2];
      el.append(copy);
    }
  }
}

for (const event of ['pointerover', 'focusin']) {
  board.addEventListener(event, (e) => {
    const sw = e.target.closest('[data-sw-mod]');
    if (sw && window.MischiefSoftware) {
      window.MischiefSoftware.inspect(sw.dataset.swMod);
      return;
    }
    const a = e.target.closest('[data-part]');
    if (a) inspect(a.dataset.part);
  });
}

window.addEventListener('hashchange', render);
render();
