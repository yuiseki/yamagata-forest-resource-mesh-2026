#!/usr/bin/env python3
"""Write data/README.md (the dataset card), data/LICENSE and data/provenance.yaml from the measured docs.
Every number and every statement about the content comes from docs/<slug>_profile.json and the other
measured docs; nothing is carried over from another prefecture.

uv run python scripts/05_card.py
"""

import json
from email.utils import parsedate_to_datetime
from pathlib import Path

import rfm

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"
P = rfm.PREF
MESH_PAGE = rfm.PAGE + P.mesh_id
LAYER_PAGE = rfm.PAGE + rfm.LAYER_ID


def size_category(n: int) -> str:
    for hi, label in (
        (1_000_000, "100K<n<1M"),
        (10_000_000, "1M<n<10M"),
        (100_000_000, "10M<n<100M"),
    ):
        if n < hi:
            return label
    return "100M<n<1B"


def date_range(values: dict) -> tuple[str, str]:
    def key(s):
        y, m, d = (int(x) for x in s.split("/"))
        return (y, m, d)

    vs = sorted((v for v in values if v != "<NULL>" and v.count("/") == 2), key=key)
    return vs[0], vs[-1]


def own_share(prof: dict, own: str, col: str) -> str:
    r = next((r for r in prof["by_ownership"] if r["group"] == own), None)
    return "n/a" if r is None else rfm.pct(r[col], r["cells"])


def main() -> None:
    run = sorted((DATA / "raw").glob("*/MANIFEST.json"))[-1].parent
    man = json.loads((run / "MANIFEST.json").read_text())
    mesh = json.loads((run / f"ckan_{P.mesh_id}.json").read_text())
    prof = json.loads((ROOT / "docs" / f"{P.profile_stem}.json").read_text())
    raw = json.loads((ROOT / "docs" / "raw_profile.json").read_text())
    log = json.loads((ROOT / "docs" / "extract_log.json").read_text())
    date = f"{run.name[:4]}-{run.name[4:6]}-{run.name[6:]}"
    n = prof["rows"]
    sheets = log["sheets"]
    n_files = sum(1 for v in sheets.values() if v["kept"])
    n_sheets = len(man["sheets"])
    no_layer = sum(v.get("no_layer_polygon", 0) for v in sheets.values())
    multi = sum(v.get("cells_in_several_layer_polygons", 0) for v in sheets.values())
    nn = prof["non_null"]
    na = prof["unique_values"]
    d0, d1 = date_range(prof["unique_values"]["森林簿年月日"])
    archives = {k: v for k, v in man["files"].items() if k.startswith("fr_mesh20m_")}
    fetched = [k for k, v in archives.items() if "reused_from" not in v]
    reused_runs = sorted(
        {Path(v["reused_from"]).name for v in archives.values() if "reused_from" in v}
    )
    lms = sorted(
        {
            parsedate_to_datetime(v["http"]["last-modified"])
            for v in archives.values()
            if "http" in v
        }
    )
    lm_text = (
        f"between {lms[0]:%Y-%m-%d %H:%M} and {lms[-1]:%Y-%m-%d %H:%M} UTC"
        if lms
        else "see the manifest"
    )
    retrieval = f"{len(fetched)} of the {len(archives)} sheet archives were fetched on {date}"
    if reused_runs:
        retrieval += (f"; the other {len(archives) - len(fetched)} are byte-identical copies of archives that an earlier "
                      f"run of this series fetched on {', '.join(reused_runs)} (same size, same record date, sha256 checked "
                      "against that run's manifest; `reused_from` in the manifest)")  # fmt: skip
    gaps = prof["register_gaps"]["groups"]
    gap_text = (
        "; ".join(f"{g['group']}: {rfm.pct(g['林種'], g['cells'])} of {g['cells']:,} cells" for g in gaps[:8])
        if gaps else "no municipality and ownership group of 1,000 cells or more falls under 90%"
    )  # fmt: skip
    classes = ", ".join(prof["tree_classes"])
    attribution = (
        f"出典：林野庁（{MESH_PAGE}、{LAYER_PAGE}）、PDL1.0（{rfm.PDL_URL}）をもとに yuiseki が作成。"
        f"林野庁の「全国森林資源メッシュ」と「森林計画対象森林レイヤ」から{P.ja}の部分を切り出し、"
        "GeoParquet に変換し、市町村と民有林・国有林の列を加えた加工物であり、林野庁が作成した未加工のデータではない。"
        f"（取得日 {date}）"
    )
    card = f"""---
license: other
license_name: pdl-1.0
license_link: {rfm.PDL_URL}
language:
- ja
tags:
- forest
- japan
- {P.slug}
- geospatial
- geoparquet
size_categories:
- {size_category(n)}
configs:
- config_name: default
  data_files: parquet/*.parquet
---

# 全国森林資源メッシュ {P.ja} ({P.repo})

林野庁の「全国森林資源メッシュ」(20 m メッシュ)のうち、{P.ja}の部分を切り出して固定した GeoParquet です。
分析やモデルは含みません。原データの属性は名前も値も変えていません。

{"An" if P.en[0] in "AEIOU" else "A"} {P.en} Prefecture extract of 全国森林資源メッシュ (Forestry Agency, MAFF; 20 m cells), frozen as GeoParquet, one file per
source sheet. The 11 source attributes keep their names and values.

## Read this first: what the {P.en} data can and cannot say

- Values of the tree columns (森林簿樹種1, 森林簿樹種2, 森林簿樹種3, レーザ解析樹種): {classes}. {rfm.beech_oak_statement(prof["any_value_with_search_word"])}
- {rfm.laser_statement(nn, n, P.en)}
- {n:,} cells cover all of the land of {P.en}; only {rfm.pct(nn["林種"], n)} of them carry a forest register value
  (林種 non-NULL in {nn["林種"]:,} cells). The others are outside the forest register (non-forest land, water,
  or forest without register data).
- 林種 non-NULL by ownership (from the layer): 民有林 {own_share(prof, "民有林", "林種")}, 国有林 {own_share(prof, "国有林", "林種")}.
- Gaps of the register (groups of 1,000 cells or more with under 90% of cells carrying a 林種): {gap_text}. All municipalities are in `docs/{P.profile_stem}.md`.

## Source and licence

- Source: 全国森林資源メッシュ, 林野庁 森林整備部 計画課, Plane Rectangular CS {P.zone} zone ({P.members}), the
  record `{P.mesh_id}` on G空間情報センター ({MESH_PAGE}); the {n_sheets} sheets (国土基本図図郭 quarter sheets, file names
  `fr_mesh20m_<sheet>_2025`) that touch {P.en}. The ownership and municipality columns come from the 森林計画対象森林レイヤ
  of {P.en}, `{P.layer_file.removesuffix(".7z")}` ({LAYER_PAGE}), by the same agency.
- Retrieved: {retrieval}. The records have no version field (created {mesh["metadata_created"][:10]}, metadata modified {mesh["metadata_modified"][:10]});
  the archives were last modified {lm_text} on the server. Each original is dated by its own 森林簿年月日 ({d0} to {d1}).
  sha256 of every archive is in `raw/{run.name}/MANIFEST.json`.
- Licence: 公共データ利用規約 第1.0版 (PDL1.0), stated on the record together with the Forestry Agency's 重要情報 and the
  全国森林資源メッシュの利用規約 (the CKAN licence field says 政府標準利用規約, the earlier terms; both are CC BY compatible).
  The statement was read on the record `{P.mesh_id}` itself, not taken over from another record.
  Conditions: cite the source; say that the data were edited and by whom; do not present the result as made by the
  Forestry Agency; matching with a personal-information database falls under the personal information protection law.
- The 利用規約 of the data adds these cautions: the register-derived information is made mainly by interpreting aerial
  photographs at 1/5,000 and may carry errors from the originating offices; laser-derived information has no guaranteed
  accuracy; the data are not equal to the field, to land registers or to tax records and prove no ownership, boundary,
  area or value of standing timber; they show the state at the time of each original (see 森林簿年月日), not today;
  the Forestry Agency and the originating offices take no responsibility for any use, including use of processed data.
- Attribution to use: {attribution}
- Cutter: the polygons of {P.ja} in 国土数値情報 行政区域 (N03, 2026-01-01; MLIT), used only to choose cells and not republished.

## Files

| path | content |
| --- | --- |
| `parquet/<sheet>.parquet` | {n_files} files, one per source sheet that has cells inside {P.en}; GeoParquet, EPSG:{P.crs}, zstd; {n:,} cells in all |
| `docs/{P.profile_stem}.md`, `docs/{P.profile_stem}.json` | unique values, NULL and non-NULL rates by column, municipality and ownership |
| `docs/raw_profile.md`, `docs/raw_profile.json` | the same for the {raw["sheets"]} whole sheets before the cut |
| `docs/extract_log.json`, `docs/verify_local.json` | counts of the cut and the check against the source |
| `raw/{run.name}/MANIFEST.json`, `raw/{run.name}/ckan_*.json` | source archives with sha256 and HTTP headers; the records |

Read it with `read_parquet('hf://datasets/{P.hub_repo}/parquet/*.parquet')`.

## Columns and their correspondence to the source

| column here | source | note |
| --- | --- | --- |
| `林種` | 林種 | values in this prefecture: {", ".join(k for k in prof["unique_values"]["林種"] if k != "<NULL>")} |
| `森林簿樹種1`, `森林簿樹種2`, `森林簿樹種3` | same | first, second, third tree class by area share in the register. The real column names use the digits 1, 2, 3; the data definition writes １, ２, ３ |
| `林齢` | 林齢 | integer, age of tree class 1 |
| `森林簿年月日` | 森林簿年月日 | text such as {d1} |
| `樹冠高`, `レーザ解析樹種`, `立木密度`, `平均標高`, `計測年月日` | same | non-NULL cells: {", ".join(f"{c} {nn[c]:,}" for c in rfm.LASER)} |
| `geometry` | geom | MultiPolygon of one 20 m cell, EPSG:{P.crs} (JGD2011 / Plane Rectangular CS {P.zone}), unchanged |
| `sheet` | added | the source sheet name, such as {sorted(k for k, v in sheets.items() if v["kept"])[0]} |
| `source_fid` | added | the GeoPackage fid inside that sheet's file |
| `cell_x`, `cell_y` | added | lower-left corner of the cell in EPSG:{P.crs} (metres) |
| `layer_ownership` | added from the layer's 民国別 | 民有林 or 国有林 of the 森林計画対象森林レイヤ polygon that contains the cell centre |
| `layer_municipality_code5`, `layer_municipality_name` | added from the layer's 市町村コード5桁, 市町村名称 | same polygon; NULL when the centre lies in no layer polygon |

## How {P.en} was cut

1. The rule: a cell belongs to {P.en} when its centre lies inside (or on the boundary of) one of the {log["cutter"].split(",")[1].strip()} of {P.ja} in the N03 file;
   the polygons are looked up one by one in an STRtree, not dissolved. Cells are not cut; a cell
   on the prefecture boundary goes to the side of its centre. Cells of other prefectures and of the sea in the border
   sheets are dropped.
2. {n:,} cells of {raw["rows"]:,} cells in the {raw["sheets"]} sheets are kept (all of the land of {P.en}: they cover {prof["cells_km2"]:,.1f} km2
   against {prof["n03_area_km2"]:,.1f} km2 for the N03 polygons). Every kept cell is kept, including the ones with NULL attributes.
3. Layer columns: the cell centre is moved to EPSG:6668 and tested against the layer polygons; {no_layer:,} cells lie in no
   polygon (NULL); if a centre lies in several polygons the first one is taken ({multi:,} such cells).

## Cautions

- {n - prof["distinct_cells"]:,} cell positions occur twice in the source; they are kept.
- The text `#N/A` as a value: 森林簿樹種1 {na["森林簿樹種1"].get("#N/A", 0):,} cells, 森林簿樹種2 {na["森林簿樹種2"].get("#N/A", 0):,} cells, 森林簿樹種3 {na["森林簿樹種3"].get("#N/A", 0):,} cells; kept as in the source.
- 林齢 is 0 in {prof["age_zero_and_null"]["age0"]:,} cells (whether 0 means a real age of zero or an unknown age is not stated) and exceeds 200 in
  {prof["age_gt200"]:,} cells, up to {prof["age_stats_non_null_non_zero"][1]:.0f}; kept as published.
- {prof["register_without_layer_polygon"]:,} cells have a register value although their centre lies in no layer polygon, so the mesh and the layer do not
  coincide at their edges.
- 森林簿樹種2 is present in {rfm.pct(nn["森林簿樹種2"], n)} of the cells and 森林簿樹種3 in {rfm.pct(nn["森林簿樹種3"], n)}; 森林簿樹種2 in {own_share(prof, "国有林", "森林簿樹種2")} of 国有林 cells and {own_share(prof, "民有林", "森林簿樹種2")} of 民有林 cells.
- The cells and attributes are as of each original's date; this is the copy retrieved on {date}.

## Verification

`scripts/06_verify.py` reads each raw sheet again with a second engine (DuckDB spatial) and checks, sheet by sheet, that
the same cells are chosen, that the 11 attributes, the geometry (byte-equal WKB) and the cell corner are equal, and that
the three layer columns agree with a point-in-polygon test done again (`docs/verify_local.json`). After the upload,
`scripts/07_verify_hub.py` reads this repository back at a fixed revision and compares checksums, row counts, schema,
CRS, extent, geometry validity, value counts and NULL counts. The revision is recorded in `docs/revision.md` of the GitHub
repository ({P.github}).

Reproduce: `uv run python scripts/01_download.py`, then `02` to `07` in order.
"""
    (DATA / "README.md").write_text(card, encoding="utf-8")
    (DATA / "LICENSE").write_text(
        "公共データ利用規約（第1.0版）PDL1.0 (" + rfm.PDL_URL + ")\n\n"
        "The data are 全国森林資源メッシュ and 森林計画対象森林レイヤ of the Forestry Agency (MAFF), published under PDL1.0,\n"
        "which is compatible with CC BY 4.0, together with the 全国森林資源メッシュの利用規約. They were processed as described in README.md.\n\n"
        + attribution
        + "\n",
        encoding="utf-8",
    )
    (DATA / "provenance.yaml").write_text(
        f"source: 全国森林資源メッシュ (林野庁)\nurl: {MESH_PAGE}\nlayer_url: {LAYER_PAGE}\nlicense: PDL1.0\nretrieved: {date}\n"
        f"record_metadata_modified: {mesh['metadata_modified']}\narchives: {n_sheets} sheets, sha256 in raw/{run.name}/MANIFEST.json\n"
        f"cutter: {P.n03_url}\nrows: {n}\n",
        encoding="utf-8",
    )
    print("wrote card, LICENSE, provenance.yaml")


if __name__ == "__main__":
    main()
