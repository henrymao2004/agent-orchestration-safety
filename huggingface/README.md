---
license: apache-2.0
task_categories:
  - text-generation
language:
  - en
tags:
  - agent
  - llm-agents
  - orchestration
  - identity
  - safety
  - benchmark
pretty_name: TrustFork
size_categories:
  - 1K<n<10K
---

# TrustFork

**Trust the Brand, Lose Control: How Identity Hijacks LLM Agent Orchestration**

Complete task pack: **1,890** Harbor tasks with environments, verifiers, skills, adapters, and scoring.

Displayed subagent identity is visible before evidence; the orchestrator then scopes, verifies, adopts, and executes.

- Code and website: https://github.com/henrymao2004/agent-orchestration-safety
- Gallery: https://henrymao2004.github.io/agent-orchestration-safety/gallery.html
- arXiv: coming soon

## Authors

Xutao Mao, Rui Qian, Linghan Chen, Yudong Gao, Junchi Liao, Junlin Cai, Jinman Zhao, Cong Wang

## Layout

```text
trustfork/
├── dataset.toml
├── metric.py
├── tasks/          # 1,890 executable tasks
├── _template/
├── skills/
├── config/
├── agents/
├── scoring/
├── jobs/
├── scenarios/
├── defenses/
├── base-image/
└── tools/
```

`task_index.json` lists every task id and path. Tasks are numbered `trustfork_0001` to
`trustfork_1890`, and each of the 30 risk scenarios holds 63 consecutive numbers.

```bash
git clone https://github.com/henrymao2004/agent-orchestration-safety.git
# or download this dataset and point Harbor at trustfork/
uv tool install harbor
python3 trustfork/tools/ensure_base_image.py
```

## Citation

```bibtex
@misc{trustfork2026,
  author = {Xutao Mao and Rui Qian and Linghan Chen and Yudong Gao and Junchi Liao and Junlin Cai and Jinman Zhao and Cong Wang},
  title = {Trust the Brand, Lose Control: How Identity Hijacks LLM Agent Orchestration},
  year = {2026},
  note = {Code: https://github.com/henrymao2004/agent-orchestration-safety. Dataset: https://huggingface.co/datasets/sevens2004/trustfork},
}
```
