"""北谷町の町丁字ポリゴンに国勢調査の指標を載せた GeoJSON を作る。

出力: docs/data/chatan_areas.geojson  … 30区域のポリゴン＋指標
      docs/data/chatan_town.json      … 町全体の集計（サイドパネル用）

指標は 2020年(令和2年) を主、2015年(平成27年) を比較用に持つ。
"""

from __future__ import annotations

import json
from pathlib import Path

import shapefile  # pyshp

import estat
from estat import CITY_CODE, num

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"

# 各表のデータ列（メタ7列を落とした後の 0 始まり位置）
AGE = {"total": 0, "u15": 16, "w15_64": 17, "o65": 18, "o75": 19}
POP = {"total": 0, "male": 1, "female": 2, "households": 3}
HH_SIZE = {"total": 0, "single": 1, "avg_members": 7}
HH_TYPE = {"total": 0, "with_u6": 6, "with_u18": 7, "with_o65": 8}


def ring_area(ring: list[tuple[float, float]]) -> float:
    """符号付き面積。反時計回りが正。Shapefileの外環は時計回り＝負。"""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2.0


def to_geometry(shape) -> dict:
    """pyshp の polygon を GeoJSON Polygon / MultiPolygon にする。

    Shapefileは 外環=時計回り / 穴=反時計回り。GeoJSON(RFC7946)は逆なので向きを揃える。
    """
    pts = [(round(x, 6), round(y, 6)) for x, y in shape.points]
    starts = list(shape.parts) + [len(pts)]
    polygons: list[list[list[tuple[float, float]]]] = []
    for a, b in zip(starts, starts[1:]):
        ring = pts[a:b]
        if len(ring) < 4:
            continue
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if ring_area(ring) < 0:          # 時計回り = 外環
            polygons.append([list(reversed(ring))])
        elif polygons:                    # 反時計回り = 直前の外環の穴
            polygons[-1].append(list(reversed(ring)))
        else:
            polygons.append([ring])
    if not polygons:
        raise ValueError("環が構成できない")
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def pct(part: int | None, whole: int | None) -> float | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100, 1)


def load_stats() -> dict[str, dict[str, dict[str, list[str]]]]:
    return {
        year: {kind: estat.small_area_table(tid, kind) for kind, tid in tables.items()}
        for year, tables in estat.TABLES.items()
    }


def indicators(key: str, stats: dict) -> dict:
    """1区域ぶんの指標。欠測(秘匿・該当なし)は None のまま通す。"""
    def cell(year: str, kind: str, col: int) -> int | None:
        row = stats[year][kind].get(key)
        return num(row[col]) if row else None

    def fnum(year: str, kind: str, col: int) -> float | None:
        row = stats[year][kind].get(key)
        if not row:
            return None
        v = (row[col] or "").strip()
        try:
            return round(float(v), 2)
        except ValueError:
            return None

    pop20 = cell("2020", "pop", POP["total"])
    pop15 = cell("2015", "pop", POP["total"])
    age20_total = cell("2020", "age", AGE["total"])
    o65_20 = cell("2020", "age", AGE["o65"])
    o65_15 = cell("2015", "age", AGE["o65"])
    age15_total = cell("2015", "age", AGE["total"])

    aging20 = pct(o65_20, age20_total)
    aging15 = pct(o65_15, age15_total)

    hh20 = cell("2020", "hh_type", HH_TYPE["total"])

    d = {
        "pop_2020": pop20,
        "pop_2015": pop15,
        "male_2020": cell("2020", "pop", POP["male"]),
        "female_2020": cell("2020", "pop", POP["female"]),
        "households_2020": cell("2020", "pop", POP["households"]),
        "u15_2020": cell("2020", "age", AGE["u15"]),
        "w15_64_2020": cell("2020", "age", AGE["w15_64"]),
        "o65_2020": o65_20,
        "o75_2020": cell("2020", "age", AGE["o75"]),
        "ratio_u15": pct(cell("2020", "age", AGE["u15"]), age20_total),
        "ratio_w15_64": pct(cell("2020", "age", AGE["w15_64"]), age20_total),
        "ratio_o65": aging20,
        "ratio_o75": pct(cell("2020", "age", AGE["o75"]), age20_total),
        "ratio_o65_2015": aging15,
        "hh_single_ratio": pct(cell("2020", "hh_size", HH_SIZE["single"]),
                               cell("2020", "hh_size", HH_SIZE["total"])),
        "hh_avg_members": fnum("2020", "hh_size", HH_SIZE["avg_members"]),
        "hh_with_o65_ratio": pct(cell("2020", "hh_type", HH_TYPE["with_o65"]), hh20),
        "hh_with_u18_ratio": pct(cell("2020", "hh_type", HH_TYPE["with_u18"]), hh20),
        "hh_with_u6_ratio": pct(cell("2020", "hh_type", HH_TYPE["with_u6"]), hh20),
    }
    if pop20 is not None and pop15:
        d["pop_change"] = pop20 - pop15
        d["pop_change_ratio"] = round((pop20 - pop15) / pop15 * 100, 1)
    else:
        d["pop_change"] = None
        d["pop_change_ratio"] = None
    d["aging_change_pt"] = (
        round(aging20 - aging15, 1) if aging20 is not None and aging15 is not None else None
    )
    return d


def merge_geometries(geoms: list[dict]) -> dict:
    """同一区域コードの複数ポリゴンを1つに束ねる。

    e-Statの境界データは、道路や基地で分断された区域を別レコードに分けて持つ
    （例: 字吉原0050-02 は2レコード。人口は片方にだけ入っている）。
    """
    polys: list = []
    for g in geoms:
        if g["type"] == "Polygon":
            polys.append(g["coordinates"])
        else:
            polys.extend(g["coordinates"])
    if len(polys) == 1:
        return {"type": "Polygon", "coordinates": polys[0]}
    return {"type": "MultiPolygon", "coordinates": polys}


def main() -> None:
    shp = estat.boundary_shapefile()
    stats = load_stats()

    reader = shapefile.Reader(str(shp.with_suffix("")), encoding="cp932")
    fields = [f[0] for f in reader.fields[1:]]
    idx = {name: i for i, name in enumerate(fields)}

    # 区域コードごとに geometry を集約する（1区域が複数レコードに分かれている場合がある）
    grouped: dict[str, dict] = {}
    for sr in reader.iterShapeRecords():
        rec = sr.record
        if f"{rec[idx['PREF']]}{rec[idx['CITY']]}" != CITY_CODE:
            continue
        key = rec[idx["KEY_CODE"]]
        g = grouped.setdefault(
            key,
            {
                "name": rec[idx["S_NAME"]] or "(名称なし)",
                "kcode": rec[idx["KCODE1"]],
                "area_m2": 0.0,
                "geoms": [],
                "parts": 0,
            },
        )
        g["area_m2"] += float(rec[idx["AREA"]] or 0)
        g["geoms"].append(to_geometry(sr.shape))
        g["parts"] += 1

    # 同名の区域（字吉原が6区画あるなど）は基本単位区コードで区別できるようにする
    name_counts: dict[str, int] = {}
    for g in grouped.values():
        name_counts[g["name"]] = name_counts.get(g["name"], 0) + 1

    features = []
    for key, g in sorted(grouped.items()):
        label = g["name"] if name_counts[g["name"]] == 1 else f"{g['name']}〔{g['kcode']}〕"
        props = {
            "key": key,
            "name": g["name"],
            "label": label,
            "area_km2": round(g["area_m2"] / 1_000_000, 4),
        }
        props.update(indicators(key, stats))
        pop = props.get("pop_2020")
        props["pop_density"] = (
            round(pop / (g["area_m2"] / 1_000_000)) if pop and g["area_m2"] else None
        )
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": merge_geometries(g["geoms"]),
            }
        )

    # --- 検証: 区域の人口合計が町計と一致するか ---
    town_row = stats["2020"]["pop"].get(CITY_CODE)
    town_pop = num(town_row[POP["total"]])
    summed = sum(f["properties"]["pop_2020"] or 0 for f in features)
    if summed != town_pop:
        raise SystemExit(
            f"検証失敗: 区域合計 {summed} != 町計 {town_pop}。境界と統計の対応がずれている"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    gj = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "総務省統計局『令和2年国勢調査』『平成27年国勢調査』小地域集計（e-Stat 統計GIS）",
            "boundary": "令和2年国勢調査 町丁・字等別境界データ（世界測地系・JGD2000）",
            "city": "沖縄県中頭郡北谷町",
        },
    }
    (OUT / "chatan_areas.geojson").write_text(
        json.dumps(gj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )

    town = {
        "name": "北谷町",
        "code": CITY_CODE,
        "areas": len(features),
        **indicators(CITY_CODE, stats),
    }
    town["area_km2"] = round(sum(f["properties"]["area_km2"] for f in features), 2)
    (OUT / "chatan_town.json").write_text(
        json.dumps(town, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"区域数 {len(features)} / 人口 {town_pop:,} 人（検証OK）")
    print(f"高齢化率 {town['ratio_o65']}% (2015: {town['ratio_o65_2015']}%)")
    print(f"2015→2020 人口 {town['pop_change']:+,} 人 ({town['pop_change_ratio']:+}%)")


if __name__ == "__main__":
    main()
