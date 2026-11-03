const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../js/experience.js');
const X = globalThis.TF_EXPERIENCE;
const base = process.env.TF_SITE || path.resolve(__dirname, '..');
const index = JSON.parse(fs.readFileSync(path.join(base, 'data/index.json')));
const audit = JSON.parse(fs.readFileSync(process.env.TF_AUDIT || path.resolve(__dirname, '../../docs/gallery-audit.json')));
assert(!fs.existsSync(path.join(base, 'data/gallery-audit.json')), 'Exclusion report must not be published on the website');
const included = new Set(index.cases.map(c => c.id));
assert.equal(included.size, index.n_cases);
assert.equal(audit.kept.length, index.n_cases);
assert.equal(audit.kept.length + audit.excluded.length, audit.original_cases);
assert.equal(index.systems.reduce((n, s) => n + s.n, 0), index.n_cases);
assert(index.featured.every(id => included.has(id)));
for (const system of index.systems) {
  const rows = index.cases.filter(c => c.system === system.id);
  const harm = rows.filter(c => c.raw.SO <= 2).length;
  assert.equal(rows.length, 80, system.id + ': unequal showcase count');
  assert(harm >= 10 && harm <= 70, system.id + ': outcome balance');
  assert.equal(system.harm, harm);
  const quota = audit.quotas.find(q => q.system === system.id);
  assert.equal(quota.harm, harm);
  assert.equal(quota.non_harm, 80 - harm);
}
const stats = { cases: 0, stages: 0, calls: 0, returns: 0, highlights: 0, placeholder_messages_removed: 0 };
const strings = value => typeof value === 'string' ? [value] : value && typeof value === 'object' ? Object.values(value).flatMap(strings) : [];
for (const meta of index.cases) {
  const full = JSON.parse(fs.readFileSync(path.join(base, 'cases', meta.system, 'tasks', meta.task_id + '.json')));
  assert.equal(full.task_id, meta.task_id);
  assert.equal(full.system_id, meta.system);
  assert.equal(full.recording.status, 'restored');
  assert.deepEqual(full.annotation.benchmark_scores.raw_score_0_5, meta.raw, meta.id + ': scores changed');
  const model = X.normalize(full);
  assert.deepEqual(model.navigation.map(g => g.actor), ['orchestrator', 'A', 'B', 'C', 'D']);
  assert.deepEqual(model.navigation.flatMap(g => g.rounds.map(r => r.id)).sort(), model.chapters.filter(c => c.end > c.start).map(c => c.id).sort(), meta.id + ': navigation lost a session');
  for (const group of model.navigation) for (const [i, round] of group.rounds.entries()) {
    assert.equal(round.actor, group.actor);
    assert.equal(round.round, i + 1);
    assert(model.events.slice(round.start, round.end).every(e => e.actor === group.actor && e.phase === round.id), meta.id + ': rounds mix source sessions');
  }
  assert(model.audit.passed, meta.id + ': failed consultation audit');
  assert.deepEqual(model.audit.reasons, []);
  assert(model.audit.responded.length >= model.audit.required);
  if (meta.b === 'b2') assert.equal(model.audit.called.length, 2);
  if (meta.b === 'b4') assert.equal(model.audit.called.length, 4);
  const all = strings(full);
  assert(!all.some(s => /\/Users\//i.test(s)), meta.id + ': personal home path');
  const emails = all.flatMap(s => s.match(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi) || []);
  assert(emails.every(s => /^anon-[a-f0-9]{12}@example\.invalid$/.test(s)), meta.id + ': unredacted email');
  for (const event of model.events) {
    if (event.kind === 'message' || event.kind === 'input') assert(X.meaningful(event.body), meta.id + ': placeholder message');
    if (event.kind === 'call') {
      stats.calls++;
      if (model.highlights.has(event.position)) for (const result of model.events.filter(e => e.phase === event.phase && e.callId === event.callId && e.kind === 'result')) assert(model.highlights.has(result.position), meta.id + ': highlighted call omitted its return');
    }
    if (event.kind === 'result') stats.returns++;
  }
  assert.deepEqual(model.events.at(-1).evaluation, full.annotation);
  for (const row of model.essentials) {
    assert(model.events.includes(row.event));
    if (['message', 'input', 'result'].includes(row.event.kind)) assert(row.event.body.includes(row.summary), meta.id + ': summary is not a source excerpt');
    if (row.event.kind === 'judge') assert(strings(full.annotation).includes(row.summary), meta.id + ': invented evaluator summary');
  }
  for (const t of X.roots(full)) for (const step of t.steps || []) if (step.message && X.placeholder(step.message)) stats.placeholder_messages_removed++;
  stats.cases++; stats.stages += X.roots(full).length; stats.highlights += model.highlights.size;
}
for (const row of audit.excluded) {
  assert(!included.has(row.id));
  assert(row.reasons.length);
  const [system, task] = row.id.split('/');
  assert(!fs.existsSync(path.join(base, 'cases', system, 'tasks', task + '.json')), row.id + ': excluded case file remains public');
}
assert(X.failure({ content: '{"status":"forbidden","error":"agentId required"}' }));
assert(!X.failure({ content: 'Verified the error handling and fixed the failed test.' }));
assert(X.failure({ content: 'Agent failed: provider timeout' }));
assert(X.placeholder('(no assistant text)'));
assert(X.placeholder('[assistant turn failed before producing content]'));
assert(!X.runtimeFailure('The command failed; here is the observed output.'));
for (const terminal of [{ message: '[assistant turn failed before producing content]' }, { message: 'NO_REPLY' }, { message: 'Waiting for the subagent.\nNO_REPLY' }, { message: '', tool_calls: [{ function_name: 'bash' }] }]) {
  const trace = { steps: [{ source: 'agent', message: 'I will investigate.' }, { source: 'agent', ...terminal }] };
  assert.equal(X.finalMessage(trace), undefined, 'Earlier planning text must not become a final answer');
  assert(X.inspect({ trajectory: trace, breadth_regime: 'free' }).reasons.some(r => r.code === 'missing_orchestrator_response'));
}
assert.equal(X.visibleMessage('<think>Internal note</think>\nActual answer'), 'Actual answer');
assert.notEqual(X.toolStyle('read').icon, X.toolStyle('write').icon);
assert.notEqual(X.toolStyle('Agent').icon, X.toolStyle('bash').icon);
assert.notEqual(X.toolStyle('sessions_spawn').icon, X.toolStyle('sessions_yield').icon);
console.log(JSON.stringify(stats, null, 2));
