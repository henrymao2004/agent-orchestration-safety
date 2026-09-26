(async function () {
  const TF = window.TF;
  const D = window.TF_DESIGN;
  TF.boot("gallery");
  const params = new URLSearchParams(location.search);
  const system = params.get("s") || "";
  const taskId = params.get("t") || "";
  const root = document.getElementById("caseRoot");
  if (!system || !taskId) {
    root.innerHTML = `<p>Missing case. <a href="gallery.html">Back to gallery</a></p>`;
    return;
  }

  function stepView(st, kind) {
    const msg = (st.message && String(st.message).trim()) || "";
    const who = st.source === "user" ? "user" : (kind || "orchestrator");
    const cls = st.source === "user" ? "user" : (kind === "subagent" ? "sub" : "");
    const body = msg
      ? `<div class="body">${TF.esc(msg.slice(0, 4000))}${msg.length > 4000 ? "…" : ""}</div>`
      : `<div class="body empty">No text on this step (tool-only in the packed trace).</div>`;
    return `<article class="tl ${cls}"><div class="who">${TF.esc(who)} · step ${TF.esc(st.step_id)}</div>${body}</article>`;
  }

  try {
    const o = await TF.loadCase(system, taskId);
    const ann = o.annotation || {};
    const raw = (ann.benchmark_scores || {}).raw_score_0_5 || {};
    const tp = ann.trajectory_pass || {};
    const why = tp.score_rationales || {};
    const labels = tp.labels || {};
    const traj = o.trajectory || {};
    const sc = D.identities.find((x) => x.id === o.identity_display_id);
    const g = D.goals.find((x) => x.id === o.actor_goal_id);
    const b = D.breadths.find((x) => x.id === o.breadth_regime);
    const p = D.pools.find((x) => x.id === o.pool_template_id);
    const idx = await TF.loadIndex();
    const card = idx.cases.find((c) => c.system === system && c.task_id === taskId);
    const title = (card && card.title) || o.scenario_id;

    document.title = `${title} — TrustFork`;
    document.getElementById("crumb").innerHTML = `<a href="gallery.html">Gallery</a> / ${TF.esc(TF.fmtSys(system))}`;
    document.getElementById("caseTitle").textContent = title;
    document.getElementById("caseSub").innerHTML =
      `${TF.esc(o.task_id)} · focal ${TF.esc(ann.focal_actor_slot || "—")} · ${TF.esc((traj.agent || {}).model_name || "")}`;

    document.getElementById("cond").innerHTML = `
      <div class="legend">
        <p><strong>Identity ${TF.esc(o.identity_display_id)}</strong> — ${TF.esc((sc && sc.threat) || "what the orchestrator saw on the roster before evidence.")}</p>
        <p><strong>Goal ${TF.esc(o.actor_goal_id)}</strong> — ${TF.esc((g && g.threat) || "private objective of one focal subagent.")} Focal slot ${TF.esc(ann.focal_actor_slot || "—")}.</p>
        <p><strong>Breadth ${TF.esc(o.breadth_regime)}</strong> — ${TF.esc((b && b.req) || "")} · <strong>Pool ${TF.esc(o.pool_template_id)}</strong> — ${TF.esc((p && p.threat) || "")}</p>
      </div>`;

    const scores = document.getElementById("scores");
    scores.innerHTML = TF.failMetrics.concat(TF.safeMetrics).map((m) => {
      const note = why[m.toLowerCase()] || "";
      return `<div class="score-card">${TF.bar(m, raw[m], TF.safeMetrics.includes(m))}${note ? `<p class="why">${TF.esc(note)}</p>` : ""}</div>`;
    }).join("");

    const orchSteps = (traj.steps || []).map((st) => stepView(st, "orchestrator")).join("");
    const subs = (traj.subagent_trajectories || []).map((sub, i) => {
      const name = (sub.agent || {}).name || `subagent ${i + 1}`;
      const model = (sub.agent || {}).model_name || "";
      const inner = (sub.steps || []).map((st) => stepView(st, "subagent")).join("");
      return `<details class="sub-block" ${i === 0 ? "open" : ""}><summary class="sub-h"><span>${TF.esc(name)} · ${TF.esc(model)}</span><span class="muted">${(sub.steps || []).length} steps</span></summary><div class="timeline">${inner}</div></details>`;
    }).join("");
    document.getElementById("traj").innerHTML = `<div class="timeline">${orchSteps}</div>${subs}`;

    const diag = document.getElementById("diag");
    const called = ((labels.call_order_by_stage || {}).all_task_calls) || [];
    diag.innerHTML = `
      <div class="score-card">
        <h3>Authority trace</h3>
        <p class="why">Called: ${TF.esc(called.join(", ") || "—")}</p>
        <p class="why">Adopted: ${TF.esc(String(labels.primary_adopted_source || "—"))}</p>
        <p class="why">Executed: ${TF.esc(JSON.stringify(labels.execution_sources || []))}</p>
        <p class="why">Trust update: ${TF.esc(String(labels.trust_update_class || "—"))}</p>
        <p class="why">Risk path: ${TF.esc(String(labels.risk_path || "—"))}</p>
      </div>`;
  } catch (err) {
    root.innerHTML = `<p>Could not load this case. Serve the site over HTTP so <code>cases/</code> can be fetched. ${TF.esc(err.message)}</p>`;
  }
})();
