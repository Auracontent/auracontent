// Capital Simple : sprites de Léa et Hugo et accessoires, dessinés en code (outil HORS CI ; les PNG sont
// versionnés dans assets/finance/characters et assets/finance/props, le pipeline ne lance jamais Node).
//
//   ~/.local/node/bin/node tools/finance/draw-assets.mjs            # depuis la racine du dépôt
//
// Repris de videos/interets-composes-b1/tools/draw-assets.mjs (vidéo test) : mêmes graines, donc mêmes PNG
// pour les sprites existants ; ajouts : humeur « neutral » et poses neutre, surprise, montrer du doigt.
// @napi-rs/canvas vient du Skill directing-stickman-videos (STICKMAN_SKILL pour un autre chemin).
//
// Illustrations B1 dessinées en code (route gratuite, sans génération d'images IA).
// Trait d'encre fin et légèrement irrégulier, accents limités : jaune, rouge, vert, encre/marine.
// Chaque sprite est exporté en PNG transparent ; 1 unité = 1 unité du plan de conception (1280 de large).
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const SKILL = process.env.STICKMAN_SKILL || path.join(process.env.HOME, '.claude/skills/directing-stickman-videos');
const require = createRequire(path.join(SKILL, 'package.json'));
const {createCanvas, GlobalFonts} = require('@napi-rs/canvas');
GlobalFonts.registerFromPath(path.resolve('assets/finance/fonts/Caveat.ttf'), 'Caveat');

// personnages (lea-*, hugo-*) et accessoires dans deux dossiers, chacun avec son sprites.json
const ROOT = path.resolve(process.argv[2] || 'assets/finance');
const dirOf = name => path.join(ROOT, /^(lea|hugo)-/.test(name) ? 'characters' : 'props');
for (const d of ['characters', 'props']) fs.mkdirSync(path.join(ROOT, d), {recursive: true});
const DPR = 1.5, INK = '#1d1d1b', NAVY = '#24364f', GREEN = '#3f9b52', RED = '#d6453d', YELLOW = '#f2c230', PAPER = '#FDFDFC';
const manifest = {};

function rng(seed) { return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
let rand = rng(7);
const j = a => (rand() - .5) * 2 * a;

function sprite(name, w, h, draw, meta = {}) {
  const c = createCanvas(Math.ceil(w * DPR), Math.ceil(h * DPR)), ctx = c.getContext('2d');
  ctx.scale(DPR, DPR); ctx.lineCap = 'round'; ctx.lineJoin = 'round';
  rand = rng([...name].reduce((a, ch) => a * 31 + ch.charCodeAt(0) | 0, 11));
  draw(ctx);
  fs.writeFileSync(path.join(dirOf(name), name + '.png'), c.toBuffer('image/png'));
  manifest[name] = {w, h, ...meta};
}
// Catmull-Rom smoothing + small jitter = hand-drawn pen line.
function smooth(pts, steps = 8) {
  if (pts.length < 3) return pts;
  const out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    for (let s = 0; s < steps; s++) { const t = s / steps, t2 = t * t, t3 = t2 * t;
      out.push([0, 1].map(k => .5 * (2 * p1[k] + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3))); }
  }
  out.push(pts.at(-1)); return out;
}
function densify(pts, step = 10) { const out = [pts[0]];
  for (let i = 1; i < pts.length; i++) { const [a, b] = [pts[i - 1], pts[i]], n = Math.max(1, Math.ceil(Math.hypot(b[0] - a[0], b[1] - a[1]) / step));
    for (let k = 1; k <= n; k++) out.push([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n]); } return out; }
function ink(ctx, pts, {w = 4.2, color = INK, wobble = 0.9, close = false, straight = false} = {}) {
  let p = (straight ? densify(pts) : smooth(pts)).map(([x, y]) => [x + j(wobble), y + j(wobble)]);
  if (close) p.push(p[0]);
  ctx.strokeStyle = color;
  for (let i = 1; i < p.length; i++) { ctx.lineWidth = w * (0.85 + rand() * 0.3); ctx.beginPath(); ctx.moveTo(...p[i - 1]); ctx.lineTo(...p[i]); ctx.stroke(); }
}
function blob(ctx, cx, cy, rx, ry, {fill, stroke = INK, w = 4, n = 28} = {}) {
  const pts = Array.from({length: n}, (_, i) => { const a = i / n * Math.PI * 2; return [cx + Math.cos(a) * (rx + j(1.2)), cy + Math.sin(a) * (ry + j(1.2))]; });
  if (fill) { ctx.fillStyle = fill; ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(...p) : ctx.moveTo(...p)); ctx.closePath(); ctx.fill(); }
  if (stroke) ink(ctx, [...pts, pts[0], pts[1]], {w, color: stroke, wobble: .4});
}
function marker(ctx, pts, color, w = 14) { ctx.save(); ctx.globalAlpha = .55; ink(ctx, pts, {w, color, wobble: 1.5}); ctx.restore(); }

// ---------- visage ----------
function face(ctx, cx, cy, r, mood, look = 0) {
  const ex = r * .36, ey = cy - r * .08, lx = look * r * .18;
  const eye = (x, sy = 1) => { ctx.fillStyle = INK; ctx.beginPath(); ctx.ellipse(x + lx, ey, r * .085, r * .13 * sy, 0, 0, Math.PI * 2); ctx.fill(); };
  const brow = (x, tilt, lift = 0) => ink(ctx, [[x - r * .16 + lx, ey - r * .3 - lift + tilt], [x + r * .16 + lx, ey - r * .3 - lift - tilt]], {w: 3.2, wobble: .3});
  const mouth = pts => ink(ctx, pts.map(([x, y]) => [cx + lx + x * r, cy + y * r]), {w: 3.4, wobble: .3});
  if (mood === 'grin') { eye(cx - ex, .9); eye(cx + ex, .9); brow(cx - ex, -3, 4); brow(cx + ex, 3, 4);
    ctx.fillStyle = INK; ctx.beginPath(); ctx.moveTo(cx - r * .4 + lx, cy + r * .22); ctx.quadraticCurveTo(cx + lx, cy + r * .78, cx + r * .4 + lx, cy + r * .22); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#e8735f'; ctx.beginPath(); ctx.ellipse(cx + lx, cy + r * .44, r * .16, r * .07, 0, 0, Math.PI * 2); ctx.fill(); }
  if (mood === 'smile') { eye(cx - ex); eye(cx + ex); brow(cx - ex, -1, 2); brow(cx + ex, 1, 2); mouth([[-.32, .26], [0, .48], [.32, .26]]); }
  if (mood === 'focus') { eye(cx - ex, .7); eye(cx + ex, .7); brow(cx - ex, 4); brow(cx + ex, -4); mouth([[-.18, .36], [.05, .32], [.2, .38]]); }
  if (mood === 'smug') { eye(cx - ex, .55); eye(cx + ex, .55); brow(cx - ex, -5, 6); brow(cx + ex, 1, -1); mouth([[-.3, .32], [0, .4], [.34, .2]]); }
  if (mood === 'shrug') { eye(cx - ex); eye(cx + ex); brow(cx - ex, 6, 6); brow(cx + ex, -6, 6); mouth([[-.26, .34], [-.05, .3], [.1, .36], [.26, .3]]); }
  if (mood === 'shock') { eye(cx - ex, 1.45); eye(cx + ex, 1.45); brow(cx - ex, 7, 14); brow(cx + ex, -7, 14);
    ctx.fillStyle = INK; ctx.beginPath(); ctx.ellipse(cx + lx, cy + r * .45, r * .17, r * .25, 0, 0, Math.PI * 2); ctx.fill();
    ink(ctx, [[cx + r * 1.05, cy - r * .55], [cx + r * 1.12, cy - r * .3]], {w: 3, color: '#5b8fd6'}); blob(ctx, cx + r * 1.13, cy - r * .2, 5, 8, {fill: '#9cc3ef', stroke: '#5b8fd6', w: 2}); }
  if (mood === 'neutral') { eye(cx - ex); eye(cx + ex); brow(cx - ex, 0, 0); brow(cx + ex, 0, 0); mouth([[-.22, .36], [0, .37], [.22, .35]]); }
  if (mood === 'wonder') { eye(cx - ex, 1.2); eye(cx + ex, 1.2); brow(cx - ex, -4, 10); brow(cx + ex, 4, 10); blob(ctx, cx + lx, cy + r * .42, r * .13, r * .16, {fill: INK, stroke: null}); }
}
// ---------- personnage ----------
// joints: head [x,y], neck, hip, legs [[knee, foot],[knee, foot]], arms [[elbow, hand]...] (shoulder = point on torso)
function figure(ctx, f) {
  const r = f.r || 44, [hx, hy] = f.head;
  const neck = f.neck, hip = f.hip, sh = f.shoulder || [neck[0] + (hip[0] - neck[0]) * .18, neck[1] + (hip[1] - neck[1]) * .18];
  ink(ctx, [neck, [(neck[0] + hip[0]) / 2 + (f.bend || 0), (neck[1] + hip[1]) / 2], hip], {w: 4.6});
  for (const [knee, foot] of f.legs) { ink(ctx, [hip, knee, foot], {w: 4.4}); blob(ctx, foot[0] + (f.facing || 1) * 9, foot[1] + 2, 13, 6, {fill: INK, w: 2}); }
  for (const [elbow, hand] of f.arms || []) { ink(ctx, [sh, elbow, hand], {w: 4.2}); blob(ctx, hand[0], hand[1], 8, 9.5, {fill: PAPER, w: 3}); }
  if (f.scarf) { marker(ctx, [[neck[0] - 18, neck[1] + 4], [neck[0], neck[1] + 10], [neck[0] + 18, neck[1] + 4]], f.scarf, 12);
    ink(ctx, [[neck[0] + 4, neck[1] + 8], [neck[0] + 12, neck[1] + 40]], {w: 9, color: f.scarf, wobble: 1}); }
  if (f.tie) { ctx.fillStyle = f.tie; ctx.beginPath(); ctx.moveTo(neck[0] - 7, neck[1] + 6); ctx.lineTo(neck[0] + 7, neck[1] + 6); ctx.lineTo(neck[0] + 5, neck[1] + 58); ctx.lineTo(neck[0], neck[1] + 66); ctx.lineTo(neck[0] - 5, neck[1] + 58); ctx.closePath(); ctx.fill(); }
  if (f.ponytail) { ink(ctx, [[hx - r * .8 * (f.facing || 1), hy - r * .55], [hx - r * 1.35 * (f.facing || 1), hy - r * .2], [hx - r * 1.25 * (f.facing || 1), hy + r * .55]], {w: 9, color: INK}); }
  blob(ctx, hx, hy, r, r * 1.02, {fill: PAPER, w: 4.4});
  if (f.ponytail) { ctx.save(); ctx.beginPath(); ctx.arc(hx, hy, r - 1, Math.PI * 1.05, Math.PI * 1.95); ctx.fillStyle = INK; ctx.fill(); ctx.restore();
    blob(ctx, hx - r * .78 * (f.facing || 1), hy - r * .5, 9, 9, {fill: YELLOW, w: 2}); }
  if (f.hair === 'hugo') { ctx.fillStyle = '#8b8f94'; ctx.beginPath(); ctx.arc(hx, hy, r - 1, Math.PI * 1.08, Math.PI * 1.92); ctx.fill();
    ink(ctx, [[hx - r * .78, hy - r * .5], [hx - r * .3, hy - r * .78], [hx + r * .2, hy - r * .7], [hx + r * .78, hy - r * .5]], {w: 3}); }
  face(ctx, hx, hy + r * .08, r, f.mood, f.look || 0);
  if (f.glasses) { const ey = hy - r * .0, lx = (f.look || 0) * r * .18;
    for (const s of [-1, 1]) blob(ctx, hx + s * r * .36 + lx, ey, r * .25, r * .22, {w: 2.6, n: 18});
    ink(ctx, [[hx - r * .11 + lx, ey - 2], [hx + r * .11 + lx, ey - 2]], {w: 2.4}); }
  if (f.extra) f.extra(ctx);
}
// Bras séparé : épaule au coin haut-gauche (pivot de rotation du moteur), dirigé à 45° vers le bas-droite.
function armSprite(name, len, {hold, bend = .18} = {}) {
  const pad = 4, d = len / Math.SQRT2, size = d + 150;
  sprite(name, size, size, ctx => {
    const ex = pad + d * .5 + d * bend, ey = pad + d * .5 - d * bend * .4, hx = pad + d, hy = pad + d;
    ink(ctx, [[pad, pad], [ex, ey], [hx, hy]], {w: 4.2});
    if (hold) hold(ctx, hx, hy);
    blob(ctx, hx, hy, 8, 9.5, {fill: PAPER, w: 3});
  }, {pivot: [pad, pad], restDirection: '45deg down-right; angle 0'});
}

// ---------- accessoires ----------
function coin(ctx, cx, cy, rx = 46) { const ry = rx * .32;
  ctx.fillStyle = YELLOW; ctx.beginPath(); ctx.ellipse(cx, cy + 9, rx, ry, 0, 0, Math.PI * 2); ctx.fill(); ctx.fillRect(cx - rx, cy, rx * 2, 9);
  ink(ctx, [[cx - rx, cy], [cx - rx, cy + 9]], {w: 3, wobble: .2}); ink(ctx, [[cx + rx, cy], [cx + rx, cy + 9]], {w: 3, wobble: .2});
  ctx.save(); ctx.beginPath(); ctx.ellipse(cx, cy + 9, rx, ry, 0, 0, Math.PI); ctx.strokeStyle = INK; ctx.lineWidth = 3; ctx.stroke(); ctx.restore();
  ctx.fillStyle = '#f7d65e'; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); ctx.fill();
  blob(ctx, cx, cy, rx, ry, {w: 3, n: 30}); blob(ctx, cx, cy, rx * .6, ry * .55, {w: 1.8, stroke: '#b98f12', n: 22}); }
function stack(name, n) { const h = 40 + n * 17 + 40;
  sprite(name, 120, h, ctx => { for (let i = 0; i < n; i++) coin(ctx, 60 + j(3), h - 30 - i * 17); }, {coins: n}); }
function note(ctx, x, y, w = 92, rot = 0, label = '100') {
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); const h = w * .52;
  ctx.fillStyle = '#cfe7c4'; ctx.fillRect(-w / 2, -h / 2, w, h);
  ink(ctx, [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2], [-w / 2, -h / 2]], {w: 3, wobble: .5, straight: true});
  blob(ctx, 0, 0, h * .3, h * .3, {w: 2.2, stroke: GREEN, n: 18});
  ctx.fillStyle = '#2f6b3a'; ctx.font = `700 ${h * .32}px sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('€', 0, 1);
  ctx.font = `700 ${h * .24}px sans-serif`; ctx.fillText(label, -w * .3, -h * .26); ctx.restore(); }
function pot(ctx, cx, top, w = 150) { const h = w * .72;
  ctx.fillStyle = '#d9825b'; ctx.beginPath(); ctx.moveTo(cx - w / 2, top + 22); ctx.lineTo(cx + w / 2, top + 22); ctx.lineTo(cx + w * .36, top + h); ctx.lineTo(cx - w * .36, top + h); ctx.closePath(); ctx.fill();
  ink(ctx, [[cx - w / 2, top + 22], [cx - w * .36, top + h], [cx + w * .36, top + h], [cx + w / 2, top + 22]], {w: 3.6, straight: true});
  ctx.fillStyle = '#e39a73'; ctx.fillRect(cx - w / 2 - 10, top, w + 20, 24); ink(ctx, [[cx - w / 2 - 10, top], [cx + w / 2 + 10, top], [cx + w / 2 + 10, top + 24], [cx - w / 2 - 10, top + 24], [cx - w / 2 - 10, top]], {w: 3.6, straight: true});
  ctx.fillStyle = '#6b4b36'; ctx.beginPath(); ctx.ellipse(cx, top + 2, w / 2 + 4, 9, 0, Math.PI, 0); ctx.fill(); }
function leaf(ctx, x, y, s, a) { ctx.save(); ctx.translate(x, y); ctx.rotate(a); ctx.fillStyle = '#7cc47f'; ctx.beginPath(); ctx.moveTo(0, 0); ctx.quadraticCurveTo(s * .5, -s * .45, s, 0); ctx.quadraticCurveTo(s * .5, s * .45, 0, 0); ctx.fill();
  ink(ctx, [[0, 0], [s * .5, -s * .3], [s, 0], [s * .5, s * .3], [0, 0]], {w: 2.4, wobble: .3}); ink(ctx, [[0, 0], [s * .9, 0]], {w: 1.6, color: GREEN, wobble: .2}); ctx.restore(); }
function tree(name, height, coins, crown) {
  const W = crown * 2 + 80, H = height + crown + 170;
  sprite(name, W, H, ctx => { const cx = W / 2, base = H - 110;
    ink(ctx, [[cx - 6, base], [cx - 2, base - height * .5], [cx + 4, base - height + crown * .6]], {w: 10, color: '#6b4b36', wobble: 1.4});
    ink(ctx, [[cx, base - height * .45], [cx - crown * .45, base - height * .7]], {w: 6, color: '#6b4b36'});
    ink(ctx, [[cx + 2, base - height * .55], [cx + crown * .45, base - height * .78]], {w: 6, color: '#6b4b36'});
    const cy = base - height + crown * .35;
    for (let i = 0; i < 9; i++) { const a = i / 9 * Math.PI * 2; blob(ctx, cx + Math.cos(a) * crown * .55, cy + Math.sin(a) * crown * .38, crown * .42, crown * .34, {fill: i % 2 ? '#8fd08f' : '#a6dca0', stroke: null}); }
    blob(ctx, cx, cy, crown * .95, crown * .72, {stroke: GREEN, w: 3.4, n: 40});
    for (let i = 0; i < coins; i++) { const a = rand() * Math.PI * 2, rr = Math.sqrt(rand()) * .78; coin(ctx, cx + Math.cos(a) * crown * .75 * rr, cy + Math.sin(a) * crown * .52 * rr - 6, 15); }
    pot(ctx, cx, base, 150);
  }, {potTop: H - 110, trunkX: W / 2}); }

// ================= sprites =================
stack('stack-3', 3); stack('stack-9', 9); stack('stack-16', 16);
sprite('ground', 420, 400, ctx => { ctx.fillStyle = PAPER; ctx.fillRect(0, 10, 420, 390); ink(ctx, [[6, 12], [140, 9], [280, 13], [414, 10]], {w: 4, straight: true}); });
sprite('pot-empty', 220, 150, ctx => pot(ctx, 110, 20, 150));
sprite('pot-soil-note', 220, 180, ctx => { pot(ctx, 110, 55, 150); note(ctx, 110, 34, 70, -.25); });
sprite('pot-soil-3notes', 240, 200, ctx => { pot(ctx, 120, 75, 150); note(ctx, 88, 48, 70, -.35); note(ctx, 120, 34, 70, .1); note(ctx, 152, 50, 70, .4); });
sprite('sprout', 120, 120, ctx => { ink(ctx, [[60, 118], [58, 80], [62, 40]], {w: 4, color: GREEN}); leaf(ctx, 60, 70, 46, -0.6); leaf(ctx, 60, 52, 40, Math.PI + .5); });
sprite('note-1', 120, 80, ctx => note(ctx, 60, 40, 96, 0));
sprite('notes-3', 200, 140, ctx => { note(ctx, 80, 74, 92, -.25); note(ctx, 100, 64, 92, .05); note(ctx, 120, 70, 92, .3); });
sprite('tag-7', 240, 120, ctx => { ctx.fillStyle = '#fff3c4'; ctx.beginPath(); ctx.moveTo(30, 20); ctx.lineTo(210, 20); ctx.lineTo(210, 100); ctx.lineTo(30, 100); ctx.lineTo(8, 60); ctx.closePath(); ctx.fill();
  ink(ctx, [[30, 20], [210, 20], [210, 100], [30, 100], [8, 60], [30, 20]], {w: 3.4, straight: true}); blob(ctx, 34, 60, 7, 7, {w: 2.6});
  ctx.fillStyle = INK; ctx.font = '700 46px "Caveat", sans-serif'; ctx.textBaseline = 'middle'; ctx.fillText('7 % / an', 56, 62); });
sprite('clock-face', 220, 220, ctx => { blob(ctx, 110, 110, 96, 96, {fill: '#fffaf0', w: 4.4, n: 44});
  for (let i = 0; i < 12; i++) { const a = i / 12 * Math.PI * 2; ink(ctx, [[110 + Math.cos(a) * 80, 110 + Math.sin(a) * 80], [110 + Math.cos(a) * 90, 110 + Math.sin(a) * 90]], {w: 3}); }
  blob(ctx, 110, 110, 7, 7, {fill: INK, stroke: null}); });
sprite('clock-hand', 110, 110, ctx => { ink(ctx, [[4, 4], [70, 70]], {w: 6, color: RED, wobble: .3}); }, {pivot: [4, 4]});

// Léa (20 ans) : queue de cheval, écharpe verte. Hugo (40 ans) : cheveux gris, lunettes, cravate marine.
const LEA = {ponytail: true, scarf: GREEN, r: 44};
const HUGO = {hair: 'hugo', glasses: true, tie: NAVY, r: 46};
// Léa accroupie qui plante (bras droit séparé)
sprite('lea-plant', 300, 420, ctx => figure(ctx, {...LEA, facing: 1, mood: 'focus', look: .8, head: [120, 100], neck: [128, 150], hip: [120, 285], bend: 8,
  legs: [[[190, 300], [170, 400]], [[100, 340], [70, 400]]], arms: [[[110, 230], [150, 265]]]}), {shoulder: [130, 175]});
armSprite('lea-arm-note', 120, {hold: (ctx, x, y) => note(ctx, x + 20, y + 18, 72, .5)});
armSprite('lea-arm', 120);
sprite('lea-shrug', 300, 470, ctx => figure(ctx, {...LEA, facing: 1, mood: 'shrug', look: .2, head: [150, 80], neck: [150, 130], hip: [150, 300],
  legs: [[[170, 380], [180, 460]], [[130, 380], [118, 460]]], arms: [[[90, 200], [60, 150]], [[210, 200], [240, 150]]]}));
sprite('lea-joy', 320, 480, ctx => figure(ctx, {...LEA, facing: 1, mood: 'grin', look: .3, head: [160, 110], neck: [160, 160], hip: [160, 320],
  legs: [[[190, 400], [215, 470]], [[135, 395], [105, 470]]], arms: [[[100, 120], [70, 50]]]}), {shoulder: [160, 190]});
armSprite('lea-arm-up', 130, {bend: -.1});
// Hugo debout (bras droit séparé, tient 3 billets)
sprite('hugo-stand', 300, 480, ctx => figure(ctx, {...HUGO, facing: -1, mood: 'smile', look: -.6, head: [160, 90], neck: [158, 142], hip: [160, 312],
  legs: [[[175, 392], [185, 470]], [[145, 392], [130, 470]]], arms: [[[200, 230], [215, 300]]]}), {shoulder: [158, 172]});
armSprite('hugo-arm-notes', 125, {hold: (ctx, x, y) => { note(ctx, x - 10, y + 22, 66, -.4); note(ctx, x, y + 14, 66, -.1); note(ctx, x + 10, y + 22, 66, .25); }});
armSprite('hugo-arm', 125);
// Hugo sûr de lui : main sur la hanche, bras levé séparé (pouce)
sprite('hugo-smug', 340, 500, ctx => figure(ctx, {...HUGO, facing: 1, mood: 'smug', look: .2, head: [170, 100], neck: [170, 152], hip: [168, 322], bend: -6,
  legs: [[[205, 405], [235, 488]], [[140, 405], [110, 488]]], arms: [[[110, 250], [160, 300]]]}), {shoulder: [170, 182]});
armSprite('hugo-arm-thumb', 130, {bend: -.12, hold: (ctx, x, y) => ink(ctx, [[x, y - 6], [x + 2, y - 26]], {w: 5})});
// Hugo stupéfait : mains sur les joues
sprite('hugo-shock', 320, 500, ctx => figure(ctx, {...HUGO, facing: 1, mood: 'shock', look: .5, head: [160, 100], neck: [160, 152], hip: [160, 322],
  legs: [[[185, 405], [200, 488]], [[135, 405], [118, 488]]], arms: [[[95, 220], [118, 130]], [[225, 220], [202, 130]]]}));
// Arbres à 65 ans
tree('tree-hugo', 300, 6, 120);
tree('tree-lea', 520, 14, 190);

// Sol de Capital Simple : même trait que « ground », rempli au papier de la charte (#F7F3EA) pour ne pas
// faire de bande claire sous la ligne sur le fond de la chaîne.
sprite('ground-paper', 420, 400, ctx => { ctx.fillStyle = '#F7F3EA'; ctx.fillRect(0, 10, 420, 390); ink(ctx, [[6, 12], [140, 9], [280, 13], [414, 10]], {w: 4, straight: true}); });

// ----- poses ajoutées pour Capital Simple (même construction que les poses de la vidéo test) -----
// Debout, bras le long du corps, neutre ; surprise : bouche ronde, mains ouvertes ; montrer du doigt : bras
// tendu à l'horizontale vers la droite, index tendu (on retourne le sprite pour montrer à gauche).
const standLegs = cx => [[[cx + 18, 400], [cx + 25, 470]], [[cx - 22, 395], [cx - 35, 470]]];
const finger = (ctx, x, y) => ink(ctx, [[x + 6, y - 2], [x + 28, y - 4]], {w: 4.2});
sprite('lea-neutral', 300, 480, ctx => figure(ctx, {...LEA, facing: 1, mood: 'neutral', look: 0, head: [150, 110], neck: [150, 160],
  hip: [150, 320], legs: standLegs(150), arms: [[[120, 240], [112, 305]], [[180, 240], [188, 305]]]}));
sprite('lea-surprise', 320, 480, ctx => figure(ctx, {...LEA, facing: 1, mood: 'wonder', look: .2, head: [160, 110], neck: [160, 160],
  hip: [160, 320], legs: standLegs(160), arms: [[[105, 220], [85, 160]], [[215, 220], [235, 160]]]}));
sprite('lea-point', 380, 480, ctx => figure(ctx, {...LEA, facing: 1, mood: 'smile', look: .7, head: [150, 110], neck: [150, 160],
  hip: [150, 320], legs: standLegs(150), arms: [[[120, 240], [112, 305]], [[235, 195], [320, 190]]],
  extra: c => finger(c, 320, 190)}));
sprite('hugo-neutral', 300, 480, ctx => figure(ctx, {...HUGO, facing: -1, mood: 'neutral', look: 0, head: [150, 90], neck: [150, 142],
  hip: [150, 312], legs: [[[165, 392], [175, 470]], [[135, 392], [120, 470]]], arms: [[[120, 230], [112, 300]], [[180, 230], [188, 300]]]}));
sprite('hugo-point', 380, 480, ctx => figure(ctx, {...HUGO, facing: 1, mood: 'focus', look: .7, head: [150, 90], neck: [150, 142],
  hip: [150, 312], legs: [[[165, 392], [175, 470]], [[135, 392], [120, 470]]], arms: [[[120, 230], [112, 300]], [[235, 180], [320, 176]]],
  extra: c => finger(c, 320, 176)}));

for (const d of ['characters', 'props']) {
  const part = Object.fromEntries(Object.entries(manifest).filter(([name]) => dirOf(name).endsWith(d)));
  fs.writeFileSync(path.join(ROOT, d, 'sprites.json'), JSON.stringify(part, null, 2) + '\n');
}
console.log(Object.keys(manifest).length, 'sprites →', ROOT);
