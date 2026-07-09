"""테스트 fixture — 가짜 DART 응답(라이브 키 없이 정규화·upsert 검증)."""

from __future__ import annotations

from typing import Any

# 가짜 DART intermediate: 삼성전자 예시(계정명 일부만, 일부 누락으로 null 검증)
DART_RAW_SAMSUNG: dict[str, Any] = {
    "company": {
        "corp_code": "00126380",
        "stock_code": "005930",
        "corp_name": "삼성전자",
        "market": "KOSPI",
        "sector": "반도체",
    },
    "periods": [
        {
            "year": 2026,
            "quarter": 1,
            "accounts": {
                "매출액": 70_000_000_000_000,
                "당기순이익": 8_000_000_000_000,
                "영업이익": 9_000_000_000_000,
                "자본총계": 300_000_000_000_000,
                "자산총계": 450_000_000_000_000,
                "부채총계": 150_000_000_000_000,
                "현금및현금성자산": 40_000_000_000_000,
                # depreciation·차입금 누락 → null 검증
            },
            "dividend_total": 2_000_000_000_000,
            # buyback 항목 누락 → null
        }
    ],
}
