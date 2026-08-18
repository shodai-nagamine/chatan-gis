"""北谷町の医療機関・介護事業所を点データ（GeoJSON）にする。

出力: docs/data/chatan_facilities.geojson

医療機関 … 国土数値情報「医療機関データ P04」（緯度経度つき、2020年）
介護事業所 … 厚生労働省「介護サービス情報公表システム」オープンデータ
             （CC BY 相当。緯度経度の列を持つので住所の変換は要らない）
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "facilities"
OUT = ROOT / "docs" / "data"
UA = "chatan-gis/0.1 (personal civic data project; contact via GitHub issues)"

MLIT_P04 = "https://nlftp.mlit.go.jp/ksj/gml/data/P04/P04-20/P04-20_47_GML.zip"
KAIGO_INDEX = "https://www.mhlw.go.jp/stf/kaigo-kouhyou_opendata.html"

# 医療機関の施設分類（P04_001）
MED_KINDS = {1: "病院", 2: "診療所", 3: "歯科診療所"}

# 取り込む介護サービス。地図の凡例を4系統に畳むため category を持たせる。
KAIGO_SERVICES = {
    "510": ("介護老人福祉施設（特養）", "入所"),
    "520": ("介護老人保健施設（老健）", "入所"),
    "540": ("地域密着型介護老人福祉施設", "入所"),
    "550": ("介護医療院", "入所"),
    "320": ("認知症対応型共同生活介護（GH）", "入所"),
    "331": ("特定施設入居者生活介護（有料老人ホーム）", "入所"),
    "334": ("特定施設入居者生活介護（サ高住）", "入所"),
    "150": ("通所介護（デイサービス）", "通所"),
    "780": ("地域密着型通所介護", "通所"),
    "160": ("通所リハビリテーション", "通所"),
    "720": ("認知症対応型通所介護", "通所"),
    "210": ("短期入所生活介護（ショートステイ）", "通所"),
    "730": ("小規模多機能型居宅介護", "通所"),
    "770": ("看護小規模多機能型居宅介護", "通所"),
    "110": ("訪問介護", "訪問・相談"),
    "130": ("訪問看護", "訪問・相談"),
    "140": ("訪問リハビリテーション", "訪問・相談"),
    "760": ("定期巡回・随時対応型訪問介護看護", "訪問・相談"),
    "430": ("居宅介護支援（ケアプラン）", "訪問・相談"),
}

CITY = "北谷町"
CITY_CODE = "47326"


def fetch(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers={"User-Agent": UA}, timeout=600)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def kaigo_csv_urls() -> dict[str, str]:
    """公表ページから サービスコード -> CSVのURL を拾う。

    URLに更新日時が埋まっていて版ごとに変わるため、固定せずページから解決する。
    """
    r = requests.get(KAIGO_INDEX, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    found = {}
    for m in re.finditer(r'href="(/content/12300000/jigyosho_(\d+)_all_\d+\.csv)"', r.text):
        found[m.group(2)] = "https://www.mhlw.go.jp" + m.group(1)
    if not found:
        raise RuntimeError("介護サービスのCSVリンクを1件も取得できなかった")
    return found


def medical_features() -> list[dict]:
    zp = fetch(MLIT_P04, RAW / "P04-20_47.zip")
    with zipfile.ZipFile(zp) as z:
        name = next(n for n in z.namelist() if n.endswith(".geojson"))
        data = json.loads(z.read(name).decode("utf-8"))

    out = []
    for f in data["features"]:
        p = f["properties"]
        addr = p.get("P04_003") or ""
        if CITY not in addr:
            continue
        kind = MED_KINDS.get(p.get("P04_001"), "その他の医療機関")
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {
                    "name": (p.get("P04_002") or "").strip(),
                    "category": "医療",
                    "kind": kind,
                    "address": addr.strip(),
                    "detail": (p.get("P04_004") or "").strip(),  # 診療科目
                    "source": "国土数値情報 医療機関データ（2020年）",
                },
            }
        )
    return out


def kaigo_features() -> list[dict]:
    urls = kaigo_csv_urls()
    out = []
    missing = []
    for code, (label, category) in KAIGO_SERVICES.items():
        url = urls.get(code)
        if not url:
            missing.append(code)
            continue
        path = fetch(url, RAW / f"kaigo_{code}.csv")
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for row in csv.DictReader(io.StringIO(text)):
            city = (row.get("市区町村名") or "").strip()
            code_col = (row.get("都道府県コード又は市町村コード") or "").strip()
            if CITY not in city and not code_col.startswith(CITY_CODE):
                continue
            try:
                lat = float(row.get("緯度") or "")
                lon = float(row.get("経度") or "")
            except ValueError:
                continue
            if not (26.0 < lat < 26.6 and 127.5 < lon < 128.0):
                continue  # 明らかに町外の座標は落とす
            out.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                    "properties": {
                        "name": (row.get("事業所名") or "").strip(),
                        "category": category,
                        "kind": label,
                        "address": ((row.get("住所") or "") + " " + (row.get("方書（ビル名等）") or "")).strip(),
                        "detail": (row.get("定員") or "").strip(),
                        "source": "介護サービス情報公表システム（厚生労働省）",
                    },
                }
            )
    if missing:
        print(f"  ※ CSVが見つからなかったサービスコード: {', '.join(missing)}")
    return out


def main() -> None:
    med = medical_features()
    kaigo = kaigo_features()

    # 同一事業所が複数サービスで重複するので、名前＋座標でまとめてサービス名を束ねる
    merged: dict[tuple, dict] = {}
    for f in med + kaigo:
        p = f["properties"]
        key = (p["name"], tuple(f["geometry"]["coordinates"]))
        if key in merged:
            kinds = merged[key]["properties"]["kinds"]
            if p["kind"] not in kinds:
                kinds.append(p["kind"])
            continue
        p = dict(p)
        p["kinds"] = [p.pop("kind")]
        merged[key] = {"type": "Feature", "geometry": f["geometry"], "properties": p}

    features = sorted(merged.values(), key=lambda f: (f["properties"]["category"], f["properties"]["name"]))

    counts: dict[str, int] = {}
    for f in features:
        c = f["properties"]["category"]
        counts[c] = counts.get(c, 0) + 1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chatan_facilities.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
                "metadata": {
                    "counts": counts,
                    "sources": [
                        "国土数値情報「医療機関データ」（国土交通省、2020年）",
                        "「介護サービス情報公表システム」オープンデータ（厚生労働省、2026年7月時点）",
                    ],
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"施設 {len(features)} 件: " + " / ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
