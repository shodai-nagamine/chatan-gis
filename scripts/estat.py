"""e-Stat 統計GIS からの取得・キャッシュ・パース。

境界データも小地域統計も、統計GIS の同じダウンロードエンドポイントから取れる。
どのファイルも一度落としたら data/raw/ に置いたまま使い回す（再実行を安くするため）。
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

GIS_ENDPOINT = "https://www.e-stat.go.jp/gis/statmap-search/data"
UA = "chatan-gis/0.1 (personal civic data project; contact via GitHub issues)"

PREF = "47"          # 沖縄県
CITY_CODE = "47326"  # 北谷町

# 令和2年国勢調査 小地域（町丁・字等別）の境界データ
BOUNDARY = {
    "dlserveyId": "A002005212020",
    "code": PREF,
    "coordSys": "1",   # 1 = 世界測地系・緯度経度
    "format": "shape",
    "downloadType": "5",
    "datum": "2000",   # JGD2000
}

# 小地域統計。R2 と H27 で表IDが違うだけで列レイアウトは同一（列数を assert で確認する）。
TABLES = {
    "2020": {
        "pop": "T0001081",        # 男女別人口総数及び世帯総数
        "age": "T0001082",        # 年齢(5歳階級)別人口
        "hh_size": "T0001083",    # 世帯人員別一般世帯数
        "hh_type": "T0001084",    # 世帯の家族類型別一般世帯数
    },
    "2015": {
        "pop": "T000848",
        "age": "T000849",
        "hh_size": "T000850",
        "hh_type": "T000851",
    },
}

EXPECTED_COLS = {"pop": 11, "age": 67, "hh_size": 15, "hh_type": 16}


def _get(params: dict, dest: Path) -> Path:
    """キャッシュが無ければ取得。あるものはそのまま返す。"""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(GIS_ENDPOINT, params=params, headers={"User-Agent": UA}, timeout=300)
    r.raise_for_status()
    if not r.content[:2] == b"PK":
        raise RuntimeError(f"ZIPが返ってこなかった: {dest.name} / {r.content[:120]!r}")
    dest.write_bytes(r.content)
    return dest


def boundary_shapefile() -> Path:
    """境界Shapefileを展開し、.shp のパスを返す。"""
    zp = _get(BOUNDARY, RAW / "boundary_47.zip")
    out = RAW / "boundary_47"
    if not (out / "r2ka47.shp").exists():
        with zipfile.ZipFile(zp) as z:
            z.extractall(out)
    return out / "r2ka47.shp"


def small_area_table(stats_id: str, kind: str) -> dict[str, list[str]]:
    """小地域統計を KEY_CODE -> 数値列(文字列のまま) の辞書で返す。

    e-Stat の小地域CSVは 1行目が列ID、2行目が日本語ラベル（令和2年分は空）、
    3行目以降がデータ。先頭7列がメタ（KEY_CODE, HYOSYO, CITYNAME, NAME, ...）。
    """
    zp = _get(
        {"statsId": stats_id, "code": PREF, "downloadType": "2"},
        RAW / f"{stats_id}_47.zip",
    )
    with zipfile.ZipFile(zp) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("cp932")

    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    if len(header) != EXPECTED_COLS[kind]:
        raise RuntimeError(
            f"{stats_id}: 列数が想定と違う（{len(header)} != {EXPECTED_COLS[kind]}）。"
            "e-Stat側で表構成が変わった可能性がある"
        )

    out: dict[str, list[str]] = {}
    for row in rows[2:]:
        if not row or not row[0].startswith(CITY_CODE):
            continue
        out[row[0]] = row[7:]
    if not out:
        raise RuntimeError(f"{stats_id}: 北谷町({CITY_CODE})の行が1件も無い")
    return out


def num(v: str) -> int | None:
    """統計値を整数に。秘匿(*)・該当なし(-)・空欄は None。"""
    v = (v or "").strip()
    if v in ("", "-", "*", "X", "x"):
        return None
    try:
        return int(v)
    except ValueError:
        try:
            return int(float(v))
        except ValueError:
            return None
