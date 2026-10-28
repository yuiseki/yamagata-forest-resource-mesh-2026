import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pytest
import rfm
from shapely.geometry import box

TOHOKU_EXCEPT_AKITA = {
    "02": "青森県",
    "03": "岩手県",
    "04": "宮城県",
    "06": "山形県",
    "07": "福島県",
}


def test_table_covers_the_prefectures_of_the_series():
    for code, ja in TOHOKU_EXCEPT_AKITA.items():
        assert rfm.PREFS[code].ja == ja
    assert rfm.PREFS["05"].ja == "秋田県"


def test_zone_follows_the_mesh_record():
    # the records say: X zone (10) = EPSG 6678, IX zone (9) = EPSG 6677
    for code in ("02", "03", "04", "05", "06"):
        assert (rfm.PREFS[code].mesh_id, rfm.PREFS[code].crs) == ("mesh_10", 6678)
    assert (rfm.PREFS["07"].mesh_id, rfm.PREFS["07"].crs) == ("mesh_9", 6677)


def test_names_are_derived_from_the_code():
    p = rfm.PREFS["03"]
    assert p.slug == "iwate"
    assert p.repo == "iwate-forest-resource-mesh-2026"
    assert p.hub_repo == "yuiseki/iwate-forest-resource-mesh-2026"
    assert p.n03_name == "N03-20260101_03_GML.zip"
    assert p.n03_url == "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/N03-20260101_03_GML.zip"
    assert p.layer_file == "fr_layer_03_2025.7z"
    assert p.layer_gpkg == "fr_layer_03_2025.gpkg"
    assert p.profile_stem == "iwate_profile"
    assert p.parquet_name("10IC1") == "parquet/10IC1.parquet"


def test_the_current_repo_has_a_valid_pref():
    assert rfm.PREF.code in rfm.PREFS
    assert rfm.PREF is rfm.PREFS[rfm.PREF.code]


def test_sheet_names():
    assert rfm.archive_name("10IC1") == "fr_mesh20m_10IC1_2025.7z"
    assert rfm.sheet_of(Path("x/gpkg/fr_mesh20m_10IC1_2025.gpkg")) == "10IC1"
    assert rfm.sheet_of(Path("fr_mesh20m_09ZEF1_2025.7z")) == "09ZEF1"


def test_choose_sheets_keeps_the_touching_ones_once():
    sheets = gpd.GeoDataFrame(
        {"図郭名": ["A1", "A1", "B2", "C3"]},
        geometry=[box(0, 0, 10, 10), box(0, 0, 10, 10), box(10, 0, 20, 10), box(30, 30, 40, 40)],
        crs=6678,
    )
    cutter = box(5, 5, 15, 8)
    assert rfm.choose_sheets(sheets, cutter) == ["A1", "B2"]


def _manifest(d: Path, name: str, data: bytes, lm="Tue, 01 Jul 2026 00:00:00 GMT") -> None:
    (d / name).write_bytes(data)
    man = {"files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                            "record_last_modified": lm}}}  # fmt: skip
    (d / "MANIFEST.json").write_text(json.dumps(man))


def test_find_reusable_needs_size_checksum_and_record_date(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    _manifest(d, "a.7z", b"abc", lm="L1")
    assert rfm.find_reusable("a.7z", 3, "L1", [d]) == d / "a.7z"
    assert rfm.find_reusable("a.7z", 4, "L1", [d]) is None  # size differs from the record
    assert rfm.find_reusable("a.7z", 3, "L2", [d]) is None  # the record was modified since
    assert rfm.find_reusable("missing.7z", 3, "L1", [d]) is None
    (d / "a.7z").write_bytes(b"abd")  # same size, different bytes: the manifest checksum catches it
    assert rfm.find_reusable("a.7z", 3, "L1", [d]) is None


def test_laser_statement_follows_the_counts():
    all_null = {"レーザ解析樹種": 0, "樹冠高": 0, "立木密度": 0, "平均標高": 0, "計測年月日": 0}
    assert "NULL in every" in rfm.laser_statement(all_null, 100, "Aomori")
    some = dict(all_null, 樹冠高=5, 計測年月日=5)
    s = rfm.laser_statement(some, 100, "Aomori")
    assert "NULL in every" not in s
    assert "樹冠高 5 (5.0%)" in s
    assert "レーザ解析樹種" in s  # still listed as all NULL


def test_tree_class_statement_reports_search_words_only_when_present():
    uv = {
        "森林簿樹種1": {"スギ": 10, "広葉樹": 5, "<NULL>": 1},
        "森林簿樹種2": {"広葉樹": 2},
        "森林簿樹種3": {},
        "レーザ解析樹種": {"<NULL>": 3},
    }
    classes, hits = rfm.tree_classes(uv)
    assert classes == ["スギ", "広葉樹"]
    assert hits == {"ブナ": 0, "ミズナラ": 0, "ナラ": 0, "コナラ": 0}
    uv["レーザ解析樹種"] = {"ブナ": 7, "<NULL>": 1}
    _, hits = rfm.tree_classes(uv)
    assert hits["ブナ"] == 7 and hits["ナラ"] == 0
    assert "cannot be told apart" in rfm.beech_oak_statement(
        {"ブナ": 0, "ミズナラ": 0, "ナラ": 0, "コナラ": 0}
    )
    assert "ブナ 7" in rfm.beech_oak_statement(hits)


def test_low_coverage_lists_big_gaps_only():
    rows = [
        {"group": "A市", "cells": 1000, "林種": 500},
        {"group": "B市", "cells": 1000, "林種": 990},
        {"group": "C町", "cells": 10, "林種": 0},
        {"group": "<NULL>", "cells": 5000, "林種": 0},
    ]
    got = rfm.low_coverage(rows, "林種", min_cells=100, below=0.9)
    assert [g["group"] for g in got] == [
        "A市"
    ]  # B is above, C is too small, <NULL> is not a municipality


def test_pct():
    assert rfm.pct(1, 3) == "33.3%"
    assert rfm.pct(0, 0) == "n/a"


@pytest.mark.parametrize("code", list(TOHOKU_EXCEPT_AKITA))
def test_n03_url_is_for_the_same_code(code):
    assert rfm.PREFS[code].n03_url.endswith(f"_{code}_GML.zip")


def test_layer_name_prefers_the_prefecture_then_the_only_layer(tmp_path):
    g = gpd.GeoDataFrame({"a": [1]}, geometry=[box(0, 0, 1, 1)], crs=6668)
    one = tmp_path / "one.gpkg"
    g.to_file(one, layer="秋田県", driver="GPKG")
    assert rfm.layer_name(one, "秋田県") == "秋田県"
    assert rfm.layer_name(one, "青森県") == "秋田県"  # the only layer
    two = tmp_path / "two.gpkg"
    g.to_file(two, layer="x", driver="GPKG")
    g.to_file(two, layer="y", driver="GPKG")
    assert rfm.layer_name(two, "x") == "x"
    with pytest.raises(SystemExit):
        rfm.layer_name(two, "青森県")


def test_the_repo_directory_matches_its_prefecture():
    root = Path(rfm.__file__).parents[1]
    if root.name.startswith("_template"):
        pytest.skip("the template has no prefecture of its own")
    assert root.name == rfm.PREF.repo
