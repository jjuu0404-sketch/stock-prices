"""국내·해외 주식 시세를 모아 prices.json 으로 저장한다.

브라우저는 증권 사이트를 직접 못 읽지만(CORS), 파이썬에는 그 제약이 없다.
그래서 이 스크립트를 깃허브 액션에서 돌려 결과 파일만 남기고,
가계부 앱은 그 파일을 읽는다.
"""

import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# 깃허브 서버는 UTC 로 돌아간다. 여기서 쓰는 시세는 한국 장 기준이므로
# 화면에 보일 시각은 항상 한국시각으로 못박는다.
KST = timezone(timedelta(hours=9))

HERE = Path(__file__).parent
TICKERS = HERE / "tickers.json"
WATCHLIST = HERE / "watchlist.txt"
OUT = HERE / "prices.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; household-ledger/1.0)"}

# 국내는 한 번에 여러 종목을 주므로 전 종목을 받아둔다.
NAVER = "https://polling.finance.naver.com/api/realtime/domestic/stock/{}"
# 해외는 묶음 조회가 막혀(401) 종목당 한 번씩 불러야 한다.
# 5천 종목을 매번 도는 건 낭비라, watchlist.txt 에 적은 것만 받는다.
YAHOO_ONE = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1d&range=1d"

KR_BATCH = 50     # 네이버가 한 번에 받아주는 종목 수


def get(url, tries=3):
    for i in range(tries):
        try:
            with urlopen(Request(url, headers=UA), timeout=30) as r:
                return r.read()
        except (HTTPError, URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_kr(codes):
    """네이버는 쉼표로 여러 종목을 한 번에 준다."""
    out = {}
    for group in chunks(codes, KR_BATCH):
        try:
            data = json.loads(get(NAVER.format(",".join(group))))
        except Exception as e:
            print(f"  국내 {group[0]}… 실패: {e}", file=sys.stderr)
            continue
        for d in data.get("datas", []):
            price = re.sub(r"[^\d.-]", "", str(d.get("closePrice", "")))
            if price:
                out[d["itemCode"]] = float(price)
        time.sleep(0.2)      # 예의상 간격
    return out


def fetch_us(symbols):
    """해외는 종목당 한 번씩. watchlist 에 적힌 것만 돈다."""
    out = {}
    for sym in symbols:
        try:
            data = json.loads(get(YAHOO_ONE.format(sym)))
            meta = data["chart"]["result"][0]["meta"]
            p = meta.get("regularMarketPrice")
            if p is not None:
                out[sym] = float(p)
        except Exception as e:
            print(f"  해외 {sym} 실패: {e}", file=sys.stderr)
        time.sleep(0.3)
    return out


def read_watchlist():
    if not WATCHLIST.exists():
        return []
    lines = WATCHLIST.read_text(encoding="utf-8").splitlines()
    return [ln.split("#")[0].strip().upper() for ln in lines
            if ln.split("#")[0].strip()]


def main():
    tickers = json.loads(TICKERS.read_text(encoding="utf-8"))
    kr = [t["c"] for t in tickers if t["m"] in ("KOSPI", "KOSDAQ")]
    us = read_watchlist()
    print(f"국내 {len(kr):,}종목 / 해외 {len(us)}종목(watchlist)")

    prices = {}
    prices.update(fetch_kr(kr))
    print(f"  국내 {len(prices):,}종목 수집")

    if us:
        before = len(prices)
        prices.update(fetch_us(us))
        print(f"  해외 {len(prices) - before}종목 수집")

    if not prices:
        print("한 건도 못 받았다. 이전 파일을 그대로 둔다.", file=sys.stderr)
        return 1

    now = datetime.now(KST)
    payload = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),      # 한국시각
        "tz": "KST",
        "updatedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(prices),
        "prices": prices,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"\n{len(prices):,}종목 -> {OUT.name} ({OUT.stat().st_size/1024:.0f}KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
