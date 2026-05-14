# LSMS Automation — Architecture Plan

**Status:** v0 draft, 2026-05-14
**Goal:** Internal chatbot platform for the research group that turns natural-language requests into LSMS data answers — variable discovery, cross-round / cross-country merges, exploratory stats, regressions, plots — over all African LSMS survey data.

---

## 1. Scope clarification (decide before build)

"LSMS in Africa" splits into two groups:

- **LSMS-ISA (Integrated Surveys on Agriculture)** — harmonized methodology, 8 countries:
  Burkina Faso, Ethiopia, Malawi, Mali, Niger, Nigeria, Tanzania, Uganda.
- **Broader LSMS family** in Africa — *not* harmonized with ISA:
  Côte d'Ivoire (CILSS), Ghana (GLSS), Kenya (KIHBS), South Africa (NIDS), Sierra Leone, etc.

**Default plan:** Phase 1–3 covers ISA-only (8). Phase 4 extends to the rest. The extension is mostly extra ingest edge cases; the agent and UI don't change.

---

## 2. Repository layout

```
lsms-agent/
├── countries/                              # raw data, owned by user
│   ├── tanzania/
│   │   ├── data/
│   │   │   ├── round_2008_nps_w1/*.dta
│   │   │   ├── round_2010_nps_w2/*.dta
│   │   │   └── round_2012_nps_w3/*.dta
│   │   └── questionnaire/
│   │       ├── round_2008_nps_w1/*.pdf
│   │       ├── round_2010_nps_w2/*.pdf
│   │       └── round_2012_nps_w3/*.pdf
│   ├── ethiopia/
│   ├── malawi/
│   └── ...
├── catalog/                                # built artifacts (gitignored)
│   ├── variables.parquet                   # flat variable catalog
│   ├── data_parquet/                       # .dta converted to .parquet
│   └── indexes/
│       ├── variables.qdrant/
│       └── docs.qdrant/
├── ingest/                                 # one-time + incremental ETL
│   ├── convert_dta_to_parquet.py
│   ├── extract_variables.py
│   ├── parse_questionnaires.py
│   └── build_indexes.py
├── server/                                 # FastAPI backend
│   ├── tools/
│   │   ├── search_variables.py
│   │   ├── search_docs.py
│   │   ├── load_data.py
│   │   └── run_python.py
│   ├── agent.py                            # Claude tool-use loop
│   ├── sandbox.py                          # Docker-based code execution
│   └── auth.py                             # group password
├── app/                                    # Chainlit chat UI
├── admin/                                  # Streamlit "verification" page (you only)
├── docker-compose.yml
└── README.md                               # GitHub landing
```

User-facing rule: drop a country folder in `countries/`, run `make ingest`, the agent knows about it.

---

## 3. Stack

| Layer | Choice | Why |
|---|---|---|
| LLM | **Claude Sonnet 4.6** with prompt caching on system prompt + tool list | Strong tool use + reasoning at moderate cost; caching pays for itself in multi-turn analysis sessions |
| Backend | FastAPI (Python) | Same language as analysis code |
| Chat UI | **Chainlit** | Purpose-built for LLM chat in Python; renders tables/plots/intermediate steps natively; one container to deploy |
| Data format | Convert `.dta` → **Parquet** at ingest; keep `.dta` originals | 5–20× smaller, ~50× faster reads with pandas / polars / duckdb |
| Variable catalog | One `variables.parquet`, one row per (country, round, module, variable) | Simple to query, supports keyword + vector search |
| Vector store | Qdrant (self-hosted via Docker) | Free, fast, two collections: variables + doc chunks |
| Embeddings | Voyage `voyage-3-large` | Anthropic-recommended; strong on short labels (variable text) |
| Code sandbox | Docker container with Jupyter kernel, data mounted **read-only**, no network, CPU/RAM limits | Trusted users (your group); pragmatic isolation, restarted per session |
| Auth | Single shared **group password** → HTTP-only signed session cookie, 30-day expiry | Matches your ask |
| Hosting | One VM (Hetzner CX42 or DO 8GB+, ~$40–60/mo, 16GB RAM, 200GB disk) running everything via `docker-compose` | Keeps data local as you want; single-box ops |
| GitHub landing | Static `index.html` on GitHub Pages → "Open App" button → VM URL | Matches your end-product vision |

---

## 4. The two artifacts that make this work

Everything downstream depends on these. Built once at ingest, rebuilt incrementally as data is added.

### 4.1 `variables.parquet` — the variable catalog

One row per variable per module per round per country.

| column | example | source |
|---|---|---|
| country | `tanzania` | folder name |
| round | `2010_nps_w2` | folder name |
| module_file | `hh_sec_c.dta` | filename |
| var_name | `hh_c01` | pyreadstat metadata |
| label | `"Highest grade completed"` | pyreadstat metadata |
| dtype | `numeric` / `string` | pyreadstat metadata |
| value_labels | `{1:"None", 2:"Primary", ...}` | pyreadstat metadata |
| n_obs / n_missing | `18452 / 312` | quick pass on data |
| candidate_keys | `["hhid","indidy2"]` | detected join keys (see §6) |
| questionnaire_section | `"Section 2C — Education"` | linked via §4.2 |

Built with `pyreadstat.read_dta(path, metadataonly=True)` — fast, no full data load.

A parallel **vector index** over `label + value_labels + module_file` enables `search_variables("schooling years in Tanzania round 2")` to work even when variable names differ across rounds (`hh_c01` vs `educ_yrs` vs `s2c_q4`).

### 4.2 Questionnaire doc index

PDFs in `countries/<country>/questionnaire/<round>/` are parsed once:

1. PDF → text via `pymupdf` (preserves headings).
2. Chunk by section heading; fall back to ~800-token chunks with 100-token overlap.
3. Embed; store in Qdrant with metadata `{country, round, module_hint, section, page}`.
4. Best-effort link each PDF section back to a module file in `data/` (heuristic on section title vs filename). This populates `questionnaire_section` in the catalog.

---

## 5. Agent tools

The agent only ever calls these four. Keep the surface tiny — it's the only way the model stays reliable.

```python
search_variables(query: str, country: str | None, round: str | None, k: int = 20)
    -> list[VariableHit]
# Hybrid keyword + vector search over variables.parquet.

search_docs(query: str, country: str | None, round: str | None, k: int = 10)
    -> list[DocChunk]
# Vector search over questionnaire chunks. Returns text + page + source.

load_data(country: str, round: str, module_file: str)
    -> str  # path to parquet, mounted in sandbox
# Resolves a logical (country, round, module) tuple to a sandbox-readable parquet path.

run_python(code: str, session_id: str)
    -> {"stdout": str, "stderr": str, "tables": [...], "figures": [...]}
# Executes in the session's Jupyter kernel. State persists across calls in one session.
# Standard libs preloaded: pandas, polars, numpy, statsmodels, scipy, matplotlib, seaborn, linearmodels.
```

That's it. Merging, regressions, plots, summary stats — all happen inside `run_python`. The agent's job is to (a) find the right variables/files via the search tools, (b) write correct pandas code, (c) iterate on errors.

---

## 6. Handling the merge-key / harmonization problem

This is the hardest data problem you have. The agent helps but doesn't magically solve it. Approach:

1. **Per-module key detection at ingest.** For each `.dta`, identify columns that look like household / individual / plot / parcel / wave IDs (`hhid`, `indidy2`, `plotid`, `case_id`, etc.) by name patterns + uniqueness ratios. Store as `candidate_keys`.
2. **Per-round crosswalk file** (`countries/<country>/crosswalks/<round>.yaml`): handwritten, small, optional. Maps "logical entity" (e.g. `household_id`) to the actual column name in that round. Starts empty; gets populated over time, including by the agent suggesting entries.
3. **Cross-round panel join.** When the user asks to merge rounds, the agent consults the crosswalk if present, otherwise uses `candidate_keys` and asks the user to confirm before running.
4. **Cross-country comparison.** No automatic harmonization; the agent finds analogous variables via `search_variables` and writes the harmonization code per request. Successful patterns get saved as Python snippets in `recipes/` for reuse.

This is the realistic limit: an LLM agent will not produce a clean harmonized panel of all 8 ISA countries on its own. It will get you 80% of the way per query, and you'll accumulate crosswalks as a side product over time.

---

## 7. Agent flow (per user message)

```
1. User: "Find education-related variables in Tanzania round 2008 and 2010, then build a panel of years-of-schooling."

2. Agent (Claude with tool use):
   a. search_variables("education schooling years", country="tanzania", round="2008_nps_w1")
   b. search_variables("education schooling years", country="tanzania", round="2010_nps_w2")
   c. (optional) search_docs(...) to confirm question wording matches across rounds
   d. Proposes: "I found `hh_c01` (2008) and `hh_c01` (2010) both labelled 'highest grade completed'.
      I'll merge on hhid+indidy. Proceed?"
   e. On confirm: load_data + run_python writes the merge code, returns a head() + n_rows + a balance summary.

3. UI renders: agent's narrative + result table + (optionally) the figure. Python code is hidden from
   normal users but visible in the admin verification view.
```

---

## 8. Admin verification view (you only)

A separate Streamlit page at `/admin` behind your personal password, showing every session's full trace:

- User messages
- Tool calls + arguments
- Generated Python (rendered, copy-button)
- Outputs (tables / stdout / figures)
- Token + cost counters

This is your QA surface. The chat UI itself stays clean for users.

---

## 9. Phased milestones

| Phase | Output | Rough effort |
|---|---|---|
| **0. Bootstrap** | Repo skeleton, docker-compose, GitHub Pages landing, group password auth. | 1–2 days |
| **1. Ingest pipeline (1 country)** | Tanzania end-to-end: `.dta` → parquet, `variables.parquet`, questionnaire index. | 3–4 days |
| **2. Agent + tools** | Chainlit UI, four tools, Claude tool-use loop, sandbox, admin trace view. | 4–6 days |
| **3. Scale ingest to all 8 ISA countries** | Same pipeline applied; edge cases per country (Ethiopia ESS, Nigeria GHS, etc.). | 1–2 weeks (mostly debugging weird files) |
| **4. Extend to non-ISA African LSMS** | Add CILSS, GLSS, KIHBS, NIDS, etc. — more file format quirks, possibly no `.dta`. | 1–2 weeks |
| **5. Hardening** | Cost guardrails, per-user token caps, recipe library, basic logging/monitoring. | ~1 week |

Total to a usable v1 for your group: **~3–4 weeks** of focused work; **~6–8 weeks** elapsed at normal research-side pace.

---

## 10. Cost estimate (rough)

Assuming Claude Sonnet 4.6 with prompt caching, mid-sized sessions (~30k input / 3k output per turn, 10 turns/session):

- Per session: ~$0.20–0.50.
- 5 users × 5 sessions/week × 4 weeks ≈ 100 sessions/month ≈ **$20–50/mo API**.
- Hosting (VM): **$40–60/mo**.
- Embeddings: one-time at ingest, negligible (~$5–20 total for everything).

Plan for **~$100/mo total** as a comfortable ceiling for the group.

---

## 11. Open questions for you

1. **Scope confirm:** Start ISA-only (8) and extend later, or do all ~15 from the start?
2. **File format reality check:** Is everything `.dta`, or do some countries/rounds ship CSV/Excel? (Affects ingest complexity.)
3. **"Atomic dataset" = one module file?** i.e. one `.dta` paired with one PDF section, not one PDF per round.
4. **Round naming:** do you have a preferred naming convention for the `round_*` subfolders, or should I propose one?
5. **Where will the box live?** Self-managed VM is cheapest; if your university or group has existing infra, we can host there instead.
6. **Domain name:** is there a subdomain we can point to (e.g. `lsms.yourgroup.org`) or should we start with a raw IP / `xip.io`-style URL?
7. **Initial data:** when ready, which country/round should be the first end-to-end pilot? (Recommend Tanzania NPS — best-documented ISA dataset.)

---

## 12. What is explicitly **not** in v1

To avoid scope creep, the following are deferred:

- MCP server. The agent uses direct tool calls. We can wrap the same tools as an MCP server later if you want other clients (Claude Desktop, etc.) to use them.
- Multi-user permissions beyond the shared group password.
- Full automatic cross-country harmonization. Crosswalks accumulate organically.
- Public access / external sharing.
- Mobile UI optimization.
- Long-term result/notebook storage per user (you can export from chat; no server-side history beyond traces).
