"""Constants and small helpers shared by the scripts of <prefecture>-forest-resource-mesh-2026.

The table PREFS holds what differs by prefecture; rfm_pref.PREF_CODE chooses the one of this repository.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from rfm_pref import PREF_CODE

CKAN = "https://www.geospatial.jp/ckan/api/3/action/package_show?id="
LAYER_ID = "layer"  # 森林計画対象森林レイヤ: carries 民国別 and 市町村, which the mesh lacks
PAGE = "https://www.geospatial.jp/ckan/dataset/"
PDL_URL = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"
UA = "Mozilla/5.0 (research; yuiseki)"
N03_PAGE_URL = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2026.html"
N03_DIR = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2026/"
N03_VERSION = "20260101"
EDITION = "2025"  # the file names carry the edition: fr_mesh20m_<sheet>_2025, fr_layer_<code>_2025
# the files use ASCII digits in the three tree columns; the data definition writes full-width １２３
MESH_COLUMNS = ["林種", "森林簿樹種1", "森林簿樹種2", "森林簿樹種3", "林齢", "森林簿年月日",
                "樹冠高", "レーザ解析樹種", "立木密度", "平均標高", "計測年月日"]  # fmt: skip
TREE = ["林種", "森林簿樹種1", "森林簿樹種2", "森林簿樹種3", "レーザ解析樹種"]
LASER = ["レーザ解析樹種", "樹冠高", "立木密度", "平均標高", "計測年月日"]
WORDS = ["ブナ", "ミズナラ", "ナラ", "コナラ"]

# the records of the Plane Rectangular zones give the CRS: X (10) is EPSG 6678, IX (9) is EPSG 6677
MESHES = {
    "mesh_10": {"crs": 6678, "zone": "X", "members": "青森・秋田・山形・岩手・宮城"},
    "mesh_9": {
        "crs": 6677,
        "zone": "IX",
        "members": "福島・栃木・茨城・埼玉・千葉・群馬・神奈川・東京の一部",
    },
}


@dataclass(frozen=True)
class Pref:
    code: str
    slug: str
    ja: str
    en: str
    mesh_id: str

    @property
    def crs(self) -> int:
        return MESHES[self.mesh_id]["crs"]

    @property
    def zone(self) -> str:
        return MESHES[self.mesh_id]["zone"]

    @property
    def members(self) -> str:
        return MESHES[self.mesh_id]["members"]

    @property
    def repo(self) -> str:
        return f"{self.slug}-forest-resource-mesh-2026"

    @property
    def hub_repo(self) -> str:
        return f"yuiseki/{self.repo}"

    @property
    def github(self) -> str:
        return f"https://github.com/{self.hub_repo}"

    @property
    def n03_name(self) -> str:
        return f"N03-{N03_VERSION}_{self.code}_GML.zip"

    @property
    def n03_url(self) -> str:
        return N03_DIR + self.n03_name

    @property
    def layer_file(self) -> str:
        return f"fr_layer_{self.code}_{EDITION}.7z"

    @property
    def layer_gpkg(self) -> str:
        return f"fr_layer_{self.code}_{EDITION}.gpkg"

    @property
    def profile_stem(self) -> str:
        return f"{self.slug}_profile"

    def parquet_name(self, sheet: str) -> str:
        return f"parquet/{sheet}.parquet"


PREFS = {
    p.code: p
    for p in (
        Pref("02", "aomori", "青森県", "Aomori", "mesh_10"),
        Pref("03", "iwate", "岩手県", "Iwate", "mesh_10"),
        Pref("04", "miyagi", "宮城県", "Miyagi", "mesh_10"),
        Pref("05", "akita", "秋田県", "Akita", "mesh_10"),
        Pref("06", "yamagata", "山形県", "Yamagata", "mesh_10"),
        Pref("07", "fukushima", "福島県", "Fukushima", "mesh_9"),
    )
}
PREF = PREFS[PREF_CODE]


def archive_name(sheet: str) -> str:
    return f"fr_mesh20m_{sheet}_{EDITION}.7z"


def sheet_of(path: Path) -> str:
    """'fr_mesh20m_10IC1_2025.gpkg' -> '10IC1'."""
    return Path(path).name.split("_")[2]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(1 << 24):
            h.update(chunk)
    return h.hexdigest()


def choose_sheets(index, cutter) -> list[str]:
    """Names of the sheets of the index that touch the cutter; the index repeats some sheets."""
    return sorted(set(index.loc[index.intersects(cutter), "図郭名"]))


def find_reusable(name: str, size: int, record_last_modified, run_dirs) -> Path | None:
    """An archive that an earlier run of the series already fetched: same size as the record says,
    same record date, and the bytes on disk match the sha256 that run wrote in its MANIFEST.json."""
    for d in run_dirs:
        man_path, f = Path(d) / "MANIFEST.json", Path(d) / name
        if not man_path.is_file() or not f.is_file():
            continue
        ent = json.loads(man_path.read_text())["files"].get(name)
        if (
            not ent
            or ent.get("size") != size
            or ent.get("record_last_modified") != record_last_modified
        ):
            continue
        if f.stat().st_size == size and sha256(f) == ent["sha256"]:
            return f
    return None


def pct(a: int, b: int) -> str:
    return "n/a" if not b else f"{100 * a / b:.1f}%"


def laser_statement(non_null: dict, n: int, name: str) -> str:
    cols = ", ".join(LASER)
    if all(non_null[c] == 0 for c in LASER):
        return f"The laser-derived columns ({cols}) are NULL in every {name} cell."
    some = [f"{c} {non_null[c]:,} ({pct(non_null[c], n)})" for c in LASER if non_null[c]]
    none = [c for c in LASER if not non_null[c]]
    s = (
        f"The laser-derived columns ({cols}) are not empty in {name}: non-NULL cells are "
        + ", ".join(some)
        + "."
    )
    return s + (f" All NULL: {', '.join(none)}." if none else "")


def tree_classes(unique_values: dict) -> tuple[list[str], dict]:
    """The values of the tree columns by number of cells, and the cells whose value contains a search word."""
    cols = ["森林簿樹種1", "森林簿樹種2", "森林簿樹種3", "レーザ解析樹種"]
    total: dict[str, int] = {}
    for c in cols:
        for v, k in unique_values.get(c, {}).items():
            if v != "<NULL>":
                total[v] = total.get(v, 0) + k
    classes = [v for v, _ in sorted(total.items(), key=lambda t: (-t[1], t[0]))]
    hits = {w: sum(k for v, k in total.items() if w in v) for w in WORDS}
    return classes, hits


def beech_oak_statement(hits: dict) -> str:
    if not any(hits.values()):
        return ("No value of any tree column contains ブナ, ミズナラ, ナラ or コナラ, so beech and oak "
                "cannot be told apart in these data.")  # fmt: skip
    return ("Values of the tree columns that contain the search words exist (cells: "
            + ", ".join(f"{w} {k:,}" for w, k in hits.items()) + "); see the unique values in the profile.")  # fmt: skip


def low_coverage(rows: list[dict], col: str, min_cells: int, below: float) -> list[dict]:
    """Municipality (or other group) rows whose share of non-NULL `col` is below `below`; NULL group and tiny groups are left out."""
    out = [
        r
        for r in rows
        if r["group"] != "<NULL>" and r["cells"] >= min_cells and r[col] / r["cells"] < below
    ]
    return sorted(out, key=lambda r: r[col] / r["cells"])


def layer_name(gpkg: Path, preferred: str) -> str:
    """The layer of a GeoPackage with geometry: the one named after the prefecture, else the only one."""
    import pyogrio

    names = [str(x[0]) for x in pyogrio.list_layers(gpkg) if x[1] is not None]
    if preferred in names:
        return preferred
    if len(names) == 1:
        return names[0]
    raise SystemExit(f"{gpkg}: cannot choose a layer among {names}")
