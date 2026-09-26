const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const lucide = require('../js/lucide.min.js');
require('../js/experience.js');
const X = globalThis.TF_EXPERIENCE;
const site = path.resolve(__dirname, '..');
const index = JSON.parse(fs.readFileSync(path.join(site, 'data/index.json')));
const context = { window: { TF_EXPERIENCE: X } };
vm.createContext(context);
for (const name of ['design', 'core', 'flow']) vm.runInContext(fs.readFileSync(path.join(site, 'js', name + '.js'), 'utf8'), context);
const TF = context.window.TF, flow = context.window.TF_FLOW, design = context.window.TF_DESIGN;
const esc = value => TF.esc(value).replace(/\r/g, '&#13;').replace(/\n/g, '&#10;');
const short = (value, size = 240) => { const s = X.compact(value); return s.length > size ? s.slice(0, size) + '...' : s; };
const element = ([tag, attrs, children = []]) => `<${tag}${Object.entries(attrs || {}).map(([k, v]) => ` ${k}="${esc(v)}"`).join('')}>${children.map(element).join('')}</${tag}>`;
const icon = name => element(lucide[name.split('-').map(s => s[0].toUpperCase() + s.slice(1)).join('')] || lucide.Wrench);
const header = `<header class="static-header"><a href="index.html">TrustFork</a><nav aria-label="Main navigation"><a href="index.html">Home</a><a href="gallery.html">Showcase</a><a href="findings.html">Findings</a><a href="run.html">Run</a></nav></header>`;
const caseUrl = c => `showcase/${c.system}/${c.task_id}.html`;
const systemAnchor = s => 'system-' + s;
const directory = `<div class="static-showcase">${header}<main class="static-wrap"><div class="static-title"><div><h1>Showcase</h1><p>${index.n_systems} systems · ${index.n_cases} cases</p></div></div><nav class="static-systems" aria-label="Systems">${index.systems.map(s => `<a href="#${systemAnchor(s.id)}">${esc(TF.fmtSys(s.id))}</a>`).join('')}</nav>${index.systems.map(s => `<section class="static-system" id="${systemAnchor(s.id)}"><h2>${flow.pairLogos(s.id)}${esc(TF.fmtSys(s.id))}<small>${s.n} cases</small></h2><ul class="static-directory">${index.cases.filter(c => c.system === s.id).map(c => `<li><a href="${caseUrl(c)}"><span class="outcome-mark ${c.raw.SO <= 2 ? 'harm' : ''}"></span><span><strong>${esc(c.title)}</strong><small>Task ${esc(c.task_id.replace('trustfork_', ''))}</small></span></a></li>`).join('')}</ul></section>`).join('')}</main></div>`;
const galleryPath = path.join(site, 'gallery.html');
const gallery = fs.readFileSync(galleryPath, 'utf8');
fs.writeFileSync(galleryPath, gallery.replace(/<!-- STATIC_SHOWCASE_START -->[\s\S]*?<!-- STATIC_SHOWCASE_END -->/, `<!-- STATIC_SHOWCASE_START -->\n${directory}\n  <!-- STATIC_SHOWCASE_END -->`));

function wires(called, mobile) {
  const positions = mobile ? [[25, 86], [75, 86], [25, 268], [75, 268]] : [[12.5, 86], [37.5, 86], [62.5, 86], [87.5, 86]];
  return `<svg class="scene-svg static-wire-${mobile ? 'mobile' : 'desktop'}" viewBox="0 0 100 ${mobile ? 270 : 88}" preserveAspectRatio="none" aria-hidden="true">${positions.map(([x, y], i) => `<path class="wire-path ${called.includes('ABCD'[i]) ? 'hot' : ''}" d="M50 0 C50 ${y * .45} ${x} ${y * .45} ${x} ${y}" fill="none" vector-effect="non-scaling-stroke"/>`).join('')}</svg>`;
}
function body(e) {
  const a = e.args || {}, old = a.old_string ?? a.oldText, next = a.new_string ?? a.newText;
  if (e.kind === 'call' && (old !== undefined || next !== undefined)) return `<p>${esc(a.file_path || a.filePath || a.path || '')}</p><h3>Before</h3><pre>${esc(X.text(old))}</pre><h3>Proposed replacement</h3><pre>${esc(X.text(next))}</pre><details><summary>All arguments</summary><pre>${esc(e.body)}</pre></details>`;
  return `<pre>${esc(e.body)}</pre>`;
}
function event(e, model, prefix = 'event-') {
  const kind = { input: 'Input', message: 'Response', reasoning: 'Recorded reasoning', call: 'Tool call', result: e.error ? 'Reported error' : 'Tool return' }[e.kind];
  return `<details class="static-event ${e.kind} ${e.tone || ''} ${e.error ? 'error' : ''}" id="${prefix}${e.position}"><summary>${icon(e.icon)}<span><strong>${esc(kind)}${['call', 'result'].includes(e.kind) ? ' · ' + esc(e.title) : ''} · Step ${e.step}</strong><small>${esc(short(X.excerpt(e, model.focus)))}</small></span></summary><div class="event-body">${body(e)}</div></details>`;
}
function evaluation(annotation) {
  const raw = annotation.benchmark_scores.raw_score_0_5, rationales = annotation.trajectory_pass.score_rationales || {};
  return `<section class="static-judge" id="evaluation"><h2>Final evaluation</h2><div class="static-metrics">${design.metrics.map(m => {
    const key = m.raw || m.id, value = raw[key], score = 20 * (m.invert ? 5 - value : value);
    const rationale = rationales[key.toLowerCase()];
    const response = Object.values(annotation.response_pass.scores || {}).filter(r => r[m.id.toLowerCase()] !== undefined);
    return `<section class="static-metric"><header><strong>${esc(m.id)} · ${esc(m.name)}</strong><strong>${score.toFixed(0)} / 100</strong></header><meter min="0" max="100" value="${score}" aria-label="${esc(m.name)}"></meter>${rationale ? `<p>${esc(rationale)}</p>` : response.map(r => `<p><strong>${esc(r.actor)} · ${r[m.id.toLowerCase()]} / 5</strong><br>${esc(r.rationale || '')}</p>`).join('')}</section>`;
  }).join('')}</div></section>`;
}
for (const c of index.cases) {
  const full = JSON.parse(fs.readFileSync(path.join(site, 'cases', c.system, 'tasks', c.task_id + '.json'))), model = X.normalize(full);
  const anchor = id => `${caseUrl(c)}#${id}`;
  const graph = flow.markup(c, full, model).replace('<svg class="scene-svg" aria-hidden="true"></svg>', wires(model.audit.called, false) + wires(model.audit.called, true)).replace(/ role="button" tabindex="0"/g, '');
  const essentials = model.essentials.map(row => `<a class="static-essential ${row.event.kind}" href="${anchor(row.event.kind === 'judge' ? 'evaluation' : 'event-' + row.event.position)}"><strong>${icon(row.event.icon)}${esc(row.label)}</strong><p>${esc(short(row.summary, 440))}</p></a>`).join('');
  const actors = model.navigation.filter(g => g.rounds.length);
  const content = actors.map(g => `<section class="static-actor" id="actor-${g.actor}"><h2>${esc(g.title)}</h2>${g.rounds.map(round => {
    const events = model.events.slice(round.start, round.end);
    const highlighted = events.filter(e => model.highlights.has(e.position));
    return `<details class="static-round" open><summary>${esc(round.label)}</summary><details open class="static-highlights"><summary>Highlights</summary>${highlighted.map(e => event(e, model)).join('')}</details><details class="static-full"><summary>Full trajectory (${events.length} events)</summary>${events.map(e => event(e, model, 'full-event-')).join('')}</details></details>`;
  }).join('')}</section>`).join('');
  const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><base href="../../"><title>${esc(c.title)} | TrustFork</title><link rel="icon" href="assets/favicon.svg"><link rel="stylesheet" href="css/site.css"><link rel="stylesheet" href="css/flow.css?v=tf-evidence-1"><link rel="stylesheet" href="css/showcase-static.css?v=tf-balanced-80"></head><body class="static-case ${c.raw.SO <= 2 ? 'harm' : ''}">${header}<main class="static-wrap"><div class="static-title">${flow.pairLogos(c.system)}<div><h1>${esc(c.title)}</h1><p>${esc(TF.fmtSys(c.system))} · Task ${esc(c.task_id.replace('trustfork_', ''))}</p></div></div>${graph}<nav class="static-agent-nav" aria-label="Agents">${actors.map(g => `<a href="${anchor('actor-' + g.actor)}">${esc(g.title)}</a>`).join('')}<a href="${anchor('evaluation')}">Evaluation</a></nav><section class="static-essentials">${essentials}</section><a class="static-download" href="cases/${c.system}/tasks/${c.task_id}.json" download>${icon('download')}Recorded case</a>${content}${evaluation(full.annotation)}</main></body></html>`;
  const dest = path.join(site, caseUrl(c));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, html);
}
console.log(JSON.stringify({ staticCases: index.n_cases, systems: index.n_systems }));
