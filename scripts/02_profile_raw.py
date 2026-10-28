#!/usr/bin/env python3
"""Profile the raw sheets (whole sheets, before any cutting by prefecture): layer, rows, geometry,
CRS, extent, invalid geometries, columns, NULL counts and the unique values of the text columns.

    uv run python scripts/02_profile_raw.py   # writes docs/raw_profile.json and docs/raw_profile.md
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyogrio
import rfm
import shapely

ROOT = Path(__file__).parents[1]
P = rfm.PREF
TEXT = ["林種", "森林簿樹種1", "森林簿樹種2", "森林簿樹種3", "レーザ解析樹種", "森林簿年月日"]


def write_md(res: dict, run: Path) -> None:
    n = res["rows"]
    b = res["bbox_plane_xy"]
    date = f"{run.name[:4]}-{run.name[4:6]}-{run.name[6:]}"
    md = [
        f"# Raw profile of the {res['sheets']} sheets that touch {P.en} (whole sheets, before any cutting)",
        "",
        f"Source: G空間情報センター dataset `{P.mesh_id}` (全国森林資源メッシュ, zone {P.zone}), sheets chosen by intersecting the sheet index with the {P.en} boundary (KSJ N03). Run {date}; sha256 of each archive is in data/raw/{run.name}/MANIFEST.json (kept in the Hugging Face repo).",
        "",
        f"These counts cover the whole sheets, so they include cells of neighbouring prefectures and of the sea. The {P.en}-only figures are in docs/{P.profile_stem}.md.",
        "",
        f"- sheets: {res['sheets']}; rows: {n:,}; layers: {len(res['layers'])} geometry layers, one per file, named like the file; geometry type ids: {res['geometry_type_ids']} (6 = MultiPolygon); invalid geometries: {res['invalid_geometry']}",
        f"- CRS: {'; '.join(res['crs'])}; plane bbox x {b[0]:.0f} to {b[2]:.0f}, y {b[1]:.0f} to {b[3]:.0f}",
        f"- column sets: {len(res['field_sets'])} distinct ({', '.join(res['field_sets'][0])}, plus the GeoPackage fid)",
        "",
        "| column | NULL rows | share of rows |",
        "| --- | ---: | ---: |",
    ]
    md += [f"| {c} | {v:,} | {rfm.pct(v, n)} |" for c, v in res["nulls"].items()]
    md += ["", f"## Unique values of the text columns (all {res['sheets']} sheets)", ""]
    for c, v in res["value_counts"].items():
        md += (
            [f"### {c}", "", "| value | rows |", "| --- | ---: |"]
            + [f"| {k} | {x:,} |" for k, x in v.items()]
            + [""]
        )
    na1, na2 = (res["value_counts"][c].get("#N/A", 0) for c in ("森林簿樹種1", "森林簿樹種2"))
    meas = {
        k: v
        for k, v in res["measure_date_counts"].items()
        if k not in ("None", "NaT", "nan", "<NULL>")
    }
    dates = [k for k in res["value_counts"]["森林簿年月日"] if k != "<NULL>"]
    md += [
        "## Other findings",
        "",
        f"- 計測年月日 values other than NULL: {json.dumps(meas, ensure_ascii=False)}",
        f"- The literal text `#N/A` as a value: 森林簿樹種1 {na1:,} rows, 森林簿樹種2 {na2:,} rows; kept as in the source.",
        f"- 林齢 is 0 in {res['age_counts'].get(0, 0):,} rows besides the NULLs ({res['age_counts'].get(-1, 0):,}); whether 0 means an age of zero or an unknown age is not stated in the definition.",
        f"- 森林簿年月日 holds {len(dates)} dates, as text: {', '.join(sorted(dates))}.",
        f"- No column separates 国有林 from 民有林 in the mesh; that attribute (民国別) is in the 森林計画対象森林レイヤ of {P.en} (downloaded as well).",
    ]
    (ROOT / "docs" / "raw_profile.md").write_text("\n".join(md) + "\n")


def main() -> int:
    run = sorted((ROOT / "data" / "raw").glob("*/MANIFEST.json"))[-1].parent
    sheets = sorted((run / "gpkg").glob("fr_mesh20m_*_2025.gpkg"))
    per_sheet, counts = {}, {c: Counter() for c in TEXT}
    nulls, rows, invalid = Counter(), 0, 0
    types, crs_seen, fields_seen, layers_seen = Counter(), set(), set(), set()
    ages, meas = Counter(), Counter()
    bbox = [1e18, 1e18, -1e18, -1e18]
    for p in sheets:
        layer = [str(x[0]) for x in pyogrio.list_layers(p) if x[1] is not None][0]
        layers_seen.add(layer)
        info = pyogrio.read_info(p, layer=layer)
        crs_seen.add(str(info["crs"]))
        fields_seen.add(tuple(info["fields"]))
        df = pyogrio.read_dataframe(p, layer=layer)
        g = df.geometry.values
        n = len(df)
        bad = int((~shapely.is_valid(g)).sum())
        for t, c in zip(*np.unique(shapely.get_type_id(g), return_counts=True), strict=True):
            types[int(t)] += int(c)
        b = df.total_bounds
        bbox = [min(bbox[0], b[0]), min(bbox[1], b[1]), max(bbox[2], b[2]), max(bbox[3], b[3])]
        for c in df.columns.drop("geometry"):
            nulls[c] += int(df[c].isna().sum())
        for c in TEXT:
            counts[c].update(df[c].fillna("<NULL>").tolist())
        ages.update(df["林齢"].fillna(-1).astype(int).tolist())
        meas.update(df["計測年月日"].astype(str).fillna("<NULL>").tolist())
        rows += n
        invalid += bad
        per_sheet[p.name] = {
            "rows": n,
            "invalid": bad,
            "fid_unique": bool(df.index.is_unique),
            "layer": layer,
        }
        print(p.name, n, bad, flush=True)
    res = {"sheets": len(sheets), "rows": rows, "invalid_geometry": invalid, "geometry_type_ids": dict(types),
           "layers": sorted(layers_seen), "crs": sorted(crs_seen), "field_sets": [list(f) for f in fields_seen],
           "bbox_plane_xy": bbox, "nulls": dict(nulls), "per_sheet": per_sheet,
           "value_counts": {c: dict(counts[c].most_common()) for c in TEXT},
           "age_counts": dict(sorted(ages.items())), "measure_date_counts": dict(sorted(meas.items()))}  # fmt: skip
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "raw_profile.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n"
    )
    write_md(res, run)
    print("rows", rows, "invalid", invalid, "nulls", dict(nulls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
