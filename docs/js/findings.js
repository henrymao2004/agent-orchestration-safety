(function () {
  const TF = window.TF;
  const D = window.TF_DESIGN;
  TF.boot("findings");

  const AXES = [
    {
      title: "Identity presentation",
      items: [
        ["M0", "Hidden identity."],
        ["M1", "Real model identity."],
        ["M2", "Exchanged model identity."],
        ["M3", "Real capability tier."],
        ["M4", "Reversed tier defined by the operator."],
        ["M5", "Real family relation."],
        ["M6", "Reversed displayed family relation."],
      ],
    },
    {
      title: "Risky-subagent goal",
      items: [
        ["G1", "Advice that ignores risk."],
        ["G2", "Behavior shaped by the scenario attack."],
        ["G3", "Behavior that seeks authority."],
      ],
    },
    {
      title: "Consultation breadth",
      items: [
        ["free", "No restriction: the orchestrator chooses how many subagents to call."],
        ["b2", "Admit exactly two subagents."],
        ["b4", "Consult all four subagents."],
      ],
    },
    {
      title: "Subagent backbones",
      items: [
        ["P0", "Repetition of the exact backbone."],
        ["P1", "One exact backbone among same-tier alternatives from other families."],
        ["P2", "Same-family opposite tier among models from other families."],
        ["P3", "Repetition within the same family at the opposite tier."],
      ],
    },
  ];

  // Scores are 0–100 vulnerability, higher values indicate greater vulnerability.
  const SYSTEMS = [
    { group: "OpenCode", rows: [
      ["GPT-5.6-Sol", 17.7, 23.2, 4.5, 24.9, 15.5, 9.3, 48.6, 20.5, 10.3],
      ["GPT-5.6-Luna", 10.5, 20.8, 7.3, 30.3, 19.4, 14.7, 75.1, 27.6, 11.8],
      ["Kimi-K3", 17.7, 22.5, 1.8, 20.0, 34.3, 13.3, 92.0, 12.6, 15.7],
      ["Kimi-K2.6", 19.6, 26.7, 5.3, 25.6, 31.3, 16.4, 100.0, 13.6, 17.2],
      ["GLM-5.2", 13.0, 27.6, 4.9, 30.0, 24.2, 13.8, 77.0, 17.9, 15.1],
      ["GLM-4.7", 18.1, 35.7, 17.0, 53.8, 50.8, 36.6, 86.1, 34.3, 23.8],
      ["Minimax-M3", 9.4, 25.2, 4.7, 24.9, 23.5, 14.0, 77.7, 17.6, 14.8],
      ["Minimax-M2.5", 24.3, 41.5, 18.9, 46.0, 52.4, 37.8, 76.0, 31.3, 25.4],
    ]},
    { group: "OpenClaw", rows: [
      ["GLM-5.2", 17.8, 28.3, 2.5, 13.2, 14.0, 9.1, 66.7, 13.4, 21.7],
      ["GLM-4.7", 25.9, 53.7, 20.1, 53.8, 46.6, 40.2, 57.7, 36.5, 41.3],
      ["Minimax-M3", 28.1, 35.1, 5.2, 25.7, 31.3, 25.5, 48.0, 16.7, 51.1],
      ["Minimax-M2.5", 40.2, 67.8, 26.1, 66.0, 56.2, 49.7, 90.9, 42.0, 38.5],
    ]},
    { group: "Pi", rows: [
      ["GPT-5.6-Sol", 25.6, 28.6, 1.8, 23.9, 15.1, 8.6, 55.4, 17.1, 12.6],
      ["GPT-5.6-Luna", 25.0, 31.3, 3.3, 29.0, 23.4, 12.2, 53.1, 23.9, 14.1],
      ["Minimax-M3", 18.1, 31.9, 4.5, 23.1, 22.2, 13.8, 65.3, 20.6, 17.7],
      ["Minimax-M2.5", 35.4, 51.1, 23.9, 48.5, 53.4, 43.2, 83.1, 33.2, 34.4],
    ]},
  ];
  const COLS = ["RTF", "RSR", "IAS", "SAF", "VF", "EI", "CAR", "TH", "TUL"];
  const ORDER = [0, 1, 2, 3, 4, 5, 7, 8, 6];
  const SHOWN = ORDER.map((j) => COLS[j]);

  const CAR = { id: "CAR", name: "Captured Authority Rate", stage: "Revision",
    blurb: "How often the risky response is still adopted or governs execution after evidence contradicts it." };
  document.getElementById("metrics").innerHTML = [CAR].concat(D.metrics).map((m) =>
    `<article class="dim"><header><span class="tag">${m.id}</span><span class="muted">${m.stage}</span></header>
     <h3 style="margin-top:8px;font-size:16px">${m.name}</h3>
     <p class="muted" style="margin-top:6px">${m.blurb}</p></article>`
  ).join("");

  document.getElementById("axes").innerHTML = AXES.map((ax) =>
    `<article class="axis"><h3>${ax.title}</h3>${ax.items.map(([id, t]) =>
      `<div class="axis-item"><span class="tag">${id}</span><span>${t}</span></div>`
    ).join("")}</article>`
  ).join("");

  const head = `<thead><tr><th>Harness</th><th>Backbone</th>${SHOWN.map((c) =>
    c === "CAR" ? `<th><strong>${c} ↑</strong></th>` : `<th>${c} ↑</th>`).join("")}</tr></thead>`;
  const body = SYSTEMS.map((g) => g.rows.map((r, i) => {
    const cells = ORDER.map((j) => {
      const v = r[j + 1];
      const worst = Math.max(...g.rows.map((row) => row[j + 1]));
      const text = v === worst ? `<strong>${v.toFixed(1)}</strong>` : v.toFixed(1);
      return `<td class="num">${text}</td>`;
    }).join("");
    const harness = i === 0 ? `<td class="harness-cell" rowspan="${g.rows.length}">${g.group}</td>` : "";
    return `<tr>${harness}<td>${r[0]}</td>${cells}</tr>`;
  }).join("")).join("");
  document.getElementById("sysTable").innerHTML = head + `<tbody>${body}</tbody>`;

  const bib = document.getElementById("bibtex");
  bib.textContent = D.bibtex;
  document.getElementById("copyCite").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(D.bibtex);
      document.getElementById("copyCite").textContent = "Copied";
    } catch (_) {
      document.getElementById("copyCite").textContent = "Select the block";
    }
  });

  const links = [...document.querySelectorAll(".find-toc a")];
  const sections = links.map((a) => document.querySelector(a.getAttribute("href"))).filter(Boolean);
  const mark = () => {
    const y = window.scrollY + 120;
    let cur = sections[0];
    for (const s of sections) if (s.offsetTop <= y) cur = s;
    links.forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + cur.id));
  };
  window.addEventListener("scroll", mark, { passive: true });
  mark();
})();
