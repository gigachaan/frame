"""
OSINT 수집기 (OSINTCollector)
- Tavily Search API 연동
- 화이트리스트 도메인 자동 필터링 및 티어(Tier 1, 2, 3) 메타데이터 태깅
- 순환 보고(Circular Reporting / 재인용) 자동 감지
- 다국어 줄바꿈 안전 문단 분할 (Paragraph Chunking)
- 다국어 쿼리 중복 URL 자동 제거 (Deduplication)
"""

import os
import re
import uuid
from typing import List, Dict, Optional
from urllib.parse import urlparse

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

from config import (
    OSINT_WHITELIST,
    QUOTE_PATTERNS,
    MAX_RAW_CHARS,
    MAX_PARAGRAPH_CHARS,
    MIN_PARAGRAPH_CHARS,
)


class OSINTCollector:
    """국방/안보 OSINT 데이터 전처리 및 수집 엔진"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        if TavilyClient is not None:
            self.client = TavilyClient(api_key=self.api_key)
        else:
            self.client = None
        # 화이트리스트에 등록된 모든 도메인을 기본 검색 대상으로 지정
        self.allowed_domains = list(OSINT_WHITELIST.keys())

    def _resolve_tier_meta(self, url: str) -> Dict:
        """URL의 호스트네임을 기반으로 티어/국가/가중치 메타데이터 매핑"""
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        for domain, meta in OSINT_WHITELIST.items():
            if domain in hostname:
                return meta

        return {
            "tier": 4,
            "country": "UNKNOWN",
            "category": "unverified",
            "name": hostname or "Unknown Source",
            "weight": 0.50,
        }

    def _extract_attribution_hint(self, text: str) -> Optional[str]:
        """본문 초반 500자에서 다른 출처나 통신사를 재인용한 구절을 감지"""
        prefix = text[:500]
        for pattern in QUOTE_PATTERNS:
            match = re.search(pattern, prefix, re.IGNORECASE)
            if match:
                hint = match.group(1).strip()
                if 2 <= len(hint) <= 40:
                    return hint
        return None

    def _split_into_paragraphs(self, text: str) -> List[str]:
        """동양권(중국어/일본어) 및 웹 크롤링 줄바꿈 이슈를 해결하는 안전한 문단 분리기"""
        raw_pieces = re.split(r'\n\s*\n|\n', text)
        paragraphs = []

        for piece in raw_pieces:
            piece = piece.strip()
            if len(piece) < MIN_PARAGRAPH_CHARS:
                continue

            for i in range(0, len(piece), MAX_PARAGRAPH_CHARS):
                chunk = piece[i : i + MAX_PARAGRAPH_CHARS].strip()
                if chunk:
                    paragraphs.append(chunk)

        if not paragraphs and text.strip():
            paragraphs = [text[:MAX_PARAGRAPH_CHARS].strip()]

        return paragraphs

    def collect(self, query: str, days_back: int = 3, max_results: int = 5) -> List[Dict]:
        """단일 검색어로 Tavily를 검색하고 규격화된 문서 딕셔너리 리스트 반환"""
        if self.client is None:
            print("[-] 'tavily-python' 패키지가 필요합니다: pip install tavily-python")
            return []

        time_range = "day" if days_back <= 1 else "week" if days_back <= 7 else "month"

        try:
            response = self.client.search(
                query=query,
                search_depth="advanced",
                include_domains=self.allowed_domains,
                time_range=time_range,
                include_raw_content=True,
                max_results=max_results,
            )
        except Exception as e:
            print(f"[-] Tavily 검색 실패 (Query: '{query}'): {e}")
            return []

        documents = []
        for item in response.get("results", []):
            url = item.get("url", "")
            raw_text = item.get("raw_content") or item.get("content") or ""
            if not raw_text.strip():
                continue

            tier_info = self._resolve_tier_meta(url)
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"

            is_truncated = len(raw_text) > MAX_RAW_CHARS
            status = "success_truncated" if is_truncated else "success_full"

            clipped_text = raw_text[:MAX_RAW_CHARS]
            paragraphs_text = self._split_into_paragraphs(clipped_text)
            quoted_source = self._extract_attribution_hint(clipped_text)

            doc_entry = {
                "doc_id": doc_id,
                "url": url,
                "title": item.get("title", ""),

                # 🏷️ [티어 메타데이터]
                "tier": tier_info["tier"],
                "source_name": tier_info["name"],
                "country": tier_info["country"],
                "source_category": tier_info["category"],
                "credibility_weight": tier_info["weight"],

                # 🔄 [순환 보고 방어 메타데이터]
                "is_reprint_likely": bool(quoted_source),
                "quoted_source": quoted_source,

                # ⏱️ [시간 및 상태]
                "published_date": item.get("published_date") or None,
                "event_date": None,
                "status": status,

                # 📑 [문단 단위 목록]
                "paragraphs": [
                    {
                        "paragraph_id": f"{doc_id}_p{idx + 1}",
                        "raw_text": p_text,
                    }
                    for idx, p_text in enumerate(paragraphs_text)
                ],
            }
            documents.append(doc_entry)

        return documents

    def collect_multilingual(
        self, queries: List[str], days_back: int = 3, max_results_per_query: int = 5
    ) -> List[Dict]:
        """다국어 쿼리 리스트를 받아 중복 URL을 제거하고 통합 수집"""
        all_docs = []
        seen_urls = set()

        for q in queries:
            docs = self.collect(
                query=q, days_back=days_back, max_results=max_results_per_query
            )
            for d in docs:
                if d["url"] not in seen_urls:
                    seen_urls.add(d["url"])
                    all_docs.append(d)

        print(f"[✓] 다국어 수집 완료: {len(queries)}개 쿼리로부터 {len(all_docs)}건 고유 문서 확보")
        return all_docs
