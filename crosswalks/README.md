# Crosswalks

Curated equivalences across survey rounds within a country.  Each file maps **one concept** (e.g. *years of schooling*, *household ID*, *per-capita consumption*) to the actual variable name + module in every round where that concept appears.

## Why these exist

LSMS variable names drift across waves — `hh_c07` in NPS-W2 might become `educ_yrs` in NPS-W3 and `s2c_q4` in some other rebrand. Without a crosswalk the agent has to re-infer the mapping on every panel merge, which (a) wastes tokens and (b) sometimes gets it wrong silently. A crosswalk file is a one-time investment that pays off on every reuse.

## Layout

```
crosswalks/
├── <Country>/
│   ├── <concept>.yaml
│   └── ...
```

Country names match the catalog (e.g. `Tanzania`, `Burkina Faso` — with the space).

## File format

```yaml
concept: years_of_schooling
country: Tanzania
notes: |
  Best available proxy is hh_c07 in NPS waves 1-4; W5 renames it to ed_07.
  hh_c07 is reported in completed grades; SDD wave reports highest level
  attained as a categorical instead — use the value_labels to harmonize.
rounds:
  "2008_NPS_W1":
    module_path: HH_SEC_C.dta
    variable: hh_c07
    label: "Highest grade attained"
  "2010_NPS_W2":
    module_path: HH_SEC_C.dta
    variable: hh_c07
  "2012_NPS_W3":
    module_path: HH_SEC_C.csv
    variable: hh_c07
  # leave a round out if no equivalent exists
```

Fields:
- `concept` — short snake-case identifier (matches filename stem).
- `country` — must match the catalog exactly.
- `notes` — free text. Anything that would surprise the next reader belongs here.
- `rounds` — map of round key → variable spec. Each spec needs at minimum `module_path` and `variable`; `label` is helpful but optional.

## How the agent uses them

- `list_crosswalks(country)` — discover what concepts have been crosswalked.
- `lookup_crosswalk(country, concept)` — fetch the YAML for a specific concept.

The agent is instructed to call `list_crosswalks` before inventing a merge or harmonization from scratch.

## Adding one

1. Create `crosswalks/<Country>/<concept>.yaml`.
2. Use the format above.
3. Commit and push — no rebuild required; the file is read at runtime on each lookup.

## Bootstrap candidates

Concepts worth crosswalking first (high reuse value):
- `household_id` — the join key for every panel merge.
- `individual_id` — analogous for person-level panels.
- `years_of_schooling`
- `urban_rural`
- `per_capita_consumption`
- `household_size`
- `plot_area` (agriculture-heavy users)

Once a few exist they accumulate quickly — agent suggestions, user reviews, repeat.
