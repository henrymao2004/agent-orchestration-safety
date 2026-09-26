const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
require('../js/experience.js');
const X = globalThis.TF_EXPERIENCE;
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
const select = (value, fields) => Object.fromEntries(fields.filter(k => value?.[k] !== undefined).map(k => [k, value[k]]));
function sanitize(value) {
  if (typeof value === 'string') return value
    .replace(/\/Users\/[^\s/"'\\]+/gi, '/redacted-home')
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, address => /^anon-[a-f0-9]{12}@example\.invalid$/.test(address) ? address : `anon-${digest(address.toLowerCase()).slice(0, 12)}@example.invalid`)
    .replace(/\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b/g, '[redacted-credential]')
    .replace(/(\bAuthorization\s*[:=]\s*["']?Bearer\s+)[A-Za-z0-9_.-]+/gi, '$1[redacted-credential]');
  if (Array.isArray(value)) return value.map(sanitize);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, sanitize(v)]));
  return value;
}
function trajectory(raw) {
  const out = select(raw, ['schema_version', 'session_id', 'trajectory_id']);
  out.agent = select(raw.agent, ['name', 'model_name', 'version']);
  const native = raw.agent?.extra?.native_bundle?.match(/agent-(candidate_[a-d])-subagent-([^/]+)$/);
  if (native) out.agent.native_session_key = `agent:${native[1]}:subagent:${native[2]}`;
  out.steps = (raw.steps || []).map(step => {
    const result = select(step, ['step_id', 'source', 'timestamp', 'message', 'reasoning_content']);
    if (step.tool_calls?.length) result.tool_calls = step.tool_calls.map(call => ({ ...select(call, ['tool_call_id', 'function_name', 'arguments']), ...(call.extra?.status ? { status: call.extra.status } : {}) }));
    if (step.observation?.results) result.observation = { results: step.observation.results.map(r => {
      const row = select(r, ['source_call_id', 'tool_call_id', 'content', 'is_error', 'subagent_trajectory_ref']);
      if (typeof r.extra?.is_error === 'boolean') row.is_error = r.extra.is_error;
      if (r.extra?.opencode_metadata?.truncated === true) row.truncated = true;
      return row;
    }) };
    return result;
  });
  out.subagent_trajectories = (raw.subagent_trajectories || []).map(trajectory);
  return out;
}
function prepare(mapPath, output, site) {
  const index = JSON.parse(fs.readFileSync(path.join(site, 'data/index.json')));
  const catalog = JSON.parse(fs.readFileSync(path.join(site, 'data/catalog.json')));
  const sources = new Map(JSON.parse(fs.readFileSync(mapPath)).map(row => [row.id, row]));
  const report = { version: 1, original_cases: index.cases.length, policy: 'Gallery-only curation. Exclude failed delegations, unmet distinct-actor breadth, and unrecoverable consultation evidence. Original benchmark scores and source archives are unchanged.', kept: [], excluded: [] };
  const outputCases = [];
  fs.mkdirSync(output, { recursive: true });
  for (const meta of index.cases) {
    const source = sources.get(meta.id);
    if (!source) { report.excluded.push({ id: meta.id, reasons: [{ code: 'original_evidence_unavailable' }] }); continue; }
    const original = JSON.parse(fs.readFileSync(path.join(site, 'cases', meta.system, 'tasks', meta.task_id + '.json')));
    const bytes = fs.readFileSync(source.file), raw = JSON.parse(bytes);
    if (raw.session_id !== original.trajectory.session_id || raw.steps.length !== original.trajectory.steps.length || !raw.steps.every((s, i) => s.step_id === original.trajectory.steps[i].step_id && s.source === original.trajectory.steps[i].source && s.timestamp === original.trajectory.steps[i].timestamp)) throw Error('Source identity mismatch: ' + meta.id);
    const stages = (source.stages || [{ name: 'single', file: source.file }]).map(stage => {
      const bytes = fs.readFileSync(stage.file), raw = JSON.parse(bytes);
      return { name: stage.name, source_sha256: digest(bytes), trajectory: { ...trajectory(raw), stage_name: stage.name } };
    }).sort((a, b) => Date.parse(a.trajectory.steps.at(-1)?.timestamp) - Date.parse(b.trajectory.steps.at(-1)?.timestamp));
    const full = sanitize({ ...original, trajectory: trajectory(raw), stages, scenario: select(catalog.scenarios.find(s => s.id === meta.scenario_id), ['title', 'prompt', 'attack_goal', 'risk_entry', 'risk_impact']), recording: { status: 'restored', source_sha256: digest(bytes) }, privacy: { email_addresses: 'consistent pseudonyms', home_paths: 'redacted' } });
    const audit = X.inspect(full);
    if (!audit.passed) { report.excluded.push({ id: meta.id, reasons: audit.reasons }); continue; }
    full.consultation_audit = { ...audit, bindings: undefined };
    const dest = path.join(output, 'cases', meta.system, 'tasks', meta.task_id + '.json');
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, JSON.stringify(full) + '\n');
    const model = X.normalize(full);
    outputCases.push(sanitize({ ...meta, called: audit.called, n_steps: full.trajectory.steps.length, n_sub: full.trajectory.subagent_trajectories.length, preview: model.essentials.find(e => e.label === 'My task')?.summary || meta.preview, audit: { required: audit.required, responded: audit.responded, calls: audit.calls } }));
    report.kept.push({ id: meta.id, called: audit.called, responded: audit.responded, calls: audit.calls });
  }
  const mean = (rows, key) => Math.round(rows.reduce((n, r) => n + Number(r.raw[key]), 0) / rows.length * 100) / 100;
  const systems = index.systems.map(s => { const rows = outputCases.filter(c => c.system === s.id); return { ...s, n: rows.length, ias: rows.length ? mean(rows, 'IAS') : null, so: rows.length ? mean(rows, 'SO') : null, harm: rows.filter(c => Number(c.raw.SO) <= 2).length }; }).filter(s => s.n);
  const included = new Set(outputCases.map(c => c.id));
  const featured = index.featured.filter(id => included.has(id));
  const next = { ...index, n_cases: outputCases.length, n_systems: systems.length, systems, featured: featured.length ? featured : outputCases.slice(0, 3).map(c => c.id), cases: outputCases, note: 'Recorded TrustFork cases.' };
  fs.mkdirSync(path.join(output, 'data'), { recursive: true });
  fs.writeFileSync(path.join(output, 'data/index.json'), JSON.stringify(next) + '\n');
  report.retained_cases = outputCases.length;
  report.reason_counts = report.excluded.flatMap(c => [...new Set(c.reasons.map(r => r.code))]).reduce((counts, code) => (counts[code] = (counts[code] || 0) + 1, counts), {});
  fs.writeFileSync(path.resolve(output) + '-audit.json', JSON.stringify(report, null, 2) + '\n');
  console.log(JSON.stringify({ original: index.cases.length, kept: outputCases.length, excluded: report.excluded.length, systems: systems.map(s => ({ id: s.id, n: s.n })), reasons: report.reason_counts }, null, 2));
}
module.exports = { sanitize, trajectory, select };
if (require.main === module) {
  const [mapPath, output, input] = process.argv.slice(2);
  if (!mapPath || !output) throw Error('Usage: node prepare-gallery.cjs SOURCE_MAP.json OUTPUT_DIRECTORY [UNFILTERED_SITE_DIRECTORY]');
  prepare(mapPath, output, input ? path.resolve(input) : path.resolve(__dirname, '..'));
}
