#!/usr/bin/env python3
"""
오늘의 투자 운세 — 지수 데이터 수집 스크립트
GitHub Actions에서 주기적으로 실행되어 지수를 가져와 data/indices.json에 저장합니다.

- KOSPI·KOSDAQ: 네이버페이 증권의 실시간 폴링 API 사용 (거의 실시간, ~20초 단위 갱신)
- 다우존스·나스닥: Yahoo Finance 사용
  (한국 낮 시간엔 미국 장이 닫혀있어 "전일 종가"가 곧 최신 정보이므로
   실시간 여부가 큰 의미 없음)

서버(GitHub Actions)에서 직접 호출하므로 CORS 문제가 발생하지 않습니다.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_json(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ── 국내 지수: 네이버 실시간 폴링 API ──
NAVER_INDEX = [
    {"code": "KOSPI",  "name": "KOSPI",  "flag": "🇰🇷"},
    {"code": "KOSDAQ", "name": "KOSDAQ", "flag": "🇰🇷"},
]

def _first_of(d, keys):
    """딕셔너리에서 여러 후보 키 중 처음 발견되는 값을 반환."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def fetch_naver_index(code):
    url = f"https://polling.finance.naver.com/api/realtime/domestic/index/{code}"
    try:
        raw = fetch_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ⚠️  {code} 요청 실패: {e}")
        return None

    print(f"  🔍 {code} 원본 응답(디버그, 500자): {json.dumps(raw, ensure_ascii=False)[:500]}")

    if raw.get("resultCode") not in (None, "success"):
        print(f"  ⚠️  {code} 응답 오류(resultCode={raw.get('resultCode')})")
        return None

    # 응답 구조가 바뀌었을 가능성에 대비해 여러 경로를 시도
    item = None
    try:
        item = raw["result"]["areas"][0]["datas"][0]
    except (KeyError, IndexError, TypeError):
        pass
    if item is None:
        try:
            item = raw["datas"][0]
        except (KeyError, IndexError, TypeError):
            pass
    if item is None and isinstance(raw.get("result"), dict):
        item = raw["result"]
    if item is None:
        print(f"  ⚠️  {code} 응답 구조에서 데이터 항목을 찾지 못함")
        return None

    # 실제 확인된 필드명(2026-09): closePrice, compareToPreviousClosePrice, fluctuationsRatio
    # 단, 값이 "6,628.15" 같은 콤마 포함 문자열로 오므로 반드시 정제 후 float 변환해야 함
    cur_raw = _first_of(item, ["closePrice", "nv", "tradePrice", "close", "currentPrice", "price"])
    chg_raw = _first_of(item, ["compareToPreviousClosePrice", "cv", "changePrice", "change"])
    pct_raw = _first_of(item, ["fluctuationsRatio", "cr", "changeRate", "rate"])
    prev_raw = _first_of(item, ["pcv", "prevClosePrice", "basePrice", "previousClose", "sv"])

    def to_float(v):
        """'6,628.15' / '-207.65' / 6628.15 등 다양한 형태를 float로 안전 변환."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).replace(",", "").strip()
        try:
            return float(s)
        except ValueError:
            return None

    cur = to_float(cur_raw)
    prev = to_float(prev_raw)
    chg = to_float(chg_raw)
    chg_pct = to_float(pct_raw)

    if cur is None:
        print(f"  ⚠️  {code} 현재가 필드를 찾지 못함. 항목 내용: {json.dumps(item, ensure_ascii=False)[:300]}")
        return None

    # 등락 방향(하락이면 부호를 음수로) — compareToPreviousPrice.code: "1"상한 "2"상승 "3"보합 "4"하한 "5"하락
    direction = item.get("compareToPreviousPrice", {})
    if isinstance(direction, dict) and direction.get("code") in ("4", "5"):
        if chg is not None and chg > 0:
            chg = -chg
        if chg_pct is not None and chg_pct > 0:
            chg_pct = -chg_pct

    if chg is None:
        chg = (cur - prev) if prev is not None else 0.0
    if chg_pct is None:
        chg_pct = (chg / prev * 100) if prev else 0.0

    return {
        "val": round(cur, 2),
        "chg": round(chg, 2),
        "chgPct": round(chg_pct, 2),
        "realtime": True,
    }


# ── 해외 지수: Yahoo Finance ──
YAHOO_INDEX = [
    {"sym": "^DJI",  "name": "다우존스", "flag": "🇺🇸"},
    {"sym": "^IXIC", "name": "나스닥",   "flag": "🇺🇸"},
]

def fetch_yahoo_index(sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
    try:
        data = fetch_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  ⚠️  {sym} 요청 실패: {e}")
        return None

    result = data.get("chart", {}).get("result")
    if not result:
        print(f"  ⚠️  {sym} 데이터 없음")
        return None

    meta = result[0].get("meta", {})
    cur = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")

    if cur is None:
        return None
    if prev is None:
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in quotes.get("close", []) if c is not None]
        prev = closes[-2] if len(closes) >= 2 else cur

    chg = cur - prev
    chg_pct = (chg / prev * 100) if prev else 0

    return {
        "val": round(cur, 2),
        "chg": round(chg, 2),
        "chgPct": round(chg_pct, 2),
        "realtime": False,
    }


def main():
    print("📊 지수 데이터 수집 시작...\n")
    indices = []

    print("── 국내 지수 (네이버 실시간) ──")
    for item in NAVER_INDEX:
        print(f"  → {item['name']} 조회 중...")
        result = fetch_naver_index(item["code"])
        if result:
            indices.append({"name": item["name"], "flag": item["flag"], **result})
            print(f"    ✅ {item['name']}: {result['val']} ({result['chgPct']:+.2f}%)")
        else:
            print(f"    ❌ {item['name']} 수집 실패 — 건너뜀")

    print("\n── 해외 지수 (Yahoo Finance, 전일 종가 기준) ──")
    for item in YAHOO_INDEX:
        print(f"  → {item['name']} ({item['sym']}) 조회 중...")
        result = fetch_yahoo_index(item["sym"])
        if result:
            indices.append({"name": item["name"], "flag": item["flag"], **result})
            print(f"    ✅ {item['name']}: {result['val']} ({result['chgPct']:+.2f}%)")
        else:
            print(f"    ❌ {item['name']} 수집 실패 — 건너뜀")

    kst = timezone(timedelta(hours=9))
    output = {
        "updated_at": datetime.now(kst).isoformat(),
        "indices": indices,
    }

    with open("data/indices.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료: {len(indices)}/{len(NAVER_INDEX)+len(YAHOO_INDEX)}개 지수 저장됨")

    if not indices:
        print("⚠️  경고: 수집된 지수가 하나도 없습니다.")
        exit(1)


if __name__ == "__main__":
    main()
