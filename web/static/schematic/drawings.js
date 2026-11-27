// Orthographic component drawings grounded in Mischief Bot's real-life hardware.
// ViewBox for all illustrations: 0 0 184 84
const el = (tag, attrs = '') => `<${tag} ${attrs}/>`;
const rect = (x, y, w, h, r = 0, cls = '') =>
  `<rect x="${x}" y="${y}" width="${w}" height="${h}"${r ? ` rx="${r}"` : ''}${cls ? ` class="${cls}"` : ''}/>`;
const circ = (cx, cy, r, cls = '') =>
  `<circle cx="${cx}" cy="${cy}" r="${r}"${cls ? ` class="${cls}"` : ''}/>`;
const ln = (x1, y1, x2, y2, cls = '') =>
  `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"${cls ? ` class="${cls}"` : ''}/>`;
const pth = (d, cls = '') => `<path d="${d}"${cls ? ` class="${cls}"` : ''}/>`;
const rep = (n, fn) => Array.from({ length: n }, (_, i) => fn(i)).join('');

// Yellow TT dual-shaft gearmotor (brushed 130 DC can + rectangular gearbox + mounting bracket)
function ttMotor(side) {
  const inner =
    // Cylindrical 130 DC motor can (right side before mirror)
    rect(112, 24, 34, 34, 3, 'fill-body') +
    pth('M146 27 h4 a3 3 0 0 1 3 3 v22 a3 3 0 0 1 -3 3 h-4', 'fill-dark') +
    // Two brass solder lugs at rear endbell
    rect(153, 31, 6, 4, 1, 'fill-accent') +
    rect(153, 47, 6, 4, 1, 'fill-accent') +
    // Motor can vent & seam lines
    ln(118, 24, 118, 58, 'thin') +
    rect(125, 34, 13, 14, 1, 'thin') +
    // Rectangular TT plastic gearbox housing
    rect(34, 21, 78, 40, 4, 'fill-warm') +
    // Mounting screw bosses & rear tab
    rect(48, 15, 16, 6, 1.5, 'fill-body thin') +
    rect(48, 61, 16, 6, 1.5, 'fill-body thin') +
    // Clear acrylic T-bracket outline on gearbox waist
    rect(72, 17, 7, 48, 1, 'dash') +
    // Dual-shaft output boss (double-D white shaft)
    circ(56, 41, 11, 'fill-paper') +
    circ(56, 41, 6.5, 'fill-body thin') +
    pth('M52.5 38 h7 v6 h-7 z', 'fill-accent') +
    // Gearbox alignment holes & stiffening ribs
    circ(95, 31, 2.3, 'fill-paper thin') +
    circ(95, 51, 2.3, 'fill-paper thin') +
    ln(79, 25, 108, 25, 'thin') +
    ln(79, 57, 108, 57, 'thin') +
    // Channel tag
    `<text x="${side === 'L' ? 40 : 40}" y="11" class="lbl">${side === 'L' ? 'CH A · LEFT' : 'CH B · RIGHT'}</text>`;

  return side === 'R'
    ? `<g transform="translate(184 0) scale(-1 1)">${inner.replace(/<text[^>]*>.*?<\/text>/, '')}</g><text x="116" y="11" class="lbl">CH B · RIGHT</text>`
    : inner;
}

const illustrations = {
  // 01. Anker PowerCore brick: rounded black body, embossed ANKER, 4 blue LEDs, side button, 2 USB ports
  bank:
    // Main brick body + top bevel
    rect(30, 14, 124, 54, 10, 'fill-dark') +
    rect(35, 19, 114, 44, 7, 'fill-body thin') +
    // Dual USB-A ports on left end edge
    rect(25, 25, 6, 12, 1.5, 'fill-paper') +
    rect(25, 45, 6, 12, 1.5, 'fill-paper') +
    // Micro-USB input notch on top-right rim
    rect(128, 12, 12, 3, 1, 'fill-paper thin') +
    // Side power button + 4 status LED dots (matching front-left face in photos)
    circ(45, 53, 3.6, 'fill-paper thin') +
    rep(4, (i) => circ(57 + i * 6.5, 53, 1.7, 'fill-accent')) +
    // Embossed ANKER wordmark
    '<text x="92" y="42" text-anchor="middle" class="wordmark">ANKER</text>',

  // 02. Pi power cable: USB-A plug wrapping to right-angle power plug
  picable:
    // Smooth rubber jacket curve
    pth('M44 50 C70 76 106 10 136 32', 'cable-outer') +
    pth('M44 50 C70 76 106 10 136 32', 'cable-inner') +
    // Left USB-A plug body + metal shroud
    '<g transform="rotate(-24 38 46)">' +
    rect(26, 36, 18, 22, 2.5, 'fill-dark') +
    rect(29, 25, 12, 11, 1, 'fill-paper') +
    ln(33, 28, 33, 33, 'thin') +
    ln(37, 28, 37, 33, 'thin') +
    '</g>' +
    // Right-angle Pi power connector
    rect(132, 26, 16, 13, 2.5, 'fill-dark') +
    rect(148, 29, 10, 7, 1.5, 'fill-paper') +
    '<text x="92" y="76" text-anchor="middle" class="lbl">USB-A → PI POWER</text>',

  // 03. Motor power cable: braided USB-A branch with strain relief to front adapter
  motorcable:
    // Braided jacket (solid + dashed cross-hatch overlay)
    pth('M42 36 C72 6 112 72 140 42', 'cable-outer') +
    pth('M42 36 C72 6 112 72 140 42', 'cable-braid') +
    // Left USB-A plug
    rect(22, 29, 20, 14, 2, 'fill-dark') +
    rect(12, 31.5, 10, 9, 1, 'fill-paper') +
    ln(16, 34, 16, 38, 'thin') +
    // Right-angle plug feeding VM breakout
    rect(138, 34, 13, 18, 2.5, 'fill-dark') +
    rect(151, 39, 9, 8, 1.5, 'fill-paper') +
    '<text x="92" y="76" text-anchor="middle" class="lbl">BRAIDED · MOTOR BRANCH</text>',

  // 04. Compact USB-C VBUS breakout adapter tucked under front lower deck
  vm:
    // Compact PCB
    rect(56, 20, 68, 44, 3, 'fill-body') +
    // USB-C receptacle on left edge
    rect(42, 31, 19, 22, 3, 'fill-dark') +
    rect(45, 35, 13, 14, 2, 'fill-paper thin') +
    // 4 breakout solder pads on right edge
    rep(4, (i) => circ(114, 28 + i * 9.5, 2.8, i < 2 ? 'fill-accent' : 'fill-paper thin')) +
    // Outgoing VM (+) and GND (-) leads
    pth('M117 28 h28 M117 37.5 h28', 'heavy') +
    // SMD pull-down resistors
    rect(72, 29, 8, 4, 0.5, 'fill-paper thin') +
    rect(72, 51, 8, 4, 0.5, 'fill-paper thin') +
    '<text x="86" y="44" text-anchor="middle" class="lbl">VBUS</text>' +
    '<text x="151" y="30" class="lbl">+VM</text>' +
    '<text x="151" y="41" class="lbl">GND</text>',

  // 05. Raspberry Pi Model B (full-size board matching IMG_20261126_105815.jpg)
  pi:
    // Main PCB with 4 mounting holes
    rect(34, 11, 112, 62, 4, 'fill-body') +
    circ(40, 17, 2.3, 'fill-paper thin') +
    circ(116, 17, 2.3, 'fill-paper thin') +
    circ(40, 67, 2.3, 'fill-paper thin') +
    circ(116, 67, 2.3, 'fill-paper thin') +
    // 40-pin (2x20) GPIO header along top edge
    rect(47, 14, 64, 9, 1, 'fill-paper thin') +
    rep(16, (i) =>
      circ(50 + i * 3.85, 16.8, 0.85, i >= 10 ? 'fill-accent' : '') +
      circ(50 + i * 3.85, 20.2, 0.85, i >= 10 ? 'fill-accent' : '')
    ) +
    // Highlight bracket on active pins 29-40
    rect(86.5, 13, 25.5, 11, 1, 'accent-box') +
    // Wireless metal shield & Broadcom SoC
    rect(42, 29, 17, 14, 1.5, 'fill-dark thin') +
    rect(70, 31, 22, 22, 2, 'fill-dark') +
    rect(75, 36, 12, 12, 1, 'fill-paper thin') +
    // CSI camera ribbon slot
    rect(103, 40, 5, 20, 1, 'fill-accent') +
    // Right edge: RJ45 Ethernet + dual stacked USB-A ports (exact real Pi layout!)
    rect(128, 16, 22, 16, 1.5, 'fill-dark') +
    rect(128, 35, 22, 14, 1.5, 'fill-dark') +
    rect(128, 52, 22, 14, 1.5, 'fill-dark') +
    ln(144, 19, 144, 29, 'thin') +
    // Bottom edge: USB-C power, micro-HDMI, 3.5 mm audio
    rect(46, 67, 13, 8, 1.5, 'fill-paper') +
    rect(65, 68, 10, 7, 1, 'fill-paper thin') +
    rect(80, 68, 10, 7, 1, 'fill-paper thin') +
    rect(96, 66, 9, 9, 1, 'fill-paper thin') +
    // Front red power LED
    circ(39, 58, 1.8, 'fill-accent'),

  // 06. 62 GB USB boot flash drive
  usb:
    // Body casing + grip contour
    rect(38, 25, 78, 34, 6, 'fill-dark') +
    rect(44, 30, 66, 24, 3, 'fill-body thin') +
    // Lanyard loop hole
    circ(49, 42, 3.5, 'fill-paper thin') +
    // Metal USB-A connector shroud + two retention windows
    rect(116, 29, 30, 26, 1.5, 'fill-paper') +
    rect(128, 33, 7, 6, 0.8, 'fill-dark thin') +
    rect(128, 45, 7, 6, 0.8, 'fill-dark thin') +
    '<text x="82" y="45" text-anchor="middle" class="lbl">62 GB · OS</text>',

  // 07. OV5647 wide-angle camera module (matches IMG_20261126_105802.jpg)
  cam:
    // 25x24 mm square PCB with 4 annular mounting holes
    rect(64, 10, 56, 54, 3, 'fill-body') +
    circ(70, 16, 2.8, 'fill-paper') +
    circ(114, 16, 2.8, 'fill-paper') +
    circ(70, 58, 2.8, 'fill-paper') +
    circ(114, 58, 2.8, 'fill-paper') +
    // Square sensor mount & protruding circular M12 wide-angle lens barrel
    rect(75, 19, 34, 34, 4, 'fill-paper thin') +
    circ(92, 36, 16, 'fill-dark') +
    circ(92, 36, 11.5, 'fill-body thin') +
    circ(92, 36, 7.2, 'fill-dark') +
    circ(92, 36, 3.4, 'fill-paper thin') +
    // Optic reflection dot
    circ(89.5, 33.5, 1.2, 'fill-accent') +
    // Bottom 15-pin CSI ZIF connector latch
    rect(75, 60, 34, 11, 1.5, 'fill-paper') +
    rect(73, 66, 38, 4, 1, 'fill-accent') +
    rep(9, (i) => ln(78 + i * 3.5, 61, 78 + i * 3.5, 66, 'thin')),

  // 08. 15-pin flat white FFC ribbon with blue stiffener tab (matches IMG_20261126_105802.jpg)
  ribbon:
    // Graceful S-folded flat ribbon silhouette
    pth('M28 52 C56 52 64 12 94 22 C122 31 124 62 152 44 L156 56 C126 76 116 44 90 35 C64 26 58 66 30 66 Z', 'fill-paper') +
    // Fine parallel conductor traces along the FFC
    rep(4, (i) =>
      pth(`M${29} ${55 + i * 2.8} C57 ${55 + i * 2.8} 64 ${15 + i * 2.8} 93 ${25 + i * 2.8} C121 ${34 + i * 2.8} 124 ${65 + i * 2.8} 153 ${47 + i * 2.8}`, 'thin')
    ) +
    // Distinctive blue stiffener tab at camera end + contact fingers
    rect(18, 50, 12, 18, 1.5, 'fill-accent') +
    rect(14, 52, 4, 14, 0.5, 'fill-paper thin') +
    // Pi end stiffener
    rect(152, 43, 11, 16, 1.5, 'fill-dark'),

  // 09. Red SparkFun-style TB6612FNG breakout (exact 2x8 pins visible in IMG_20261126_105815.jpg)
  driver:
    // Compact red breakout PCB (tinted accent fill)
    rect(48, 12, 88, 60, 3, 'fill-red') +
    // Top 8 header pins (PWMA..GND) & Bottom 8 header pins (VM..GND)
    rep(8, (i) =>
      circ(57 + i * 10, 19, 2.3, 'fill-paper') +
      circ(57 + i * 10, 65, 2.3, 'fill-paper')
    ) +
    // Center SSOP-24 TB6612FNG IC + gull-wing pins
    rect(78, 32, 28, 20, 1.5, 'fill-dark') +
    rep(7, (i) => ln(80 + i * 4, 28, 80 + i * 4, 32, 'thin') + ln(80 + i * 4, 52, 80 + i * 4, 56, 'thin')) +
    circ(82, 36, 1.2, 'fill-paper') +
    // Decoupling capacitors flanking IC
    rect(59, 36, 8, 12, 1, 'fill-paper thin') +
    rect(117, 36, 8, 12, 1, 'fill-paper thin') +
    '<text x="92" y="10" text-anchor="middle" class="lbl">PWMA · AIN · STBY · BIN · PWMB</text>' +
    '<text x="92" y="81" text-anchor="middle" class="lbl">VM · VCC · GND · AO1/2 · BO1/2</text>',

  // 10. Custom female-to-female DuPont GPIO jumper bundle (9 leads)
  harness:
    // 9 individual gently fanned jumper leads
    rep(7, (i) =>
      pth(`M42 ${20 + i * 6.5} C76 ${20 + i * 6.5} 106 ${23 + i * 6.2} 140 ${23 + i * 6.2}`, i % 2 === 0 ? '' : 'thin')
    ) +
    // Stacked black DuPont female housings on Pi side (left)
    rect(24, 16, 18, 49, 1.5, 'fill-dark') +
    rep(7, (i) => ln(24, 23 + i * 6.5, 42, 23 + i * 6.5, 'thin')) +
    // Stacked DuPont housings on driver side (right)
    rect(140, 19, 18, 46, 1.5, 'fill-dark') +
    rep(7, (i) => ln(140, 25.5 + i * 6.2, 158, 25.5 + i * 6.2, 'thin')) +
    '<text x="92" y="79" text-anchor="middle" class="lbl">PINS 29–40 → TB6612FNG</text>',

  // 11 & 12. Left and Right yellow TT gearmotors (mirrored)
  left: ttMotor('L'),
  right: ttMotor('R'),

  // 13. Drive wheels x2 — real 5-spoke bright yellow star rim + chunky chevron tire!
  wheels:
    // Outer rubber tire with chunky diagonal tread blocks
    circ(92, 42, 34, 'fill-dark') +
    rep(18, (i) => `<g transform="rotate(${i * 20} 92 42)">${rect(89.5, 7.5, 5, 5, 1, 'fill-paper thin')}</g>`) +
    // Tire sidewall inner lip & yellow rim outer barrel
    circ(92, 42, 26, 'fill-warm') +
    circ(92, 42, 22, 'fill-paper thin') +
    // Authentic 5-spoke star hub (matches every single photo!)
    rep(5, (i) =>
      `<g transform="rotate(${i * 72 - 18} 92 42)">${pth('M87 21 L97 21 L94.5 36 L89.5 36 Z', 'fill-warm')}</g>`
    ) +
    // Recessed center hub + double-D bore
    circ(92, 42, 8.5, 'fill-warm') +
    rect(89.5, 39.5, 5, 5, 1, 'fill-paper thin'),

  // 14. Decks & standoffs — real 2-tier slotted 2WD chassis + 4 hexagonal brass standoffs!
  chassis:
    // Lower deck (brown kraft-backed plate with mounting holes)
    pth('M28 57 Q44 47 92 47 Q140 47 156 57 Q140 69 92 69 Q44 69 28 57 Z', 'fill-warm') +
    pth('M28 60 Q44 72 92 72 Q140 72 156 60', 'thin') +
    // 4 tall hexagonal brass standoffs separating lower & upper decks
    rect(50, 29, 6, 27, 0.5, 'fill-dark') +
    rect(128, 29, 6, 27, 0.5, 'fill-dark') +
    rect(72, 35, 6, 27, 0.5, 'fill-dark') +
    rect(106, 35, 6, 27, 0.5, 'fill-dark') +
    // Clear slotted upper acrylic deck
    pth('M28 24 Q44 13 92 13 Q140 13 156 24 Q140 36 92 36 Q44 36 28 24 Z', 'fill-paper') +
    // Signature parallel front/rear mounting slots on upper acrylic deck
    ln(44, 21, 66, 21, 'thin') +
    ln(44, 26, 66, 26, 'thin') +
    ln(118, 21, 140, 21, 'thin') +
    ln(118, 26, 140, 26, 'thin') +
    // Standoff hex nuts on top deck
    circ(53, 28, 2.2, 'fill-accent') +
    circ(131, 28, 2.2, 'fill-accent') +
    circ(75, 33, 2.2, 'fill-accent') +
    circ(109, 33, 2.2, 'fill-accent'),

  // 15. Swivel casters x2 — square plate, stamped steel fork, white cylindrical nylon roller!
  caster:
    // Top square mounting plate + brass mounting bolts
    rect(54, 12, 76, 7, 1.5, 'fill-dark') +
    rect(61, 8, 6, 4, 0.5, 'fill-body thin') +
    rect(117, 8, 6, 4, 0.5, 'fill-body thin') +
    // Swivel ball-bearing turret collar
    rect(70, 19, 44, 9, 2, 'fill-body') +
    // Stamped steel fork yoke
    pth('M72 28 L66 56 L74 56 L79 34 H105 L110 56 L118 56 L112 28 Z', 'fill-dark') +
    // Wide white cylindrical nylon roller (matches IMG_20261126_105815.jpg!)
    rect(75, 39, 34, 34, 6, 'fill-paper') +
    ln(82, 39, 82, 73, 'thin') +
    ln(102, 39, 102, 73, 'thin') +
    // Center axle pin & rivet
    ln(64, 56, 120, 56, 'dash') +
    circ(70, 56, 2.5, 'fill-paper') +
    circ(114, 56, 2.5, 'fill-paper'),

  // 16. Slotted encoder discs — 20-slot black optical speed disc with double-D bore
  discs:
    circ(92, 42, 31, 'fill-dark') +
    rep(20, (i) => `<g transform="rotate(${i * 18} 92 42)">${rect(90.5, 14, 3, 9.5, 0.8, 'fill-paper thin')}</g>`) +
    circ(92, 42, 13, 'fill-body thin') +
    // Double-D TT shaft bore
    pth('M88 38.5 h8 a4 4 0 0 1 0 7 h-8 a4 4 0 0 1 0 -7 z', 'fill-paper')
};
