# Raw profile of the 53 sheets that touch Yamagata (whole sheets, before any cutting)

Source: G空間情報センター dataset `mesh_10` (全国森林資源メッシュ, zone X), sheets chosen by intersecting the sheet index with the Yamagata boundary (KSJ N03). Run 2026-10-29; sha256 of each archive is in data/raw/20261029/MANIFEST.json (kept in the Hugging Face repo).

These counts cover the whole sheets, so they include cells of neighbouring prefectures and of the sea. The Yamagata-only figures are in docs/yamagata_profile.md.

- sheets: 53; rows: 30,267,408; layers: 53 geometry layers, one per file, named like the file; geometry type ids: {6: 30267408} (6 = MultiPolygon); invalid geometries: 0
- CRS: EPSG:6678; plane bbox x -113460 to 0, y -251320 to -86300
- column sets: 1 distinct (林種, 森林簿樹種1, 森林簿樹種2, 森林簿樹種3, 林齢, 森林簿年月日, 樹冠高, レーザ解析樹種, 立木密度, 平均標高, 計測年月日, plus the GeoPackage fid)

| column | NULL rows | share of rows |
| --- | ---: | ---: |
| 林種 | 6,841,567 | 22.6% |
| 森林簿樹種1 | 6,841,544 | 22.6% |
| 森林簿樹種2 | 20,720,473 | 68.5% |
| 森林簿樹種3 | 26,113,376 | 86.3% |
| 林齢 | 6,841,567 | 22.6% |
| 森林簿年月日 | 6,841,046 | 22.6% |
| 樹冠高 | 28,805,948 | 95.2% |
| レーザ解析樹種 | 27,685,302 | 91.5% |
| 立木密度 | 29,137,365 | 96.3% |
| 平均標高 | 27,883,781 | 92.1% |
| 計測年月日 | 27,674,089 | 91.4% |

## Unique values of the text columns (all 53 sheets)

### 林種

| value | rows |
| --- | ---: |
| 天然林 | 14,823,635 |
| 人工林 | 7,273,643 |
| <NULL> | 6,841,567 |
| その他 | 757,454 |
| 未立木地 | 457,303 |
| 伐採跡地 | 105,393 |
| 竹林 | 8,413 |

### 森林簿樹種1

| value | rows |
| --- | ---: |
| 広葉樹 | 14,587,037 |
| <NULL> | 6,841,544 |
| スギ | 6,110,754 |
| その他 | 1,067,048 |
| マツ類 | 838,012 |
| カラマツ | 532,132 |
| その他針葉樹 | 134,333 |
| 伐採跡地 | 98,156 |
| ヒノキ類 | 26,346 |
| ヒバ | 12,017 |
| #N/A | 11,616 |
| タケ | 8,413 |

### 森林簿樹種2

| value | rows |
| --- | ---: |
| <NULL> | 20,720,473 |
| 広葉樹 | 8,201,467 |
| マツ類 | 634,264 |
| スギ | 370,240 |
| カラマツ | 214,507 |
| ヒバ | 54,506 |
| その他針葉樹 | 54,031 |
| ヒノキ類 | 13,043 |
| その他 | 4,045 |
| 伐採跡地 | 719 |
| タケ | 113 |

### 森林簿樹種3

| value | rows |
| --- | ---: |
| <NULL> | 26,113,376 |
| 広葉樹 | 2,280,355 |
| マツ類 | 1,197,867 |
| ヒバ | 236,829 |
| スギ | 197,614 |
| その他針葉樹 | 191,314 |
| カラマツ | 35,130 |
| ヒノキ類 | 14,537 |
| その他 | 347 |
| タケ | 39 |

### レーザ解析樹種

| value | rows |
| --- | ---: |
| <NULL> | 27,685,302 |
| その他L | 1,352,455 |
| スギ | 872,901 |
| その他 | 236,673 |
| マツ類 | 86,110 |
| カラマツ | 15,493 |
| タケ | 9,562 |
| 伐採跡地 | 8,268 |
| ヒノキ類 | 625 |
| その他N | 19 |

### 森林簿年月日

| value | rows |
| --- | ---: |
| 2024/4/1 | 8,388,383 |
| <NULL> | 6,841,046 |
| 2020/4/1 | 5,162,598 |
| 2023/4/1 | 2,345,881 |
| 2022/4/1 | 1,950,211 |
| 2023/3/31 | 1,905,719 |
| 2021/4/1 | 1,563,193 |
| 2019/4/1 | 1,168,696 |
| 2024/3/31 | 941,681 |

## Other findings

- 計測年月日 values other than NULL: {"2019-01-01": 10438, "2022-01-01": 122666, "2022-08-22": 1009824, "2022-09-11": 1449616, "2023-01-01": 775}
- The literal text `#N/A` as a value: 森林簿樹種1 11,616 rows, 森林簿樹種2 0 rows; kept as in the source.
- 林齢 is 0 in 1,116,677 rows besides the NULLs (6,841,567); whether 0 means an age of zero or an unknown age is not stated in the definition.
- 森林簿年月日 holds 8 dates, as text: 2019/4/1, 2020/4/1, 2021/4/1, 2022/4/1, 2023/3/31, 2023/4/1, 2024/3/31, 2024/4/1.
- No column separates 国有林 from 民有林 in the mesh; that attribute (民国別) is in the 森林計画対象森林レイヤ of Yamagata (downloaded as well).
