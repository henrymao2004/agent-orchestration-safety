(function (root) {
  const text = value => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value, null, 2);
  const compact = value => text(value).replace(/\s+/g, ' ').trim();
  const parse = value => { try { return JSON.parse(text(value)); } catch { return null; } };
  const runtimeFailure = value => /^\[assistant turn (?:failed|aborted|cancelled|timed out)(?:\s[^\]]*)?\]$/i.test(compact(value));
  const placeholder = value => runtimeFailure(value) || /^(?:\(no assistant text\)|\(no output\)|NO_REPLY|HEARTBEAT_OK|\[?empty\]?|undefined|null|\.\.\.|\u2026)?$/i.test(compact(value));
  const visibleMessage = value => text(value).replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  const meaningful = value => !placeholder(visibleMessage(value));
  const slot = value => text(value).match(/(?:candidate_|subagent\s+)([a-d])\b/i)?.[1].toUpperCase() || (/^[A-D]$/.test(value) ? value : null);
  const argsOf = call => typeof call.arguments === 'string' ? parse(call.arguments) || call.arguments : call.arguments || {};
  const target = call => { const a = argsOf(call); return slot(a.agentId || a.subagent_type || a.agent || a.name); };
  const delegation = call => /^(task|delegate_task|subagent|agent|sessions_spawn|spawn_agent)$/i.test(call.function_name || '');
  const failedStatus = value => /^(error|failed|forbidden|denied|aborted|cancelled|canceled|timeout|timed_out)$/i.test(value || '');
  function failure(result, call = {}) {
    if (result?.is_error === true || result?.extra?.is_error === true || failedStatus(call.status || call.extra?.status)) return true;
    const body = text(result?.content), data = parse(body);
    if (data && !Array.isArray(data) && (failedStatus(data.status) || data.error)) return true;
    return /(?:^|\n)\[error\] tool reported failure\s*$/.test(body) || /^<task\b[^>]*\bstate="(?:error|failed|aborted|cancelled)"/i.test(body) || /^(?:Error:|Agent (?:failed|aborted)|Task (?:failed|aborted)|Subagent (?:failed|aborted))/i.test(body.trim());
  }
  function pairs(trajectory) {
    const calls = new Map();
    for (const step of trajectory.steps || []) for (const call of step.tool_calls || []) calls.set(call.tool_call_id, { call, step, results: [] });
    for (const step of trajectory.steps || []) for (const result of step.observation?.results || []) {
      const id = result.source_call_id || result.tool_call_id;
      const pair = calls.get(id);
      if (pair) pair.results.push(result);
    }
    return [...calls.values()];
  }
  function finalMessage(trajectory) {
    const last = [...(trajectory.steps || [])].reverse().find(s => s.source === 'agent');
    return last && !(last.tool_calls || []).length && meaningful(last.message) && !/\bNO_REPLY\s*$/.test(last.message) ? last : undefined;
  }
  const roots = full => full.stages?.length ? full.stages.map(s => s.trajectory) : [full.trajectory || {}];
  function bind(trajectory) {
    const calls = pairs(trajectory).filter(p => delegation(p.call));
    const subs = trajectory.subagent_trajectories || [];
    return calls.map(p => {
      const actor = target(p.call), result = p.results[0], a = argsOf(p.call);
      const body = text(result?.content), data = parse(body);
      const ref = result?.subagent_trajectory_ref;
      const ids = [typeof ref === 'string' ? ref : ref?.trajectory_id, ref?.session_id, data?.childSessionKey, data?.sessionId].filter(Boolean);
      if (p.results.some(r => failure(r, p.call))) return { ...p, actor, sub: null, method: 'failed-call' };
      let candidates = subs.filter(s => !actor || slot(s.agent?.name) === actor);
      let exact = candidates.filter(s => ids.some(id => [s.session_id, s.trajectory_id, s.agent?.native_session_key].includes(id)) || (s.session_id && body.includes(s.session_id)));
      let method = 'session-reference';
      if (!exact.length) {
        const prompt = compact(a.prompt || a.task);
        exact = candidates.filter(s => prompt && (s.steps || []).some(st => st.source === 'user' && compact(st.message).includes(prompt)));
        method = 'exact-delegated-prompt';
      }
      if (exact.length > 1) {
        const after = exact.filter(s => Date.parse(s.steps?.[0]?.timestamp) >= Date.parse(p.step.timestamp));
        if (after.length) exact = after.sort((a, b) => Date.parse(a.steps[0].timestamp) - Date.parse(b.steps[0].timestamp)).slice(0, 1);
        method = 'exact-prompt-and-time';
      }
      const sub = exact.length === 1 ? exact[0] : null;
      return { ...p, actor, sub, method: sub ? method : 'unresolved' };
    });
  }
  function inspect(full) {
    const traces = roots(full), children = new Map();
    for (const trace of traces) for (const sub of trace.subagent_trajectories || []) {
      if (!children.has(sub.session_id) || children.get(sub.session_id).steps.length < sub.steps.length) children.set(sub.session_id, sub);
    }
    const bindings = [...new Map(traces.flatMap(t => bind({ ...t, subagent_trajectories: [...children.values()] })).map(p => [p.call.tool_call_id, p])).values()], reasons = [];
    const add = (code, evidence) => reasons.push({ code, ...evidence });
    const required = { free: 1, b2: 2, b4: 4 }[full.breadth_regime];
    const called = [...new Set(bindings.map(p => p.actor).filter(Boolean))];
    const responded = new Set(), orchestratorFinal = finalMessage(traces.at(-1));
    if (!required) add('unknown_breadth_requirement', {});
    if (required && called.length < required) add('insufficient_distinct_subagents', { required, observed: called.length });
    if (full.breadth_regime === 'b2' && called.length > 2) add('excess_distinct_subagents', { required: 2, observed: called.length });
    for (const p of bindings) {
      const callId = p.call.tool_call_id;
      if (p.results.some(r => failure(r, p.call)) || failedStatus(p.call.status)) { add('subagent_call_failed', { callId, actor: p.actor }); continue; }
      if (!p.actor) add('unresolved_subagent_target', { callId });
      if (!p.results.length) add('missing_delegation_return', { callId, actor: p.actor });
      if (!p.sub) { add('missing_subagent_trace', { callId, actor: p.actor }); continue; }
      if ((p.sub.steps || []).some(s => s.source === 'agent' && runtimeFailure(s.message))) { add('subagent_run_failed', { callId, actor: p.actor, session: p.sub.session_id }); continue; }
      const final = finalMessage(p.sub);
      if (!final) add('missing_subagent_response', { callId, actor: p.actor, session: p.sub.session_id });
      else if (failure({ content: visibleMessage(final.message) })) add('subagent_run_failed', { callId, actor: p.actor, session: p.sub.session_id });
      else if (Date.parse(final.timestamp) > Date.parse(orchestratorFinal?.timestamp)) add('subagent_response_after_orchestrator_end', { callId, actor: p.actor, session: p.sub.session_id });
      else if (p.actor) responded.add(p.actor);
    }
    const nestedSeen = new Set(bindings.map(p => p.call.tool_call_id));
    function nested(trace) {
      for (const sub of trace.subagent_trajectories || []) {
        for (const p of pairs(sub).filter(p => delegation(p.call))) {
          if (!nestedSeen.has(p.call.tool_call_id) && p.results.some(r => failure(r, p.call))) add('subagent_call_failed', { callId: p.call.tool_call_id, actor: target(p.call), session: sub.session_id });
          nestedSeen.add(p.call.tool_call_id);
        }
        nested(sub);
      }
    }
    traces.forEach(nested);
    for (const t of traces) if ((t.steps || []).some(s => s.source === 'agent' && runtimeFailure(s.message))) add('orchestrator_run_failed', { session: t.session_id });
    if (required && responded.size < required) add('insufficient_completed_subagents', { required, observed: responded.size });
    if (!finalMessage(traces.at(-1))) add('missing_orchestrator_response', {});
    return { passed: !reasons.length, required, called, responded: [...responded], calls: bindings.length, reasons, bindings };
  }
  function toolStyle(name, args = {}) {
    const n = (name || '').toLowerCase(), command = text(args.command);
    if (delegation({ function_name: name })) return { icon: 'bot', tone: 'delegate' };
    if (/yield|wait|get_subagent_result/.test(n)) return { icon: 'hourglass', tone: 'tracking' };
    if (/sessions|subagents|session_status/.test(n)) return { icon: 'network', tone: 'tracking' };
    if (/edit|patch/.test(n)) return { icon: 'file-pen-line', tone: 'edit' };
    if (/write/.test(n)) return { icon: 'file-plus-2', tone: 'edit' };
    if (/read/.test(n)) return { icon: 'file-text', tone: 'read' };
    if (/webfetch|web_fetch/.test(n)) return { icon: 'globe', tone: 'web' };
    if (/websearch|web_search/.test(n)) return { icon: 'radar', tone: 'web' };
    if (/glob|find|list/.test(n)) return { icon: 'folder-search', tone: 'search' };
    if (/grep|search/.test(n)) return { icon: 'search', tone: 'search' };
    if (/skill/.test(n)) return { icon: 'puzzle', tone: 'edit' };
    if (/todo/.test(n)) return { icon: 'list-checks', tone: 'tracking' };
    if (/bash|exec|shell|process/.test(n)) {
      if (/^\s*(cat|head|tail|sed|less)\b/.test(command)) return { icon: 'file-text', tone: 'read' };
      if (/^\s*(rg|grep|find|ls)\b/.test(command)) return { icon: 'folder-search', tone: 'search' };
      return { icon: 'terminal', tone: 'terminal' };
    }
    return { icon: 'wrench', tone: 'tool' };
  }
  function excerpt(event, focus = '') {
    let body = visibleMessage(event.body);
    if (event.kind === 'call') {
      const a = event.args || {};
      if (event.delegate) body = text(a.prompt || a.task || a.description);
      else if (a.command) return text(a.command);
      else if ('old_string' in a || 'new_string' in a || 'oldText' in a || 'newText' in a) return `${a.file_path || a.filePath || a.path || ''}\n${text(a.old_string ?? a.oldText)} -> ${text(a.new_string ?? a.newText)}`;
      else return [a.file_path || a.filePath || a.path || a.url || a.pattern || a.query, a.content].filter(Boolean).map(text).join('\n') || body;
    }
    const taskResult = body.match(/<task_result>([\s\S]*?)<\/task_result>/);
    if (taskResult) body = taskResult[1];
    body = body.replace(/^Agent completed[^\n]*\n\s*/, '').trim();
    const terms = [...new Set((focus.toLowerCase().match(/[a-z][a-z0-9_.\/-]{3,}/g) || []).filter(t => !/^(?:with|from|that|this|agent|subagent|task|the|and|which|should|would|could|into|have|were|their|will|file|content)$/.test(t)))];
    const paragraphs = body.split(/\n\s*\n/).map(s => s.trim()).filter(s => meaningful(s) && !/^\s*(?:#|\[Subagent Context\]|You are running as a subagent|Auto-announce|The following is the conversation history)/.test(s));
    if (!paragraphs.length) return body;
    const score = s => terms.reduce((sum, term) => sum + (s.toLowerCase().includes(term) ? (/\.|\//.test(term) ? 4 : 1) : 0), 0) + (/\b(?:wrote|written|changed|deleted|removed|executed|verified|reverted|refus|unsafe|injection|overwrit|exfil|curl|chmod|rm -)/i.test(s) ? 3 : 0);
    const best = paragraphs.map((body, index) => ({ body, index, score: score(body) })).sort((a, b) => b.score - a.score || a.index - b.index)[0].body;
    if (best.length <= 650) return best;
    const lines = best.split('\n'), windows = lines.map((line, i) => ({ body: lines.slice(i, i + 3).join('\n'), score: score(line), i }));
    return windows.sort((a, b) => b.score - a.score || a.i - b.i)[0].body;
  }
  function normalize(full) {
    const events = [], chapters = [], audit = inspect(full), traces = roots(full);
    const bindings = audit.bindings, byCall = new Map(bindings.map(p => [p.call.tool_call_id, p]));
    const emitted = new Set(), seenSteps = new Set();
    const add = e => { e.position = events.length; events.push(e); return e; };
    function visit(t, actor = 'orchestrator', parent = null) {
      const phase = t.stage_name ? `${t.stage_name}:${t.session_id}` : t.session_id || actor;
      if (emitted.has(phase)) return;
      emitted.add(phase);
      const chapter = { id: phase, actor, title: actor === 'orchestrator' ? (t.stage_name && t.stage_name !== 'single' ? t.stage_name.replaceAll('_', ' ') : 'Orchestrator') : `Subagent ${actor}`, start: events.length, model: t.agent?.model_name || '', parentCall: parent?.call.tool_call_id };
      chapters.push(chapter);
      for (const step of t.steps || []) {
        const identity = `${t.session_id}:${JSON.stringify(step)}`;
        if (seenSteps.has(identity)) continue;
        seenSteps.add(identity);
        const common = { phase, actor, step: step.step_id, timestamp: step.timestamp, source: `${phase}/step/${step.step_id}` };
        const message = visibleMessage(step.message);
        if (meaningful(message)) add({ ...common, kind: step.source === 'agent' ? 'message' : 'input', icon: step.source === 'agent' ? 'message-square' : 'inbox', title: actor === 'orchestrator' ? (step.source === 'agent' ? 'My response' : 'What I see') : `Subagent ${actor} ${step.source === 'agent' ? 'response' : 'input'}`, body: message, raw: text(step.message) });
        if (step.reasoning_content && meaningful(step.reasoning_content)) add({ ...common, kind: 'reasoning', icon: 'brain', title: 'Recorded reasoning', body: text(step.reasoning_content) });
        const calls = step.tool_calls || [];
        for (const call of calls) {
          const binding = actor === 'orchestrator' ? byCall.get(call.tool_call_id) : null;
          add({ ...common, kind: 'call', title: call.function_name, ...toolStyle(call.function_name, argsOf(call)), body: text(call.arguments), args: argsOf(call), callId: call.tool_call_id, delegate: delegation(call), target: target(call), child: binding?.sub?.session_id });
        }
        for (const result of step.observation?.results || []) {
          const callId = result.source_call_id || result.tool_call_id;
          const call = (t.steps || []).flatMap(s => s.tool_calls || []).find(c => c.tool_call_id === callId);
          const binding = actor === 'orchestrator' ? byCall.get(callId) : null;
          // Keep session-local order; a resumed child can span multiple parent calls.
          add({ ...common, kind: 'result', title: call?.function_name || 'Tool return', ...toolStyle(call?.function_name, argsOf(call || {})), body: text(result.content), callId, delegate: delegation(call || {}), target: target(call || {}), error: failure(result, call), truncated: result.truncated === true, hasStatus: typeof result.is_error === 'boolean', child: binding?.sub?.session_id });
        }
      }
      chapter.end = events.length;
    }
    traces.forEach(t => visit(t));
    for (const p of bindings) if (p.sub) visit(p.sub, p.actor, p);
    for (const trace of traces) for (const sub of trace.subagent_trajectories || []) visit(sub, slot(sub.agent?.name) || 'unresolved');
    add({ kind: 'judge', actor: 'evaluator', phase: 'evaluation', icon: 'scale', title: 'Final evaluation', evaluation: full.annotation, body: '' });
    const focus = [full.scenario?.attack_goal, full.scenario?.risk_impact, full.annotation?.trajectory_pass?.labels?.risk_path].filter(Boolean).join(' ');
    const highlights = new Map(), mark = (event, reason) => { if (event) highlights.set(event.position, reason); };
    for (const chapter of chapters) {
      const rows = events.filter(e => e.phase === chapter.id);
      mark(rows.find(e => e.kind === 'input'), chapter.actor === 'orchestrator' ? 'Original task' : 'Exact delegated input');
      mark(rows.filter(e => e.kind === 'message').at(-1), chapter.actor === 'orchestrator' ? 'Final orchestrator response' : 'Actual subagent response');
      for (const e of rows.filter(e => e.kind === 'call' && e.delegate)) mark(e, 'Recorded delegation');
      const candidates = rows.filter(e => e.kind === 'call' && e.tone !== 'tracking' && !e.delegate);
      const relevance = e => {
        const terms = (focus.toLowerCase().match(/[a-z][a-z0-9_.\/-]{3,}/g) || []).filter(t => /[._/]/.test(t));
        return terms.reduce((n, t) => n + (e.body.toLowerCase().includes(t) ? 4 : 0), 0) + (e.tone === 'edit' ? 5 : 0) + (/\b(curl|rm|chmod|python|bash|node|verify|diff|sha256)\b/.test(e.body) ? 2 : 0);
      };
      for (const e of candidates.sort((a, b) => relevance(b) - relevance(a) || a.position - b.position).slice(0, 3)) mark(e, 'Task-relevant tool evidence');
    }
    const evidenceIds = new Set(Object.values(full.annotation?.response_pass?.scores || {}).flatMap(s => s.evidence || []));
    for (const e of events) {
      if (e.callId && evidenceIds.has(e.callId)) mark(e, 'Call cited by the evaluator');
      if (e.error) mark(e, 'Reported tool error');
      if (e.kind === 'judge') mark(e, 'Recorded evaluation');
    }
    for (const e of events.filter(e => e.callId && highlights.has(e.position))) {
      for (const pair of events.filter(p => p.phase === e.phase && p.callId === e.callId)) mark(pair, highlights.get(pair.position) || 'Paired call and return');
    }
    const essentials = [];
    const input = events.find(e => e.actor === 'orchestrator' && e.kind === 'input');
    if (input) essentials.push({ label: 'My task', event: input, summary: excerpt(input) });
    const anchors = full.scenario?.attack_goal?.match(/[\w.-]+\.(?:md|py|txt|json|sh)|\b\d{6,}\b/g) || [];
    const evidence = events.filter(e => e.kind === 'result' && anchors.some(a => e.body.includes(a))).map(e => ({ e, score: anchors.reduce((n, a) => n + (e.body.includes(a) ? 5 : 0), 0) + (['web', 'read'].includes(e.tone) ? 3 : 0) - (e.delegate ? 3 : 0) })).sort((a, b) => b.score - a.score || a.e.position - b.e.position)[0]?.e;
    if (evidence) essentials.push({ label: 'Key source evidence', event: evidence, summary: excerpt(evidence, focus) });
    const operations = events.filter(e => e.kind === 'call' && !e.delegate && e.tone !== 'tracking');
    const ranked = operations.map(e => ({ e, value: (e.tone === 'edit' ? 4 : 0) + (text(full.scenario?.attack_goal).match(/[\w.-]+\.(?:md|py|txt|json|sh)/g) || []).reduce((n, p) => n + (e.body.includes(p) ? 10 : 0), 0) })).sort((a, b) => b.value - a.value || a.e.position - b.e.position);
    if (ranked[0]) essentials.push({ label: 'Recorded operation', event: ranked[0].e, summary: excerpt(ranked[0].e, focus) });
    const response = events.filter(e => e.actor === 'orchestrator' && e.kind === 'message').at(-1);
    if (response) essentials.push({ label: 'My final response', event: response, summary: excerpt(response, focus) });
    const judge = events.at(-1), rationale = full.annotation?.trajectory_pass?.labels?.final_state || full.annotation?.trajectory_pass?.score_rationales?.so;
    if (rationale) essentials.push({ label: 'Evaluator: final state', event: judge, summary: rationale });
    for (const row of essentials) mark(row.event, 'Case summary source');
    for (const e of events.filter(e => e.callId && highlights.has(e.position))) {
      for (const pair of events.filter(p => p.phase === e.phase && p.callId === e.callId)) mark(pair, highlights.get(pair.position) || 'Paired call and return');
    }
    const navigation = ['orchestrator', 'A', 'B', 'C', 'D'].map(actor => ({
      actor, title: actor === 'orchestrator' ? 'Orchestrator' : `Subagent ${actor}`,
      rounds: chapters.filter(c => c.actor === actor && c.end > c.start).map((c, i) => ({ ...c, round: i + 1, label: actor === 'orchestrator' ? c.title : `Round ${i + 1}` }))
    }));
    return { events, chapters, navigation, highlights, essentials, audit: { ...audit, bindings: undefined }, focus };
  }
  root.TF_EXPERIENCE = { text, compact, parse, placeholder, runtimeFailure, visibleMessage, meaningful, slot, target, delegation, failure, pairs, finalMessage, roots, bind, inspect, toolStyle, excerpt, normalize };
})(typeof window === 'undefined' ? globalThis : window);
