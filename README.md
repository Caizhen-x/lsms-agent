# LSMS Agent

🚀 **Live app:** <https://xcz1234-lsms-agent.hf.space> · 🌐 **Landing page:** <https://caizhen-x.github.io/lsms-agent/>

(Access is gated by a shared group password — ask the maintainer.)

Natural-language analysis agent over LSMS-ISA survey data for 8 African countries (Burkina Faso, Ethiopia, Malawi, Mali, Niger, Nigeria, Tanzania, Uganda).

Ask in plain English — "find education variables in Tanzania W2", "merge Tanzania W2 and W3 on `hhid`", "regress consumption on education in Uganda 2010" — and the agent searches the variable catalog, writes Python, and returns tables / plots.

See `LSMS Automation - Architecture Plan.md` for the full design.

## Status

**v0 walking skeleton.** All 8 countries ingested. Keyword variable search. Run-Python sandbox in chat. Questionnaire retrieval and merge helpers are deferred.

## Deployment

The chat app runs on Hugging Face Spaces (Docker). Landing page is on GitHub Pages. See [DEPLOY.md](./DEPLOY.md) for the one-time setup steps.

## Setup

```bash
# 1. Install deps
make install

# 2. Configure
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY and GROUP_PASSWORD

# 3. Put the LSMS data in ./Country Data/ (see "Data layout" below).  Not committed.

# 4. One-time ingest: convert .dta/.csv -> parquet, build variable catalog
make all-ingest

# 5. Run the chat app
make run    # opens http://localhost:8000
```

## Data layout

The repo expects `Country Data/` next to this README, organized by reorganize.py:

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

Round key format: `YYYY_<SURVEY>_W<n>` (Wn omitted for single-round countries).

If you need to re-create this layout from a fresh download, run `python scripts/reorganize.py`.

## Architecture (v0)

- **LLM**: Claude Sonnet 4.6 via Anthropic SDK, tool use, prompt caching on system+tools.
- **UI**: Chainlit (Python, chat-first, renders tables/figures natively).
- **Auth**: single shared group password.
- **Storage**: Parquet files under `catalog/parquet/<country>/<round>/`. Variable catalog at `catalog/variables.parquet`.
- **Sandbox**: in-process IPython kernel per chat session, 60s per-call timeout, `Country Data/` mounted read-only via env var `LSMS_DATA_DIR`. Trusted users only — this is not a hostile-input sandbox.

### Tools the agent has

| Tool | Purpose |
|---|---|
| `list_countries_and_rounds` | Inventory of what's available |
| `list_modules(country, round)` | What data files exist in a round |
| `search_variables(query, country?, round?)` | Substring/keyword search over variable names + labels |
| `run_python(code)` | Execute Python in the session kernel — pandas, numpy, statsmodels, matplotlib preloaded |

## Deferred (not in v0)

- Questionnaire / PDF retrieval (`search_docs`)
- Vector / semantic search over variables
- Merge crosswalks across rounds
- Cloud deployment
- Multi-user / per-user history

## License

Internal research group use only.
