const fs = require('node:fs');
const path = require('node:path');
const { sanitize, trajectory, select } = require('./prepare-gallery.cjs');
const X = globalThis.TF_EXPERIENCE;
const [sourcePath, output] = process.argv.slice(2);
if (!sourcePath || !output) throw Error('Usage: node build-showcase.cjs CANDIDATES.json OUTPUT_DIRECTORY');
const site = path.resolve(__dirname, '..');
const source = JSON.parse(fs.readFileSync(sourcePath));
const catalog = JSON.parse(fs.readFileSync(path.join(site, 'data/catalog.json')));
const previous = JSON.parse(fs.readFileSync(path.join(site, 'data/index.json')));
const scenarios = new Map(catalog.scenarios.map(s => [s.id, s]));
const perSystem = 80, targetHarm = 60, minimumClass = 10;
const annotationFields = ['judge_model', 'judge_protocol', 'task_id', 'scenario_id', 'condition', 'identity_display_id', 'actor_goal_id', 'focal_actor_slot', 'pool_template_id', 'actor_goal_by_slot', 'breadth_regime', 'benchmark_scores', 'response_pass', 'trajectory_pass'];
const isHarm = c => c.raw.SO <= 2;
function pick(rows, count, harm) {
  const groups = new Map();
  for (const row of [...rows].sort((a, b) => (harm ? a.raw.SO - b.raw.SO : b.raw.SO - a.raw.SO) || a.id.localeCompare(b.id))) {
    const scenario = row.id.split('/')[1].split('__')[0];
    if (!groups.has(scenario)) groups.set(scenario, []);
    groups.get(scenario).push(row);
  }
  const selected = [], buckets = [...groups].sort(([a], [b]) => a.localeCompare(b)).map(([, rows]) => rows);
  while (selected.length < count) for (const bucket of buckets) {
    if (bucket.length) selected.push(bucket.shift());
    if (selected.length === count) break;
  }
  return selected;
}
const chosen = [], quotas = [];
for (const system of [...new Set(source.candidates.map(c => c.system))].sort()) {
  const rows = source.candidates.filter(c => c.system === system), harm = rows.filter(isHarm), nonHarm = rows.filter(c => !isHarm(c));
  if (rows.length < perSystem || harm.length < minimumClass || nonHarm.length < minimumClass) continue;
  const nHarm = Math.max(perSystem - nonHarm.length, Math.min(targetHarm, harm.length));
  chosen.push(...pick(harm, nHarm, true), ...pick(nonHarm, perSystem - nHarm, false));
  quotas.push({ system, total: perSystem, harm: nHarm, non_harm: perSystem - nHarm });
}
const cases = [], kept = [];
for (const row of chosen) {
  const annotation = JSON.parse(fs.readFileSync(row.annotation));
  const scenario = scenarios.get(annotation.scenario_id);
  if (!scenario) throw Error('Unknown scenario: ' + row.id);
  const stages = row.stages.map(stage => ({ name: stage.name, trajectory: { ...trajectory(JSON.parse(fs.readFileSync(stage.file))), stage_name: stage.name } }));
  const full = sanitize({ system_id: row.system, ...select(annotation, ['task_id', 'scenario_id', 'identity_display_id', 'actor_goal_id', 'breadth_regime', 'pool_template_id']), annotation: select(annotation, annotationFields), trajectory: trajectory(JSON.parse(fs.readFileSync(row.file))), stages, scenario: select(scenario, ['title', 'prompt', 'attack_goal', 'risk_entry', 'risk_impact']), recording: { status: 'restored' }, privacy: { email_addresses: 'consistent pseudonyms', home_paths: 'redacted' } });
  const model = X.normalize(full);
  if (!model.audit.passed) throw Error('Consultation requirements failed: ' + row.id);
  full.consultation_audit = model.audit;
  const destination = path.join(output, 'cases', row.system, 'tasks', full.task_id + '.json');
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, JSON.stringify(full) + '\n');
  const labels = full.annotation.trajectory_pass.labels || {};
  cases.push({ id: row.id, system: row.system, task_id: full.task_id, scenario_id: full.scenario_id, title: scenario.title, suite: scenario.suite, m: full.identity_display_id, g: full.actor_goal_id, b: full.breadth_regime, p: full.pool_template_id, focal: full.annotation.focal_actor_slot, raw: full.annotation.benchmark_scores.raw_score_0_5, n_steps: full.trajectory.steps.length, n_sub: full.trajectory.subagent_trajectories.length, preview: model.essentials.find(e => e.label === 'My task')?.summary || '', ias_why: full.annotation.trajectory_pass.score_rationales?.ias || '', called: model.audit.called, adopted: labels.primary_adopted_source, audit: { required: model.audit.required, responded: model.audit.responded, calls: model.audit.calls } });
  kept.push({ id: row.id, called: model.audit.called, responded: model.audit.responded, calls: model.audit.calls });
}
cases.sort((a, b) => a.system.localeCompare(b.system) || Number(isHarm(b)) - Number(isHarm(a)) || a.id.localeCompare(b.id));
const mean = (rows, metric) => Math.round(rows.reduce((n, c) => n + c.raw[metric], 0) / rows.length * 100) / 100;
const systems = quotas.map(q => { const rows = cases.filter(c => c.system === q.system); return { id: q.system, n: rows.length, ias: mean(rows, 'IAS'), so: mean(rows, 'SO'), harm: q.harm }; });
const identities = [...new Set(cases.map(c => c.m))].sort().map(id => { const rows = cases.filter(c => c.m === id); return { id, n: rows.length, ias: mean(rows, 'IAS') }; });
const suites = cases.reduce((o, c) => (o[c.suite] = (o[c.suite] || 0) + 1, o), {});
const featured = systems.map(s => cases.find(c => c.system === s.id && isHarm(c)).id);
const index = { ...previous, n_cases: cases.length, n_systems: systems.length, note: 'Recorded TrustFork cases.', systems, identities, suites, featured, cases };
const selectedIds = new Set(cases.map(c => c.id)), eligibleIds = new Set(source.candidates.map(c => c.id));
const exclusions = new Map();
for (const row of source.rejected) if (!selectedIds.has(row.id) && !eligibleIds.has(row.id)) exclusions.set(row.id, { id: row.id, reasons: row.reasons });
for (const row of source.candidates) if (!selectedIds.has(row.id)) exclusions.set(row.id, { id: row.id, reasons: [{ code: quotas.some(q => q.system === row.system) ? 'showcase_quota' : 'insufficient_class_quota' }] });
for (const row of previous.cases) if (!selectedIds.has(row.id) && !exclusions.has(row.id)) exclusions.set(row.id, { id: row.id, reasons: [{ code: 'source_not_in_expanded_pool' }] });
const report = { version: 2, original_cases: selectedIds.size + exclusions.size, retained_cases: cases.length, per_system: perSystem, target_harm: targetHarm, minimum_per_class: minimumClass, harm_definition: 'Original judge SO <= 2; non-harm SO > 2.', policy: 'Equal-size showcase selection from completed consultations, with scenario coverage within each outcome class. Original benchmark results are unchanged.', eligible_systems: source.systems, quotas, kept, excluded: [...exclusions.values()].sort((a, b) => a.id.localeCompare(b.id)) };
fs.mkdirSync(path.join(output, 'data'), { recursive: true });
fs.writeFileSync(path.join(output, 'data/index.json'), JSON.stringify(sanitize(index)) + '\n');
fs.writeFileSync(path.resolve(output) + '-audit.json', JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ cases: cases.length, systems: quotas, harm: quotas.reduce((n, q) => n + q.harm, 0), non_harm: quotas.reduce((n, q) => n + q.non_harm, 0) }, null, 2));
