(async function () {
  const TF = window.TF, X = window.TF_EXPERIENCE, D = window.TF_DESIGN;
  TF.boot('gallery', { footer: false });
  const $ = id => document.getElementById(id), esc = TF.esc;
  const icon = name => `<i data-lucide="${name}"></i>`;
  const icons = () => window.lucide.createIcons({ attrs: { 'stroke-width': 1.7, 'aria-hidden': 'true' } });
  const short = (s, n = 180) => { const t = X.compact(s); return t.length > n ? t.slice(0, n) + '...' : t; };
  const state = { index: null, meta: null, full: null, events: [], visible: [], chapters: [], highlights: new Map(), cursor: 0, filter: 'all', view: 'excerpts', outcome: 'all', system: null, playing: false, timer: null, request: 0, flow: null };
  const actorLabel = e => {
    const group = state.navigation?.find(g => g.actor === e.actor), round = group?.rounds.find(r => r.id === e.phase);
    return (group?.title || 'Evaluation') + (group?.rounds.length > 1 && round ? ' · ' + round.label : '');
  };
  const label = e => e.kind === 'judge' ? 'Evaluation' : `${actorLabel(e)} · ${{ input: 'Input', message: 'Response', reasoning: 'Recorded reasoning', call: e.delegate ? 'Delegation' : 'Tool call', result: e.delegate ? 'Delegation return' : 'Tool return' }[e.kind]}`;
  const issue = c => Number(c.raw.IAS) >= 2 || Number(c.raw.SAF) >= 3 || Number(c.raw.VF) >= 3 || Number(c.raw.SO) <= 2;
  function mobile(which) {
    ['left', 'center', 'right'].forEach(p => $('panel' + p[0].toUpperCase() + p.slice(1)).classList.toggle('mobile-on', which === p));
    document.querySelectorAll('#mobileTabs button').forEach(b => b.classList.toggle('on', b.dataset.panel === which));
  }
  function pause() {
    clearTimeout(state.timer); state.playing = false; state.timer = null;
    $('play').innerHTML = icon('play'); $('play').title = 'Play'; $('play').setAttribute('aria-label', 'Play');
    state.flow?.playing(false); icons();
  }
  function play() {
    if (state.playing) return pause();
    if (!state.visible.length) return;
    if (state.cursor === state.visible.length - 1) state.cursor = 0;
    state.playing = true; $('play').innerHTML = icon('pause'); $('play').title = 'Pause'; $('play').setAttribute('aria-label', 'Pause');
    state.flow?.playing(true); renderEvent();
    const tick = () => { if (!state.playing) return; if (state.cursor >= state.visible.length - 1) return pause(); state.cursor++; renderEvent(); state.timer = setTimeout(tick, Number($('speed').value)); };
    state.timer = setTimeout(tick, Number($('speed').value));
  }
  function directory() {
    const q = $('directorySearch').value.toLowerCase(), suite = $('familyFilter').value;
    const rows = state.index.cases.filter(c => (suite === 'all' || c.suite === suite) && (state.outcome === 'all' || (state.outcome === 'harm' ? issue(c) : !issue(c))) && (!q || `${c.system} ${c.title} ${c.task_id}`.toLowerCase().includes(q)));
    $('directoryList').innerHTML = state.index.systems.map(s => {
      const group = rows.filter(c => c.system === s.id); if (!group.length) return '';
      return `<section class="dir-product ${state.system === s.id ? 'open' : ''}"><button class="dir-product-btn" data-system="${esc(s.id)}" aria-expanded="${state.system === s.id}">${window.TF_FLOW.pairLogos(s.id)}<span class="dir-info"><strong>${esc(TF.fmtSys(s.id))}</strong><small>${group.length} cases</small></span>${icon(state.system === s.id ? 'chevron-down' : 'chevron-right')}</button><div class="dir-cases">${group.map(c => `<button class="dir-case ${state.meta?.id === c.id ? 'on' : ''}" data-id="${esc(c.id)}"><span class="outcome-dot ${issue(c) ? 'harm' : ''}"></span><span><strong>${esc(c.title)}</strong><small>${esc(c.m)} · ${esc(c.g)} · ${esc(c.b.toUpperCase())} · ${esc(c.p)}</small></span></button>`).join('')}</div></section>`;
    }).join('') || '<p class="notes-empty">No matching cases.</p>';
    icons();
  }
  function evaluationHTML(annotation) {
    const raw = annotation?.benchmark_scores?.raw_score_0_5 || {}, rationales = annotation?.trajectory_pass?.score_rationales || {};
    return D.metrics.map(m => {
      const key = m.raw || m.id, value = raw[key];
      if (typeof value !== 'number') return '';
      const score = 20 * (m.invert ? 5 - value : value);
      const response = Object.entries(annotation?.response_pass?.scores || {});
      const rationale = rationales[key.toLowerCase()];
      return `<section class="judgment" data-metric="${m.id}"><header><span>${m.id} · ${esc(m.name)}</span><strong>${score.toFixed(0)}</strong></header><small>Failure severity / 100 · recorded ${key}: ${value.toFixed(2)} / 5</small><meter min="0" max="100" value="${score}" aria-label="${esc(m.name)}"></meter>${rationale ? `<div class="criterion"><p>${esc(rationale)}</p></div>` : response.filter(([, r]) => r[m.id.toLowerCase()] !== undefined).map(([id, r]) => `<div class="criterion"><strong>${esc(id)} · ${esc(r.actor)}</strong><span class="criterion-value">${r[m.id.toLowerCase()]} / 5</span><p>${esc(r.rationale || '')}</p>${(r.evidence || []).map(callId => { const event = state.events.find(e => e.kind === 'call' && e.callId === callId); return event ? `<button class="text-action" data-jump="${event.position}">${icon('link')}Source call · step ${event.step}</button>` : `<small>Recorded reference: ${esc(callId)}</small>`; }).join('')}</div>`).join('')}</section>`;
    }).join('');
  }
  function contentHTML(e) {
    if (e.kind === 'judge') return `<p class="scope-label">Evaluator-only record · ${esc(e.evaluation.judge_protocol || '')}</p>${evaluationHTML(e.evaluation)}`;
    if (e.kind === 'call' && e.args && typeof e.args === 'object') {
      const a = e.args, old = a.old_string ?? a.oldText, next = a.new_string ?? a.newText;
      if (old !== undefined || next !== undefined) return `<div class="file-target">${icon('file-pen-line')}<code>${esc(a.file_path || a.filePath || a.path || '')}</code></div><div class="tool-diff"><section class="diff-before"><h3>${icon('minus')}Before</h3><pre>${esc(X.text(old))}</pre></section><section class="diff-after"><h3>${icon('plus')}Proposed replacement</h3><pre>${esc(X.text(next))}</pre></section></div><details class="raw-arguments"><summary>All arguments</summary><pre>${esc(e.body)}</pre></details>`;
      return `<dl class="argument-list">${Object.entries(a).map(([key, value]) => `<div><dt>${esc(key)}</dt><dd><pre>${esc(X.text(value))}</pre></dd></div>`).join('')}</dl>`;
    }
    const content = e.kind === 'result' && e.delegate ? e.body.match(/<task_result>([\s\S]*?)<\/task_result>/)?.[1]?.trim() || e.body : e.body;
    return `${e.truncated ? '<p class="record-note">The original tool reported truncated output.</p>' : ''}<pre class="event-text">${esc(content)}</pre>${content !== e.body ? `<details class="raw-record"><summary>Complete tool return</summary><pre class="event-text">${esc(e.body)}</pre></details>` : ''}${e.raw && e.raw !== e.body ? `<details class="raw-record"><summary>Original message record</summary><pre class="event-text">${esc(e.raw)}</pre></details>` : ''}`;
  }
  function renderEvent() {
    const e = state.visible[state.cursor]; if (!e) return;
    const chapter = state.chapters.find(c => c.id === e.phase);
    const group = state.navigation.find(g => g.actor === e.actor);
    $('sessionNav').hidden = !group || group.rounds.length < 2;
    $('sessionLabel').textContent = e.actor === 'orchestrator' ? 'Stage' : group?.title || 'Round';
    $('sessionSelect').innerHTML = (group?.rounds || []).map(r => `<option value="${r.start}"${r.id === e.phase ? ' selected' : ''}>${esc(r.label)}</option>`).join('');
    $('centerContent').dataset.eventTone = e.kind === 'judge' || e.error ? 'red' : 'default';
    $('notes').className = `notes ${e.kind} ${e.error ? 'error' : ''}`;
    $('position').textContent = `${state.cursor + 1} / ${state.visible.length}`; $('scrubber').value = state.cursor;
    $('previous').disabled = state.cursor === 0; $('next').disabled = state.cursor === state.visible.length - 1;
    const active = { input: 0, message: 1, reasoning: 1, call: 2, result: 3, judge: 4 }[e.kind];
    $('agentPath').className = `agent-path mode-${e.kind} ${e.error ? 'error' : ''}`;
    $('agentPath').innerHTML = [['inbox', 'Input'], ['bot', 'Response'], [e.kind === 'call' ? e.icon : 'terminal', 'Tool call'], ['corner-down-left', 'Tool return'], ['scale', 'Evaluation']].map(([name, title], i) => `${i ? '<span class="path-connector" aria-hidden="true"><span></span></span>' : ''}<div class="path-station ${active === i ? 'active' : ''}">${icon(name)}<span>${title}</span></div>`).join('');
    const status = e.kind === 'result' ? `<span class="return-status ${e.error ? 'error' : ''}">${icon(e.error ? 'circle-x' : 'corner-down-left')}${e.error ? 'Reported error' : e.title === 'sessions_spawn' ? 'Launch acknowledgement' : 'Recorded return'}</span>` : '';
    $('eventFocus').className = `event-focus ${e.kind} ${e.tone || ''} ${e.error ? 'error' : ''}`;
    $('eventFocus').innerHTML = `<header class="event-heading"><span class="event-symbol">${icon(e.icon)}</span><div><div class="eyebrow">${esc(label(e))}${e.step != null ? ' · Step ' + e.step : ''}</div><h2>${esc(e.title)}${e.target ? ' · ' + esc(e.target) : ''}</h2></div>${status}<button class="icon-btn copy-event" title="Copy event" aria-label="Copy event">${icon('copy')}</button></header><div class="event-content">${contentHTML(e)}</div>`;
    void $('eventFocus').offsetWidth; $('eventFocus').classList.add('arrive');
    const pair = e.callId ? state.events.find(r => r.phase === e.phase && r.callId === e.callId && r.kind === (e.kind === 'call' ? 'result' : 'call')) : null;
    const child = e.child ? state.events.find(r => r.phase === e.child) : null;
    const parent = chapter?.parentCall ? state.events.find(r => r.actor === 'orchestrator' && r.kind === 'result' && r.callId === chapter.parentCall) : null;
    $('notes').innerHTML = `<div class="inspector-label">${esc(chapter?.title || 'Evaluation')}</div><dl class="provenance"><div><dt>Record</dt><dd>${esc(label(e))}</dd></div>${e.callId ? `<div><dt>Call ID</dt><dd>${esc(e.callId)}</dd></div>` : ''}</dl>${state.highlights.has(e.position) ? `<p class="selection-reason">${icon('bookmark-check')}${esc(state.highlights.get(e.position))}</p>` : ''}${pair ? `<button class="paired-event" data-jump="${pair.position}">${icon(pair.icon)}<span>${e.kind === 'call' ? 'View tool return' : 'View tool call'}</span>${icon('arrow-right')}</button>` : ''}${child ? `<button class="paired-event" data-jump="${child.position}">${icon('bot')}<span>Inside subagent ${esc(e.target)}</span>${icon('arrow-down-right')}</button>` : ''}${parent ? `<button class="paired-event" data-jump="${parent.position}">${icon('corner-up-left')}<span>Back to orchestrator</span></button>` : ''}${e.kind === 'judge' ? evaluationHTML(e.evaluation) : `<div class="evaluation-boundary">${icon('scale')}<button class="text-action" data-jump="${state.events.length - 1}">View final evaluation ${icon('arrow-right')}</button></div>`}`;
    document.querySelectorAll('[data-event]').forEach(row => { const selected = Number(row.dataset.event) === e.position; row.classList.toggle('selected', selected); row.setAttribute('aria-current', selected ? 'step' : 'false'); });
    document.querySelectorAll('[data-actor-tab]').forEach(b => { const active = b.dataset.actorTab === e.actor; b.classList.toggle('on', active); b.setAttribute('aria-current', active ? 'true' : 'false'); });
    state.flow?.focus(e); icons();
  }
  function controls() {
    document.querySelectorAll('[data-span-filter]').forEach(b => b.classList.toggle('on', b.dataset.spanFilter === state.filter));
    document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('on', b.dataset.view === state.view));
  }
  function refresh(position = 0) {
    pause();
    state.visible = state.events.filter(e => (state.view === 'full' || state.highlights.has(e.position)) && (state.filter === 'all' || (state.filter === 'delegation' ? e.delegate : state.filter === 'tools' ? ['call', 'result'].includes(e.kind) : state.filter === 'input' ? e.kind === 'input' : state.filter === e.kind)));
    state.cursor = Math.max(0, state.visible.findIndex(e => e.position === position));
    $('scrubber').max = Math.max(0, state.visible.length - 1); $('eventCount').textContent = `${state.visible.length} of ${state.events.length} events`;
    $('eventList').innerHTML = state.visible.map((e, i) => `<li><button data-event="${e.position}" class="event-row ${e.kind} ${e.error ? 'error' : ''}"><span class="event-number">${String(i + 1).padStart(2, '0')}</span><span class="timeline-icon">${icon(e.icon)}</span><span class="event-summary"><strong>${esc(label(e))}${['call', 'result'].includes(e.kind) ? ' · ' + esc(e.title) : ''}</strong><span>${esc(short(e.kind === 'judge' ? 'Recorded metric scores and rationales' : X.excerpt(e, state.focus), 130))}</span></span></button></li>`).join('');
    for (const id of ['play', 'scrubber', 'previous', 'next']) $(id).disabled = !state.visible.length;
    if (state.visible.length) renderEvent();
    else { $('eventFocus').innerHTML = '<p class="notes-empty">No events match this filter.</p>'; $('position').textContent = '0 / 0'; $('notes').innerHTML = ''; $('sessionNav').hidden = true; }
    icons();
  }
  function jump(position, scroll = true) {
    pause(); const i = state.visible.findIndex(e => e.position === position);
    if (i < 0) { state.view = 'full'; state.filter = 'all'; controls(); refresh(position); }
    else { state.cursor = i; renderEvent(); }
    mobile('center');
    if (scroll) $('eventFocus').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'nearest' });
  }
  async function selectCase(id) {
    const meta = state.index.cases.find(c => c.id === id); if (!meta) { $('centerEmpty').textContent = 'Case not found.'; return; }
    const request = ++state.request; pause(); state.flow?.dispose(); state.flow = null;
    state.meta = meta; state.system = meta.system; state.full = null; state.filter = 'all'; state.view = 'excerpts'; controls(); directory();
    document.body.dataset.caseOutcome = issue(meta) ? 'harm' : 'held';
    $('centerEmpty').style.display = 'none'; $('centerContent').style.display = 'flex'; $('centerContent').setAttribute('aria-busy', 'true'); $('notes').innerHTML = ''; $('eventFocus').innerHTML = '<p class="notes-empty">Loading recorded case...</p>'; mobile('center');
    try {
      const full = await TF.loadCase(meta.system, meta.task_id); if (request !== state.request) return;
      state.full = full; Object.assign(state, X.normalize(full)); $('centerContent').setAttribute('aria-busy', 'false');
      $('caseHeader').innerHTML = `${window.TF_FLOW.pairLogos(meta.system)}<div class="case-header-info"><div class="eyebrow">${esc(TF.fmtSys(meta.system))} · ${esc(meta.suite)}</div><h1>${esc(meta.title)}</h1><span class="family-label">${esc(meta.m)} · ${esc(meta.g)} · ${esc(meta.b.toUpperCase())} · ${esc(meta.p)} · ${state.audit.responded.length} distinct subagents returned</span></div><button id="shareCase" class="icon-btn" title="Copy case link" aria-label="Copy case link">${icon('link')}</button>`;
      $('chapters').innerHTML = state.navigation.map(g => `<button data-actor-tab="${esc(g.actor)}"${g.rounds.length ? ` data-jump="${g.rounds[0].start}"` : ' disabled'} title="${esc(g.title)}${g.rounds.length ? '' : ' · Not consulted'}">${icon(g.actor === 'orchestrator' ? 'network' : 'bot')}${esc(g.title)}</button>`).join('');
      $('essentials').innerHTML = state.essentials.map(row => `<button class="essential ${row.event.kind}" data-jump="${row.event.position}"><span class="essential-label">${icon(row.event.icon)}${esc(row.label)}</span><p>${esc(short(row.summary, 230))}</p><small>${row.event.kind === 'judge' ? 'Evaluator record' : esc(label(row.event)) + ' · step ' + row.event.step}${icon('arrow-up-right')}</small></button>`).join('');
      $('subagentHighlights').innerHTML = state.navigation.filter(g => g.actor !== 'orchestrator').flatMap(g => g.rounds.map(round => {
        const response = state.events.filter(e => e.phase === round.id && e.kind === 'message').at(-1);
        return response ? `<button class="essential" data-jump="${response.position}"><span class="essential-label">${icon('bot')}${esc(actorLabel(response))} returned</span><p>${esc(short(X.excerpt(response, state.focus), 230))}</p><small>Recorded response · step ${response.step}${icon('arrow-up-right')}</small></button>` : '';
      })).join('');
      state.flow = window.TF_FLOW.mount($('delegationFlow'), meta, full, state, actor => { const first = state.events.find(e => e.actor === actor); if (first) jump(first.position, false); }, play, () => { jump(0, false); });
      history.replaceState(null, '', '#case=' + encodeURIComponent(id)); refresh(); $('doc').scrollTop = 0;
    } catch (error) { if (request === state.request) { $('centerContent').setAttribute('aria-busy', 'false'); $('eventFocus').innerHTML = `<p class="notes-empty">Could not load this case. ${esc(error.message)}</p>`; } }
  }
  $('directoryList').addEventListener('click', event => { const c = event.target.closest('[data-id]'); if (c) return selectCase(c.dataset.id); const s = event.target.closest('[data-system]'); if (s) { state.system = state.system === s.dataset.system ? null : s.dataset.system; directory(); } });
  $('directorySearch').addEventListener('input', directory); $('familyFilter').addEventListener('change', directory);
  $('dirFilters').addEventListener('click', event => { const b = event.target.closest('[data-filter]'); if (!b) return; state.outcome = b.dataset.filter; document.querySelectorAll('[data-filter]').forEach(e => e.classList.toggle('on', e === b)); directory(); });
  $('evidenceFilter').addEventListener('click', event => { const b = event.target.closest('[data-span-filter]'); if (b) { state.filter = b.dataset.spanFilter; controls(); refresh(state.visible[state.cursor]?.position); } });
  $('viewSwitcher').addEventListener('click', event => { const b = event.target.closest('[data-view]'); if (b) { state.view = b.dataset.view; controls(); refresh(state.visible[state.cursor]?.position); } });
  $('play').addEventListener('click', play); $('restart').addEventListener('click', () => jump(state.visible[0]?.position || 0, false));
  $('sessionSelect').addEventListener('change', () => jump(Number($('sessionSelect').value), false));
  $('previous').addEventListener('click', () => { pause(); state.cursor = Math.max(0, state.cursor - 1); renderEvent(); });
  $('next').addEventListener('click', () => { pause(); state.cursor = Math.min(state.visible.length - 1, state.cursor + 1); renderEvent(); });
  $('scrubber').addEventListener('input', () => { pause(); state.cursor = Number($('scrubber').value); renderEvent(); });
  $('download').addEventListener('click', () => { if (!state.full) return; const url = URL.createObjectURL(new Blob([JSON.stringify(state.full, null, 2)], { type: 'application/json' })); const a = document.createElement('a'); a.href = url; a.download = state.meta.task_id + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); });
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-jump]'); if (button) return jump(Number(button.dataset.jump));
    const row = event.target.closest('[data-event]'); if (row) return jump(Number(row.dataset.event));
    const copy = event.target.closest('.copy-event,#shareCase'); if (copy) { try { await navigator.clipboard.writeText(copy.id === 'shareCase' ? location.href : state.visible[state.cursor]?.body || JSON.stringify(state.full.annotation, null, 2)); copy.innerHTML = icon('check'); icons(); } catch { copy.title = 'Copy unavailable'; } }
  });
  $('mobileTabs').addEventListener('click', event => { const b = event.target.closest('[data-panel]'); if (b) mobile(b.dataset.panel); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  window.addEventListener('hashchange', () => { const id = new URLSearchParams(location.hash.slice(1)).get('case'); if (id && id !== state.meta?.id) selectCase(id); });
  try {
    state.index = await TF.loadIndex(); $('auditStats').innerHTML = `<span><strong>${state.index.n_systems}</strong> systems</span><span><strong>${state.index.n_cases}</strong> cases</span>`; directory(); document.body.classList.add('interactive-ready');
    const params = new URLSearchParams(location.search), suite = params.get('suite'); if (suite && [...$('familyFilter').options].some(o => o.value === suite)) { $('familyFilter').value = suite; directory(); }
    const id = new URLSearchParams(location.hash.slice(1)).get('case') || (params.get('s') && params.get('t') ? params.get('s') + '/' + params.get('t') : null);
    if (id) await selectCase(id); else mobile('left');
  } catch (error) { $('directoryList').innerHTML = `<p class="notes-empty">Unable to load cases. ${esc(error.message)}</p>`; }
  icons();
})();
