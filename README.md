# LSMS Agent

🚀 **Live app:** <https://xcz1234-lsms-agent.hf.space> *(private Hugging Face Space)* · 🌐 **Landing page:** <https://caizhen-x.github.io/lsms-agent/>

Access requires both **(1)** a Hugging Face account that has been granted access to the Space by the maintainer, **and (2)** the shared group password. Reach out to the maintainer for either.

A natural-language analysis agent over **LSMS-ISA household survey data** for 8 African countries — Burkina Faso, Ethiopia, Malawi, Mali, Niger, Nigeria, Tanzania, Uganda. Ask in plain English; it searches the variable catalog, writes the Python, runs the analysis, and returns tables and plots.

---

## Why it exists

LSMS data is rich but painful to use. Every country names its variables differently. Every survey round restructures the modules. Questionnaires are scattered PDFs. Even *finding the right variable* before any analysis can eat an afternoon.

This agent makes that workflow feel like a conversation. You ask about a concept ("years of schooling", "household food expenditure", "fertilizer use", "land area cultivated") and it tells you which module in which round of which country has the data — then loads it, transforms it, and runs whatever you asked for.

## What's in the catalog

Built from raw World Bank LSMS-ISA downloads via `make all-ingest`:

| | Count |
|---|---:|
| Countries | **8** |
| Survey rounds | **30** |
| Data modules (Stata + CSV) | **2,712** |
| Variables indexed (with labels & value-labels where present) | **76,775** |
| Parquet footprint at runtime | ~417 MB |

Per-country round coverage:

| Country | Rounds |
|---|---|
| Burkina Faso | 2014 EMC |
| Ethiopia | 2011 ERSS W1, 2013 ESS W2, 2015 ESS W3, 2018 ESS W4 |
| Malawi | 2004 IHS2, 2010 IHS3, 2010-2013 IHPS, 2016 IHS4 |
| Mali | 2014 EACI, 2017 EACI |
| Niger | 2011 ECVMA W1, 2014 ECVMA W2 |
| Nigeria | 2010, 2012, 2015, 2018 GHS-Panel (W1–W4) |
| Tanzania | 2008, 2010, 2012, 2014 NPS (W1–W4), 2019 NPS-SDD, 2020 NPS W5 |
| Uganda | 2005, 2010, 2011, 2013, 2015, 2018, 2019 UNPS (W1–W7) |

## What you can actually ask it

### Variable discovery

> *"Find every variable that captures years of schooling in Tanzania."*
> *"What variables relate to food consumption in Malawi 2016?"*
> *"Which Ugandan rounds have a fertilizer-use indicator?"*

Returns hits across modules with the full variable name, label, value labels (where Stata-labelled), and the exact module path you can load.

### Data exploration

> *"Load the Tanzania 2010 W2 household module and show me `df.shape`, `df.dtypes`, and the first 5 rows."*
> *"What's the distribution of household size in Uganda 2019? Mean, median, p10/p90, and a histogram."*
> *"Show me a crosstab of urban/rural × education attainment in Ethiopia 2018."*

The agent uses a subprocess Python sandbox with pandas / numpy / matplotlib / seaborn / statsmodels preloaded. State persists within a session unless a timed-out call kills and resets that session's worker.

### Panel construction (single country, across rounds)

> *"Merge the Tanzania 2010 and 2012 household sections on `hhid` and report the panel balance: how many households appear in both waves vs. one wave only."*
> *"Build a three-wave panel from Nigeria GHS-Panel W1, W2, W3 using individual IDs. Show me attrition between waves."*

### Cross-country comparison

> *"Compare mean household size across Tanzania 2014 and Uganda 2015. Are the differences statistically significant?"*
> *"Plot the distribution of years of schooling for women aged 25–35 in Ethiopia 2018 vs Tanzania 2014."*

### Regressions and modelling

> *"Regress log per-capita consumption on years of schooling, household size, and urban/rural in Ethiopia 2018. Report coefficients with HC1-robust SEs."*
> *"In Uganda 2019, estimate the relationship between farm plot size and self-reported food security. Use linearmodels for clustered SEs at the EA level."*

### Plotting

> *"Histogram of household consumption per capita, log scale, Malawi 2016."*
> *"Scatter plot of plot area vs. yield for maize plots in Nigeria 2015, with a LOWESS smoother."*
> *"Stacked bar of education attainment by gender across all Tanzania rounds."*

Plots are rendered inline in the chat as PNGs.

### Working without questionnaires (graceful degradation)

Several rounds shipped as **CSV-only** from the World Bank and have no Stata labels (e.g. Tanzania W3 onward, Nigeria GHS-Panel, Malawi IHS4). For those modules, the agent only has column names — it'll say so honestly, peek at the data, and use the agent's domain knowledge to make sense of it.

## How it works under the hood

```
┌────────────────────────────────────────────────────────────────┐
│  Chainlit chat UI  (login-gated, runs on Hugging Face Spaces)  │
└────────────────────────────────────────────────────────────────┘
                              │
            User prompt ──────▼──────  conversation history
┌────────────────────────────────────────────────────────────────┐
│  Claude Sonnet 4.6  +  system prompt  +  tool use loop         │
│                                                                │
│   tools available to the model:                                │
│   ├─ list_countries_and_rounds()                               │
│   ├─ list_modules(country, round)                              │
│   ├─ search_variables(query, country?, round?)                 │
│   ├─ search_docs(query, country?, round?)                      │
│   ├─ list_crosswalks(country)                                  │
│   ├─ lookup_crosswalk(country, concept)                        │
│   └─ run_python(code)                                          │
└────────────────────────────────────────────────────────────────┘
                              │
                              ▼
   ┌─────────────────────────────┐    ┌────────────────────────┐
   │  variables.parquet          │    │  subprocess sandbox    │
   │  (76,775 rows)              │    │  per chat session;     │
   │  one row per variable       │    │  pandas/np/matplotlib  │
   │  per module per round       │    │  pre-loaded;           │
   │  per country                │    │  60s/call timeout;     │
   └─────────────────────────────┘    │  data mounted RO.      │
                                      └────────────────────────┘
                                                  │
                                                  ▼
                                      ┌────────────────────────┐
                                      │ catalog/parquet/...    │
                                      │ (per-country, per-round│
                                      │  per-module .parquet)  │
                                      └────────────────────────┘
```

1. **Ingest** (one-time, locally): `make all-ingest` walks `Country Data/`, converts every `.dta` and `.csv` to Parquet, and extracts variable labels / value labels into a single searchable catalog.
2. **Chat** (live): each session gets a private subprocess Python sandbox + a fresh Claude conversation. The model decides what to search, what to load, and what code to run. Tool calls are rendered in collapsible steps so you can audit what happened.
3. **Output**: plain prose answers, tables, and inline plots. The agent doesn't show its Python by default — your researchers see results, not code — but it's available behind the tool-step expanders if you want to verify.

## Security model

- Login: shared group password (HF Spaces secret). This is suitable only for a known group; private Space visibility is recommended.
- Cookies: JWT signed with `CHAINLIT_AUTH_SECRET`, stored in a Python variable and scrubbed from `os.environ` so sandbox code can't read it.
- Secrets: `ANTHROPIC_API_KEY` / `GROUP_PASSWORD` / HF tokens are captured at startup then deleted from `os.environ`. The anthropic SDK still gets the key (passed explicitly), but `os.environ` inspection from inside the sandbox returns nothing useful.
- Fail-closed: if `GROUP_PASSWORD` is unset at boot, the app refuses to start (no accidental open-door).
- Sandbox: each chat session gets a subprocess worker, and timed-out code is killed with `proc.kill()`. `run_python` output is capped, and geovariable/GPS/coordinate/tracking modules are hidden and blocked unless `ALLOW_SENSITIVE_MODULES=true`.
- **Trust model**: this is for a known internal research group. The sandbox has guardrails, but it is not a hostile-user containment boundary. If the HF Space is public, files committed to the Space repo can still be downloaded directly from Hugging Face, bypassing app login.

## Setup (self-hosters)

```bash
# 1. Install deps
make install

# 2. Configure
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and GROUP_PASSWORD

# 3. Put the LSMS data in ./Country Data/ (see Data layout below).  Not committed.

# 4. One-time ingest: convert .dta/.csv -> parquet, build variable catalog.
make all-ingest

# 5. Run the chat app
make run    # opens http://localhost:8000
```

For Hugging Face Spaces deployment (the live URL above), see [`DEPLOY.md`](./DEPLOY.md).

## Data layout

`Country Data/` lives next to this README and is structured by `scripts/reorganize.py`:

```
Country Data/
├── _manifest.yaml
├── Burkina Faso/2014_EMC/{data,refs}/
├── Ethiopia/{2011_ERSS_W1, 2013_ESS_W2, 2015_ESS_W3, 2018_ESS_W4}/{data,refs}/
├── Malawi/{2004_IHS2, 2010_IHS3, 2010_IHPS, 2016_IHS4}/{data,refs}/
├── Mali/{2014_EACI, 2017_EACI}/{data,refs}/
├── Niger/{2011_ECVMA_W1, 2014_ECVMA_W2}/{data,refs}/
├── Nigeria/{2010_GHSP_W1, 2012_GHSP_W2, 2015_GHSP_W3, 2018_GHSP_W4}/{data,refs}/
├── Tanzania/{2008_NPS_W1, 2010_NPS_W2, 2012_NPS_W3, 2014_NPS_W4, 2019_NPS_SDD, 2020_NPS_W5}/{data,refs}/
└── Uganda/{2005_UNPS_W1, 2010_UNPS_W2, 2011_UNPS_W3, 2013_UNPS_W4, 2015_UNPS_W5, 2018_UNPS_W6, 2019_UNPS_W7}/{data,refs}/
```

Round-key format: `YYYY_<SURVEY>_W<n>` (Wn omitted for single-round countries).

## Status & honest limits

What works today:

- ✅ All 8 ISA countries ingested into a single catalog (76,775 variables across 30 rounds, 2,712 modules)
- ✅ Keyword variable search over names + labels
- ✅ **Questionnaire / PDF retrieval (`search_docs`)** — BM25 search over 266 reference PDFs (13,449 text chunks). The agent can now quote the actual survey question that defined a variable, for any country/round.
- ✅ **Crosswalks (`list_crosswalks` / `lookup_crosswalk`)** — curated YAML files under `crosswalks/<country>/<concept>.yaml` map a concept (e.g. `household_id`, `years_of_schooling`) to per-round variable + module paths. Starts empty; accumulates as researchers add files. See [`crosswalks/README.md`](./crosswalks/README.md) for the format.
- ✅ **Audit log + per-user rate limit** — every chat turn appends `{ts, user, prompt_head, tools}` to a JSONL audit file; per-user token bucket (default 30 turns/hour, 200/day) caps damage from a leaked password.
- ✅ Subprocess-per-session Python sandbox with kill-on-timeout, scrubbed env, and `pd.read_parquet` locked to the policy-checked `load_module` path
- ✅ Default-block on geo/GPS/coordinate/tracking modules and on sensitive column names (lat/lon/phone/email/address/name etc.); opt in with `ALLOW_SENSITIVE_MODULES=true` only after confirming data-use terms
- ✅ Output caps on `run_python` (capped stdout/stderr with truncation marker, max 4 figures per call)
- ✅ Login gating, fail-closed auth, env-scrubbed secrets (incl. `CHAINLIT_AUTH_SECRET`), import-blocked network libraries in the sandbox
- ✅ Disambiguated module paths (resolves Malawi 2010 IHS3 Panel/ vs Full_Sample/ collisions correctly)
- ✅ Hugging Face Space deployed as **Private** so the committed parquet files are not publicly downloadable

What's missing or rough:

- ❌ Semantic / vector search over variables — search is keyword-only.  With `search_docs` now indexing questionnaires, the marginal value of semantic variable search is lower than before; deferred until it bites.
- ❌ Per-user identity via HF OAuth — the current audit log records whatever email a user typed into Chainlit; a leaked password still grants the same access level.  Rate limit + audit help, but they don't replace true per-user accounts.
- ❌ Audit log durability — log is written to `/tmp` and lost on Space restart.  Acceptable for v0; point `AUDIT_LOG_PATH` at HF persistent storage for durability.
- ❌ A handful of reference PDFs (Tanzania W3/W4/SDD/W5, Niger W2, Nigeria W2) are missing due to interrupted downloads.  Those rounds have reduced `search_docs` coverage.  See `Country Data/_missing_references_checklist.md` if rebuilding the data tree.

## Roadmap

Next, in priority order:

1. **Per-user identity via HF OAuth** — replace the shared password with `chainlit_oauth=huggingface` so each researcher logs in as themselves; revoke per-user when needed; the existing audit log automatically becomes more useful.
2. **Vector search over variables** — semantic match on labels (Voyage `voyage-3-large` embeddings) for synonym handling. Lower priority now that `search_docs` covers the "what does this mean" question.
3. **Auto-suggested crosswalks** — let the agent draft a YAML under `crosswalks/<country>/<concept>.yaml` and surface it for the user to approve / commit. Builds the crosswalk library passively as researchers use the tool.
4. **Durable audit log** — point `AUDIT_LOG_PATH` at HF persistent storage; rotate weekly.
5. **Result export** — download chat outputs (tables, plots, the generated Python) as a notebook.

## Tools the agent has (technical reference)

| Tool | Signature | What it returns |
|---|---|---|
| `list_countries_and_rounds` | `()` | Per-country list of round keys + module counts. |
| `list_modules` | `(country, round)` | Per-module `module_path`, `module_file`, `n_variables`. Sensitive modules (geo/GPS/coordinate/tracking) are filtered out and counted under `sensitive_modules_hidden` unless `ALLOW_SENSITIVE_MODULES=true`. |
| `search_variables` | `(query, country?, round?, limit=30)` | Hits with `module_path`, `var_name`, `label`, value labels for top-5. Hits inside sensitive modules are filtered and counted under `n_sensitive_hidden`. |
| `search_docs` | `(query, country?, round?, limit=6)` | BM25 ranking over 13,449 chunks from 266 reference PDFs. Returns `country`, `round`, `pdf`, `page`, `score`, `snippet`. Use to quote the actual survey question or codebook definition behind a variable. |
| `list_crosswalks` | `(country)` | Names of curated concepts for that country (e.g. `household_id`, `years_of_schooling`). |
| `lookup_crosswalk` | `(country, concept)` | Per-round `{module_path, variable, label, notes}` mapping from `crosswalks/<country>/<concept>.yaml`. |
| `run_python` | `(code)` | `stdout`, `stderr`, truncation flags, `figures`, `error`, `worker_restarted`. Runs in a per-session subprocess; timeouts kill the worker via `proc.kill()` and the next call boots a fresh one. Output is capped (default 4,000 chars stdout, 2,000 chars stderr, 4 figures). `pd.read_parquet` is replaced by `load_module(country, round, module_path)` — the agent cannot bypass the data policy by reading parquet directly. |

## License

Code: internal research-group use only.
Data: distributed under the World Bank LSMS-ISA data use agreement; not committed to this repo.

## Acknowledgements

Data: [World Bank LSMS-ISA](https://www.worldbank.org/en/programs/lsms/initiatives/lsms-ISA).
Model: Anthropic Claude Sonnet 4.6.
Stack: Chainlit, FastAPI, pandas, Anthropic SDK.
