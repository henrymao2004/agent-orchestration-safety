(function () {
  const TF=window.TF;
  let current;
  const SYS_COLOR = {
    glm: "#11443e", gpt: "#10a37f", kimi: "#1c1917", minimax: "#e11d48",
    opencode: "#111111", pi: "#4f46e5", openclaw: "#ea580c",
  };
  const LOGO_KEYS = new Set(["glm", "gpt", "kimi", "minimax", "opencode", "pi", "openclaw"]);

  function parseSystem(id) {
    const [model, harness] = String(id || "").split("__");
    let family = "glm";
    if (/gpt/i.test(model)) family = "gpt";
    else if (/kimi/i.test(model)) family = "kimi";
    else if (/minimax/i.test(model)) family = "minimax";
    return { model: model || "", harness: harness || "", family };
  }
  function logoImg(key, alt) {
    const k = LOGO_KEYS.has(key) ? key : "glm";
    return `<img src="assets/logos/${k}.svg" alt="${TF.esc(alt || k)}" width="28" height="28">`;
  }
  function pairLogos(sysId, cls) {
    const p = parseSystem(sysId);
    const a = logoImg(p.family, p.family);
    const b = logoImg(p.harness, p.harness);
    return `<span class="logo-pair ${cls || ""}" title="${TF.esc(p.family)} + ${TF.esc(p.harness)}">${a}${b}</span>`;
  }

  const ATTACK_MARK = {
    M2: { emoji: "🎭", hint: "swapped nametag" },
    M4: { emoji: "🔄", hint: "tier label flipped" },
    M6: { emoji: "🪞", hint: "family relation flipped" },
  };

  function identFamily(s) {
    const t = String(s || "").toLowerCase();
    if (/\bgpt\b|openai/.test(t)) return "gpt";
    if (/\bglm\b|zhipu|chatglm/.test(t)) return "glm";
    if (/\bkimi\b|moonshot/.test(t)) return "kimi";
    if (/minimax/.test(t)) return "minimax";
    return "";
  }
  function familyKey(s) {
    const t = String(s || "").toLowerCase();
    if (t === "gpt" || t === "glm" || t === "kimi" || t === "minimax") return t;
    return identFamily(s);
  }
  function prettyModel(id) {
    let s = String(id || "").split("/").pop().replace(/_/g, "-").replace(/-/g, " ");
    s = s.replace(/\bminimax\b/ig, "MiniMax")
      .replace(/\bgpt\b/ig, "GPT")
      .replace(/\bglm\b/ig, "GLM")
      .replace(/\bkimi\b/ig, "Kimi");
    return s.replace(/\b([a-z])/g, (ch) => ch.toUpperCase());
  }
  function identMap() {
    if (!current) return {};
    const labels = ((((current.full || {}).annotation || {}).trajectory_pass || {}).labels) || {};
    return labels.displayed_identity_by_actor || {};
  }
  function attackFor(slot, mId) {
    if (mId === "M2") return (slot === "A" || slot === "B") ? ATTACK_MARK.M2 : null;
    if (mId === "M4") return ATTACK_MARK.M4;
    if (mId === "M6") return ATTACK_MARK.M6;
    return null;
  }
  function actorFace(slot) {
    const empty = { slot: slot || "", raw: "", name: "Unlabeled", sub: "", emoji: "", hint: "", family: "", tagged: "Unlabeled" };
    if (!slot || slot === "none") return empty;
    const mId = (current && current.meta && current.meta.m) || "";
    const raw = String(identMap()[slot] || "").trim();
    const mark = attackFor(slot, mId);
    const relM = raw.match(/\(([^)]+)\)/);
    const rel = relM ? relM[1] : "";
    const stripped = raw.replace(/^Subagent\s+[A-D]\b/i, "").trim();
    const core = stripped.replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
    let name = "";
    let sub = "";
    if (core) {
      name = core;
      if (/frontier/i.test(rel)) sub = "claims frontier";
      else if (/efficient/i.test(rel)) sub = "claims efficient";
    } else if (/same-family/i.test(rel)) {
      name = "Same family";
    } else if (/cross-family/i.test(rel)) {
      name = "Cross family";
    } else {
      name = "No nametag";
    }
    if (mark && mId === "M4" && sub) sub = sub.replace("claims ", "flipped to ");
    if (mark && mId === "M6") sub = "relation flipped";
    if (mark && mId === "M2") sub = sub ? `${sub} · swapped` : "swapped nametag";
    const family = identFamily(raw) || identFamily(core);
    const emoji = mark ? mark.emoji : "";
    const tagged = emoji ? `${emoji} ${name}` : name;
    return { slot, raw, name, sub, emoji, hint: mark ? mark.hint : "", family, tagged };
  }
  function trueFace(slot) {
    const empty = { family: "", name: "", model: "", tier: "" };
    if (!current || !current.meta || !slot || slot === "none") return empty;
    const sys = parseSystem(current.meta.system);
    const roster = TF.resolvePool(sys.model, current.meta.p) || [];
    const hit = roster.find((a) => a.slot === slot);
    const roots = window.TF_EXPERIENCE.roots(current.full);
    const launched = roots.flatMap(t => window.TF_EXPERIENCE.pairs(t)).filter(p => window.TF_EXPERIENCE.target(p.call) === slot).flatMap(p => p.results.map(r => window.TF_EXPERIENCE.parse(r.content)?.resolvedModel)).filter(Boolean);
    const traces = roots.flatMap(t => t.subagent_trajectories || []);
    const recorded = [...new Set(launched.length ? launched : traces.filter(t => window.TF_EXPERIENCE.slot(t.agent?.name) === slot).map(t => t.agent?.model_name).filter(Boolean))];
    if (recorded.length) return { family: identFamily(recorded[0]), name: recorded.map(prettyModel).join(' / '), model: recorded.join(' / '), tier: hit?.tier || '', source: 'Recorded backbone' };
    if (!hit) {
      return { ...empty, name: 'Not recorded', source: 'No backbone record' };
    }
    return {
      family: familyKey(hit.family),
      name: prettyModel(hit.model),
      model: hit.model,
      tier: hit.tier || "",
      source: 'Configured pool backbone',
    };
  }
  function logoInner(key, alt, fallback) {
    if (LOGO_KEYS.has(key)) {
      return `<img src="assets/logos/${key}.svg" alt="${TF.esc(alt || key)}" width="28" height="28">`;
    }
    return `<span class="orb-fallback">${fallback || "🫥"}</span>`;
  }
  function actorOrb(face, truth, delay) {
    let glyph = "🫥";
    if (face.name === "Same family") glyph = "🏠";
    else if (face.name === "Cross family") glyph = "🌍";
    const front = logoInner(face.family, face.name, glyph);
    const back = logoInner(truth.family, truth.name, "•");
    const fake = !!face.emoji;
    const mark = fake
      ? `<i class="orb-mark" title="${TF.esc(face.hint)}">${face.emoji}</i><i class="fake-stamp">fake</i>`
      : "";
    const same = !!(face.family && truth.family && face.family === truth.family && !fake);
    return `<span class="orb-stage${same ? "" : " mismatch"}${fake ? " fake" : ""}" style="--flip-delay:${Number(delay) || 0}s">
      <span class="orb-true" title="true backbone">${back}</span>
      <span class="orb-mask" title="${fake ? "attack nametag" : "shown to the orchestrator"}">${front}${mark}</span>
    </span>`;
  }
  function trueLine(truth) {
    if (!truth || !truth.name) return "";
    const img = LOGO_KEYS.has(truth.family)
      ? `<img src="assets/logos/${truth.family}.svg" alt="">`
      : "";
    return `<span class="true-line" title="${TF.esc(truth.source || 'Recorded backbone')}">${img}<span class="true-tag">${truth.source === 'Configured pool backbone' ? 'pool' : 'true'}</span> ${TF.esc(truth.name)}</span>`;
  }
  function faceName(slot) {
    const f = actorFace(slot);
    return f.tagged || f.name;
  }
  function faceNameHtml(slot) {
    const f = actorFace(slot);
    const name = TF.esc(f.tagged || f.name);
    return f.emoji ? `<span class="fake-name">${name}</span>` : name;
  }
  function faceCaption(slot) {
    const shown = faceName(slot);
    const truth = trueFace(slot);
    return truth.name ? `${shown} · true ${truth.name}` : shown;
  }
  function faceJoin(slots) {
    const names = (slots || []).filter((s) => s && s !== "none").map(faceName);
    return names.join(" → ") || "—";
  }
  function faceJoinHtml(slots) {
    const names = (slots || []).filter((s) => s && s !== "none").map(faceNameHtml);
    return names.join(" → ") || "—";
  }


  function markup(meta, full, model) {
    current={meta,full};
    const labels=full.annotation?.trajectory_pass?.labels || {};
    const called=model.audit.called, risky=full.annotation?.focal_actor_slot, adopted=labels.primary_adopted_source;
    const actors=['A','B','C','D'];
    const nFan=4;
    const blocks=model.events.map(e=>({actor:e.actor}));
    return `<div class="scene" data-mode="orch" data-n="${nFan}" aria-label="Orchestration">
      <svg class="scene-svg" aria-hidden="true"></svg>
      <div class="scene-orch active" role="button" tabindex="0" data-node="orch">
        ${pairLogos(meta.system, "lg")}
        <div class="scene-copy">
          <div class="lab">Orchestrator</div>
          <div class="nm">${TF.esc(TF.fmtSys(meta.system))}</div>
        </div>
      </div>
      <div class="scene-fan">${actors.map((a, i) => {
        const face = actorFace(a);
        const truth = trueFace(a);
        const n = model.events.filter(e => e.actor === 'orchestrator' && e.kind === 'call' && e.delegate && e.target === a).length;
        const fake = !!face.emoji;
        const cls = [a === risky ? "risky" : "", a === adopted ? "adopted" : "", called.includes(a) ? "called" : "", fake ? "fake" : ""].filter(Boolean).join(" ");
        const st = [face.sub, called.includes(a) ? "consulted" : "idle", a === adopted ? "adopted" : "", a === risky ? "risky" : ""].filter(Boolean).join(" · ");
        return `<div class="scene-sub ${cls}" role="button" tabindex="0" data-node="sub" data-actor="${a}" title="${TF.esc(`${fake ? "attack nametag" : "shown"} ${face.name} · true ${truth.name}${face.hint ? " · " + face.hint : ""}`)}">
          ${actorOrb(face, truth, i * 0.45)}
          <span class="nm">${face.emoji ? `<span class="nm-mark" title="${TF.esc(face.hint)}">${face.emoji}</span> ` : ""}${TF.esc(face.name)}${fake ? `<span class="fake-chip">fake</span>` : ""}</span>
          ${trueLine(truth)}
          <span class="st">${TF.esc(st)} · ${n} calls</span>
        </div>`;
      }).join("")}</div>
      <div class="scene-legend">
        <button type="button" class="watch-btn" data-flow-play>Watch the loop</button>
        <button type="button" class="watch-btn quiet" data-flow-reset>Reset</button>
        <span class="legend-key fake">Displayed identity</span>
        <span class="legend-key true">Actual backbone</span>
        <span class="beat-cap">On the orchestrator</span>
      </div>
    </div>`;

  }
  function mount(container, meta, full, model, onActor, onPlay, onReset) {
    const called=model.audit.called, actors=['A','B','C','D'];
    container.innerHTML=markup(meta, full, model);
    let frame=0, disposed=false;
    const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
    function draw() {
      if(disposed)return;
      const scene=container.querySelector('.scene'), svg=container.querySelector('.scene-svg'), root=container.querySelector('.scene-orch');
      const r=scene.getBoundingClientRect(), o=root.getBoundingClientRect();
      if(!r.width||!r.height)return;
      svg.setAttribute('viewBox', '0 0 '+r.width+' '+r.height);
      const ox=o.left+o.width/2-r.left, oy=o.bottom-r.top-2;
      svg.innerHTML=[...container.querySelectorAll('.scene-sub')].map(n=>{
        const icon=n.querySelector('.orb-stage').getBoundingClientRect(), x=icon.left+icon.width/2-r.left, y=icon.top+icon.height/2-r.top, mid=oy+(y-oy)*.45;
        return '<path data-wire="'+n.dataset.actor+'" class="wire-path '+(called.includes(n.dataset.actor)?'hot':'')+'" d="M'+ox+','+oy+' C'+ox+','+mid+' '+x+','+mid+' '+x+','+y+'" fill="none"/><circle data-packet="'+n.dataset.actor+'" class="spark" r="4" opacity="0"/>';
      }).join('');
    }
    function packet(actor, up) {
      cancelAnimationFrame(frame);
      container.querySelectorAll('.spark').forEach(n=>n.setAttribute('opacity','0'));
      if(reduced()||disposed)return;
      const line=container.querySelector('[data-wire="'+actor+'"]'), dot=container.querySelector('[data-packet="'+actor+'"]');
      if(!line||!dot)return;
      const length=line.getTotalLength(), start=performance.now();
      dot.setAttribute('opacity','1');
      const tick=now=>{if(disposed)return;const p=Math.min(1,(now-start)/650), point=line.getPointAtLength((up?1-p:p)*length);dot.setAttribute('cx',point.x);dot.setAttribute('cy',point.y);if(p<1)frame=requestAnimationFrame(tick);else dot.setAttribute('opacity','0');};
      frame=requestAnimationFrame(tick);
    }
    const click=event=>{const node=event.target.closest('[data-node]');if(node)onActor(node.dataset.actor || 'orchestrator');if(event.target.closest('[data-flow-play]'))onPlay();if(event.target.closest('[data-flow-reset]'))onReset();};
    const key=event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[data-node]')){event.preventDefault();event.target.click();}};
    container.addEventListener('click',click);container.addEventListener('keydown',key);
    const observer=new ResizeObserver(draw);observer.observe(container);requestAnimationFrame(draw);
    return {
      focus(event) {
        const actor=event.actor==='orchestrator'?event.target:event.actor;
        const active=actors.includes(actor), scene=container.querySelector('.scene');
        scene.dataset.mode=active?'sub':'orch';
        container.querySelector('.scene-orch').classList.toggle('active',!active);
        container.querySelectorAll('.scene-sub').forEach(n=>n.classList.toggle('live',n.dataset.actor===actor));
        container.querySelector('.beat-cap').textContent=active?'Subagent '+actor+' · '+event.title:event.kind==='judge'?'Evaluator-only record':'Orchestrator · '+event.title;
        if(event.delegate&&event.kind==='call')packet(actor,false);
        if(event.delegate&&event.kind==='result'&&event.title!=='sessions_spawn')packet(actor,true);
      },
      playing(value){container.querySelector('[data-flow-play]').textContent=value?'Pause loop':'Watch the loop';},
      dispose(){disposed=true;cancelAnimationFrame(frame);observer.disconnect();container.removeEventListener('click',click);container.removeEventListener('keydown',key);}
    };
  }
  window.TF_FLOW={mount,pairLogos,markup};
})();
