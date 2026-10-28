#!/usr/bin/env python3
"""Profile the cells of this prefecture: unique values and counts of every tree column, NULL and non-NULL
rates, by municipality and by 国有林/民有林, the cell-key uniqueness, and the gaps of the forest register.
Every number that the card quotes is computed here from the data.

    uv run python scripts/04_profile.py   # writes docs/<slug>_profile.json and docs/<slug>_profile.md
"""

import json
import sys
import zipfile
from pathlib import Path

import duckdb
import geopandas as gpd
import rfm

ROOT = Path(__file__).parents[1]
P = rfm.PREF
GLOB = str(ROOT / "data" / "parquet" / "sheet=*" / "part.parquet")
TREE = rfm.TREE
OTHER = ["林齢", "森林簿年月日", "樹冠高", "立木密度", "平均標高", "計測年月日"]
NN_COLS = TREE + ["林齢", "森林簿年月日", "樹冠高", "レーザ解析樹種", "立木密度", "平均標高"]
SHOW = ["林種", "森林簿樹種1", "森林簿樹種2", "森林簿樹種3", "林齢", "森林簿年月日"]


def n03_area_km2() -> float:
    z = ROOT / "data" / "docs" / P.n03_name
    shp = next(n for n in zipfile.ZipFile(z).namelist() if n.endswith(".shp"))
    g = gpd.read_file(f"zip://{z}!{shp}").to_crs(P.crs)
    return float(g.geometry.union_all().area / 1e6)


def main() -> int:
    con = duckdb.connect()
    con.execute(f"create view m as select * from read_parquet('{GLOB}')")
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    res = {"prefecture": P.ja, "crs": P.crs}
    res["rows"] = n = q("select count(*) from m")[0][0]
    res["distinct_cells"] = q("select count(*) from (select distinct cell_x, cell_y from m)")[0][0]
    res["sheets"] = q("select count(distinct sheet) from m")[0][0]
    res["cell_extent"] = list(
        q("select min(cell_x), min(cell_y), max(cell_x), max(cell_y) from m")[0]
    )
    res["cells_km2"] = n * 400 / 1e6
    res["n03_area_km2"] = n03_area_km2()
    res["non_null"] = {c: q(f'select count("{c}") from m')[0][0] for c in TREE + OTHER}
    uv_cols = TREE + ["森林簿年月日", "計測年月日"]
    res["unique_values"] = {
        c: dict(q(f"select coalesce(cast(\"{c}\" as varchar), '<NULL>') v, count(*) from m group by 1 order by 2 desc, 1"))
        for c in uv_cols
    }  # fmt: skip
    res["age_zero_and_null"] = {
        "age0": q('select count(*) from m where "林齢" = 0')[0][0],
        "age_null": q('select count(*) from m where "林齢" is null')[0][0],
    }
    res["age_stats_non_null_non_zero"] = list(
        q('select min("林齢"), max("林齢"), avg("林齢") from m where "林齢" > 0')[0]
    )
    res["age_gt200"] = q('select count(*) from m where "林齢" > 200')[0][0]
    res["age_gt200_by_林種"] = dict(
        q(
            'select coalesce("林種",\'<NULL>\'), count(*) from m where "林齢" > 200 group by 1 order by 2 desc, 1'
        )
    )
    res["layer_ownership"] = dict(
        q(
            "select coalesce(layer_ownership,'<NULL>'), count(*) from m group by 1 order by 2 desc, 1"
        )
    )
    res["layer_municipality_null"] = q(
        "select count(*) from m where layer_municipality_name is null"
    )[0][0]
    res["register_without_layer_polygon"] = q(
        'select count(*) from m where layer_ownership is null and "林種" is not null'
    )[0][0]
    names = ["group", "cells"] + NN_COLS
    nn = ", ".join(f'count("{c}") as "{c}"' for c in NN_COLS)
    for key, col in (
        ("by_municipality", "layer_municipality_name"),
        ("by_ownership", "layer_ownership"),
    ):
        rows = con.execute(
            f"select coalesce({col}, '<NULL>') g, count(*) n, {nn} from m group by 1 order by n desc, 1"
        ).fetchall()
        res[key] = [dict(zip(names, r, strict=True)) for r in rows]
    rows = con.execute(
        f"select coalesce(layer_municipality_name, '<NULL>') || ' / ' || coalesce(layer_ownership, '<NULL>') g, count(*) n, {nn} "
        "from m group by 1 order by n desc, 1"
    ).fetchall()
    res["by_municipality_ownership"] = [dict(zip(names, r, strict=True)) for r in rows]
    # the gaps of the register: groups of at least 1,000 cells where under 90% of cells carry a 林種
    res["register_gaps"] = {
        "rule": "municipality / ownership groups of at least 1,000 cells where under 90% of the cells have a 林種",
        "groups": rfm.low_coverage(res["by_municipality_ownership"], "林種", 1000, 0.9),
    }
    res["cross_林種_樹種1"] = [list(r) for r in con.execute(
        "select coalesce(\"林種\",'<NULL>'), coalesce(\"森林簿樹種1\",'<NULL>'), count(*) from m group by 1,2 order by 3 desc, 1, 2").fetchall()]  # fmt: skip
    res["ownership_x_樹種1"] = [list(r) for r in con.execute(
        "select coalesce(layer_ownership,'<NULL>'), coalesce(\"森林簿樹種1\",'<NULL>'), count(*) from m group by 1,2 order by 1,3 desc, 2").fetchall()]  # fmt: skip
    res["tree_classes"], res["any_value_with_search_word"] = rfm.tree_classes(res["unique_values"])
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / f"{P.profile_stem}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1) + "\n"
    )

    pct = rfm.pct
    a = res["age_stats_non_null_non_zero"]
    md = [
        f"# {P.en} cells of 全国森林資源メッシュ: profile",
        "",
        f"- cells: {n:,} in {res['sheets']} sheets (centre inside {P.en}); distinct (cell_x, cell_y): {res['distinct_cells']:,}, so {n - res['distinct_cells']} cell positions occur twice",
        f"- cell_x / cell_y extent in EPSG:{P.crs}: x {res['cell_extent'][0]} to {res['cell_extent'][2]}, y {res['cell_extent'][1]} to {res['cell_extent'][3]}; the cells cover {res['cells_km2']:,.1f} km2, against {res['n03_area_km2']:,.1f} km2 for the N03 polygons of {P.en}",
        f"- the cells are all of the land of {P.en}, forest or not; cells outside the forest register carry NULL: 林種 is NULL in {n - res['non_null']['林種']:,} cells",
        "",
        f"## Non-NULL rate of every attribute (all {P.en} cells)",
        "",
        "| column | non-NULL cells | share |",
        "| --- | ---: | ---: |",
    ]
    md += [f"| {c} | {v:,} | {pct(v, n)} |" for c, v in res["non_null"].items()]
    md += ["", rfm.laser_statement(res["non_null"], n, P.en), "", f"## Unique values ({P.en})", ""]
    for c, v in res["unique_values"].items():
        md += (
            [f"### {c}", "", "| value | cells |", "| --- | ---: |"]
            + [f"| {k} | {x:,} |" for k, x in v.items()]
            + [""]
        )
    md += [
        rfm.beech_oak_statement(res["any_value_with_search_word"])
        + f" Values of the tree columns: {', '.join(res['tree_classes'])}.",
        "",
        f"林齢: 0 in {res['age_zero_and_null']['age0']:,} cells and NULL in {res['age_zero_and_null']['age_null']:,}; among the cells above 0 it runs {a[0]:.0f} to {a[1]:.0f} (mean {a[2]:.1f}); {res['age_gt200']:,} cells have an age above 200 (by 林種: {json.dumps(res['age_gt200_by_林種'], ensure_ascii=False)}); all kept as published.",
        "",
        "## Non-NULL by ownership (民国別, taken from the 森林計画対象森林レイヤ by the cell centre)",
        "",
        "| group | cells | " + " | ".join(SHOW) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in SHOW) + " |",
    ]
    md += [
        f"| {r['group']} | {r['cells']:,} | "
        + " | ".join(pct(r[c], r["cells"]) for c in SHOW)
        + " |"
        for r in res["by_ownership"]
    ]
    md += [
        "",
        f"`<NULL>` here means that the cell centre lies in no polygon of the layer (sea, rivers, non-forest land, and the edge of forest areas); {res['register_without_layer_polygon']:,} of those cells still carry a forest register value, so the mesh and the layer do not coincide at their edges.",
        "",
        "## Gaps of the register",
        "",
        f"Rule: {res['register_gaps']['rule']}.",
        "",
    ]
    gaps = res["register_gaps"]["groups"]
    if gaps:
        md += ["| municipality / ownership | cells | 林種 non-NULL |", "| --- | ---: | ---: |"]
        md += [f"| {g['group']} | {g['cells']:,} | {pct(g['林種'], g['cells'])} |" for g in gaps]
    else:
        md += ["No group meets the rule."]
    md += [
        "",
        "## Non-NULL by municipality (the same layer)",
        "",
        "| municipality | cells | " + " | ".join(SHOW) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in SHOW) + " |",
    ]
    md += [
        f"| {r['group']} | {r['cells']:,} | "
        + " | ".join(pct(r[c], r["cells"]) for c in SHOW)
        + " |"
        for r in res["by_municipality"]
    ]
    md += [
        "",
        "## 林種 by 森林簿樹種1 (cells)",
        "",
        "| 林種 | 森林簿樹種1 | cells |",
        "| --- | --- | ---: |",
    ]
    md += [f"| {x} | {y} | {c:,} |" for x, y, c in res["cross_林種_樹種1"]]
    (ROOT / "docs" / f"{P.profile_stem}.md").write_text("\n".join(md) + "\n")
    keys = (
        "rows",
        "distinct_cells",
        "sheets",
        "non_null",
        "layer_ownership",
        "layer_municipality_null",
        "any_value_with_search_word",
        "tree_classes",
    )
    print(json.dumps({k: res[k] for k in keys}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
