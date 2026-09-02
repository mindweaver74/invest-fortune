#!/usr/bin/env python3
"""
오늘의 투자 운세 — 지수 데이터 수집 스크립트
GitHub Actions에서 주기적으로 실행되어 Yahoo Finance에서 지수를 가져와
data/indices.json 파일로 저장합니다.

서버(GitHub Actions)에서 직접 호출하므로 CORS 문제가 발생하지 않습니다.
브라우저는 이 JSON 파일만 읽으면 됩니다.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# 가져올 지수 목록 (Yahoo Finance 심볼)
INDEX_LIST = [
    {"sym": "^KS11", "name": "KOSPI",   "flag": "🇰🇷"},
    {"sym": "^KQ11", "name": "KOSDAQ",  "flag": "🇰🇷"},
    {"sym": "^DJI",  "name": "다우존스", "flag": "🇺🇸"},
    {"sym": "^IXIC", "name": "나스닥",   "flag": "🇺🇸"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_index(sym):
    """Yahoo Finance v8 chart API에서 지수 하나를 가져온다."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        f"?interval=1d&range=5d"
    )
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
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
        # 종가 배열에서 직전 종가 추출 시도
        quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in quotes.get("close", []) if c is not None]
        if len(closes) >= 2:
            prev = closes[-2]
        else:
            prev = cur

    chg = cur - prev
    chg_pct = (chg / prev * 100) if prev else 0

    return {
        "val": round(cur, 2),
        "chg": round(chg, 2),
        "chgPct": round(chg_pct, 2),
    }


def main():
    print("📊 지수 데이터 수집 시작...")
    indices = []

    for item in INDEX_LIST:
        print(f"  → {item['name']} ({item['sym']}) 조회 중...")
        result = fetch_index(item["sym"])
        if result:
            indices.append({
                "name": item["name"],
                "flag": item["flag"],
                **result,
            })
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

    print(f"\n✅ 완료: {len(indices)}/{len(INDEX_LIST)}개 지수 저장됨 → data/indices.json")

    if not indices:
        print("⚠️  경고: 수집된 지수가 하나도 없습니다. Yahoo Finance 응답을 확인하세요.")
        exit(1)


if __name__ == "__main__":
    main()
