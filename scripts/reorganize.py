#!/usr/bin/env python3
"""
Reorganize the Country Data/ tree into a canonical layout:

    Country Data/<Country>/<round_key>/{data,refs}/...

Round key format: YYYY_<SURVEY>_W<N>  (Wn omitted for single-survey countries).

Idempotent: safe to re-run. Records every old -> new path in _manifest.yaml.
Does NOT modify file contents and does NOT rename individual files.
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "Country Data"

# (country, data_subpath, refs_subpath, round_key, notes)
# Paths are relative to <Country>/.  refs_subpath = "" means no refs available.
MAPPING: list[tuple[str, str, str, str, str]] = [
    # Burkina Faso: World Bank ID says 2013 but data files (emc2014_*) and refs both say 2014.
    ("Burkina Faso",
     "Data/BKA_2013_EMC_v01_M_CSV",
     "References/Enquête Multisectorielle Continue 2014",
     "2014_EMC", ""),

    # Ethiopia
    ("Ethiopia",
     "Data/ETH_2011_ERSS_v02_M_CSV",
     "Reference/2011-2012 ERSS Documentation",
     "2011_ERSS_W1", ""),
    ("Ethiopia",
     "Data/ETH_2013_ESS_v03_M_STATA",
     "Reference/2013-2014 ESS Documentation",
     "2013_ESS_W2", ""),
    ("Ethiopia",
     "Data/ETH_2015_ESS_v03_M_CSV",
     "Reference/2015-2016 ESS Documentation",
     "2015_ESS_W3", ""),
    ("Ethiopia",
     "Data/ETH_2018_ESS_v04_M_CSV",
     "Reference/2018-2019 ESS Documentation",
     "2018_ESS_W4", ""),

    # Malawi.  IHS-II has no reference folder.
    ("Malawi",
     "Data/MWI_2004_IHS-II_v01_M_Stata8",
     "",
     "2004_IHS2", "no_reference_folder_available"),
    ("Malawi",
     "Data/MWI_2010_IHS-III_v01_M_CSV",
     "Reference/Third Integrated Household Survey 2010-2011",
     "2010_IHS3", ""),
    ("Malawi",
     "Data/MWI_2010-2013_IHPS_v01_M_Stata",
     "Reference/Integrated Household Panel Survey 2010-2013 (Short-Term Panel, 204 EAs)",
     "2010_IHPS", ""),
    ("Malawi",
     "Data/MWI_2016_IHS-IV_v04_M_CSV",
     "Reference/Fourth Integrated Household Survey 2016-2017",
     "2016_IHS4", ""),

    # Mali.  Trailing space in 2014 refs folder is real.
    ("Mali",
     "Data/MLI_2014_EACI_v03_M_CSV",
     "References/first and second visit questionnaires for the EAC-I 2014 ",
     "2014_EACI", ""),
    ("Mali",
     "Data/MLI_2017_EAC-I_v03_M_CSV",
     "References/first and second visit questionnaires for the EAC-I 2017",
     "2017_EACI", ""),

    # Niger
    ("Niger",
     "Data/NER_2011_ECVMA_v01_M_Stata8",
     "References/National Survey on Household Living Conditions and Agriculture 2011",
     "2011_ECVMA_W1", ""),
    ("Niger",
     "Data/NER_2014_ECVMA-II_v02_M_CSV",
     "References/National Survey on Household Living Conditions and Agriculture 2014, Wave 2 Panel Data",
     "2014_ECVMA_W2", ""),

    # Nigeria.  W2 refs folder contains a .crdownload (partial download) — flagged.
    ("Nigeria",
     "Data/NGA_2010_GHSP-W1_v03_M_CSV",
     "References/General Household SurveyPanel 2010-2011Wave 1",
     "2010_GHSP_W1", ""),
    ("Nigeria",
     "Data/NGA_2012_GHSP-W2_v02_M_CSV",
     "References/General Household SurveyPanel 2012-2013",
     "2012_GHSP_W2", "refs_contains_partial_crdownload_file"),
    ("Nigeria",
     "Data/NGA_2015_GHSP-W3_v02_M_CSV",
     "References/General Household Survey Panel 2015-2016 Wave 3",
     "2015_GHSP_W3", ""),
    ("Nigeria",
     "Data/NGA_2018_GHSP-W4_v03_M_CSV",
     "References/General Household Survey, Panel 2018-2019",
     "2018_GHSP_W4", ""),

    # Tanzania
    ("Tanzania",
     "Data/TZA_2008_NPS1_v02_M_STATA_English_labels",
     "References/National Panel Survey 2008-2009, Wave 1",
     "2008_NPS_W1", ""),
    ("Tanzania",
     "Data/TZA_2010_NPS-R2_v03_M_STATA8",
     "References/National Panel Survey 2010-2011, Wave 2",
     "2010_NPS_W2", ""),
    ("Tanzania",
     "Data/TZA_2012_NPS-R3_v01_M_CSV",
     "References/National Panel Survey 2012-2013, Wave 3",
     "2012_NPS_W3", ""),
    ("Tanzania",
     "Data/TZA_2014_NPS-R4_v03_M_CSV",
     "References/National Panel Survey 2014-2015, Wave 4",
     "2014_NPS_W4", ""),
    ("Tanzania",
     "Data/TZA_2019_NPD-SDD_v06_M_CSV",
     "References/National Panel Survey 2019-2020 - Extended Panel with Sex Disaggregated Data",
     "2019_NPS_SDD", "extended_panel_sex_disaggregated"),
    ("Tanzania",
     "Data/TZA_2020_NPS-R5_v02_M_CSV",
     "References/National Panel Survey 2020-21, Wave 5",
     "2020_NPS_W5", ""),

    # Uganda — data side is a .zip file at this stage, not an extracted folder.
    # Unzip happens in a follow-up step; the script just moves the zip into <round>/data.zip.
    ("Uganda",
     "Data/UGA_2005-2009_UNPS_v03_M_CSV.zip",
     "References/National Panel Survey 2005-2009",
     "2005_UNPS_W1", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2010_UNPS_v03_M_CSV.zip",
     "References/National Panel Survey 2010-2011",
     "2010_UNPS_W2", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2011_UNPS_v02_M_CSV.zip",
     "References/National Panel Survey 2011-2012",
     "2011_UNPS_W3", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2013_UNPS_v02_M_CSV.zip",
     "References/National Panel Survey 2013-2014",
     "2013_UNPS_W4", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2015_UNPS_v02_M_CSV.zip",
     "References/National Panel Survey 2015-2016",
     "2015_UNPS_W5", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2018_UNPS_v02_M_CSV.zip",
     "References/Uganda National Panel Survey 2018-2019",
     "2018_UNPS_W6", "data_is_zip_pending_extraction"),
    ("Uganda",
     "Data/UGA_2019_UNPS_v03_M_CSV.zip",
     "References/National Panel Survey 2019-2020",
     "2019_UNPS_W7", "data_is_zip_pending_extraction"),
]

# Loose files that should be filed under a specific round's refs folder.
LOOSE_FILES: list[tuple[str, str, str]] = [
    # Malawi geovariables PDF labelled "y3" -> matches IHS-III (Third IHS).
    ("Malawi",
     "Reference/ihs.geovariables.description.y3.pdf",
     "2010_IHS3"),
]


def remove_ds_store(root: Path) -> int:
    count = 0
    for p in root.rglob(".DS_Store"):
        try:
            p.unlink()
            count += 1
        except OSError:
            pass
    return count


def quote_yaml(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_manifest(manifest: list[dict], manifest_path: Path) -> None:
    lines: list[str] = []
    lines.append(f"# Generated by reorganize.py at {datetime.now().isoformat(timespec='seconds')}")
    lines.append("# Maps original (pre-reorganization) paths to new paths.")
    lines.append("# Paths are relative to 'Country Data/'.")
    lines.append("entries:")
    for e in manifest:
        lines.append(f"  - country: {quote_yaml(e['country'])}")
        lines.append(f"    round_key: {quote_yaml(e['round_key'])}")
        lines.append(f"    data:")
        lines.append(f"      from: {quote_yaml(e['data_from'])}")
        lines.append(f"      to:   {quote_yaml(e['data_to'])}")
        lines.append(f"    refs:")
        lines.append(f"      from: {quote_yaml(e['refs_from'])}")
        lines.append(f"      to:   {quote_yaml(e['refs_to'])}")
        if e.get("notes"):
            lines.append(f"    notes: {quote_yaml(e['notes'])}")
    manifest_path.write_text("\n".join(lines) + "\n")


def move(src: Path, dst: Path) -> None:
    if dst.exists():
        raise RuntimeError(f"refuse to overwrite existing path: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def main() -> int:
    if not ROOT.is_dir():
        print(f"ERROR: {ROOT} does not exist", file=sys.stderr)
        return 1

    manifest: list[dict] = []
    moved = skipped = errors = 0

    for country, data_sub, refs_sub, round_key, notes in MAPPING:
        country_dir = ROOT / country
        round_dir = country_dir / round_key

        data_src = country_dir / data_sub
        refs_src = country_dir / refs_sub if refs_sub else None

        # Data side
        if data_src.suffix == ".zip":
            data_dst = round_dir / data_src.name  # keep zip filename, e.g. UGA_2005-2009_UNPS_v03_M_CSV.zip
        else:
            data_dst = round_dir / "data"

        # Refs side
        refs_dst = round_dir / "refs" if refs_src is not None else None

        # Move data
        if data_src.exists():
            try:
                move(data_src, data_dst)
                moved += 1
            except Exception as e:
                print(f"ERROR moving {data_src} -> {data_dst}: {e}", file=sys.stderr)
                errors += 1
                continue
        elif data_dst.exists():
            skipped += 1
        else:
            print(f"WARN: data source missing and destination missing: {data_src}", file=sys.stderr)
            errors += 1

        # Move refs
        if refs_src is not None:
            if refs_src.exists():
                try:
                    move(refs_src, refs_dst)
                    moved += 1
                except Exception as e:
                    print(f"ERROR moving {refs_src} -> {refs_dst}: {e}", file=sys.stderr)
                    errors += 1
            elif refs_dst.exists():
                skipped += 1
            else:
                print(f"WARN: refs source missing and destination missing: {refs_src}", file=sys.stderr)
                errors += 1
        else:
            (round_dir / "refs").mkdir(parents=True, exist_ok=True)

        manifest.append({
            "country": country,
            "round_key": round_key,
            "data_from": str(Path(country) / data_sub),
            "data_to": str(data_dst.relative_to(ROOT)),
            "refs_from": str(Path(country) / refs_sub) if refs_sub else "",
            "refs_to": str(refs_dst.relative_to(ROOT)) if refs_dst else "",
            "notes": notes,
        })

    # Loose files
    for country, loose_sub, target_round in LOOSE_FILES:
        src = ROOT / country / loose_sub
        dst = ROOT / country / target_round / "refs" / src.name
        if src.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                moved += 1
                manifest.append({
                    "country": country,
                    "round_key": target_round,
                    "data_from": "",
                    "data_to": "",
                    "refs_from": str(Path(country) / loose_sub),
                    "refs_to": str(dst.relative_to(ROOT)),
                    "notes": "loose_file_filed_into_round_refs",
                })
            except Exception as e:
                print(f"ERROR moving loose {src} -> {dst}: {e}", file=sys.stderr)
                errors += 1
        elif dst.exists():
            skipped += 1

    # .DS_Store cleanup must happen *before* rmdir-ing legacy parent dirs.
    ds = remove_ds_store(ROOT)

    # Clean up now-empty Data / Reference(s) parent dirs
    for country_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        for legacy in ("Data", "Reference", "References"):
            d = country_dir / legacy
            if d.is_dir():
                try:
                    d.rmdir()  # only succeeds if empty
                except OSError:
                    pass
    write_manifest(manifest, ROOT / "_manifest.yaml")

    print(f"\nmoved:   {moved}")
    print(f"skipped: {skipped} (already in place)")
    print(f"errors:  {errors}")
    print(f".DS_Store removed: {ds}")
    print(f"manifest: {ROOT / '_manifest.yaml'}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
