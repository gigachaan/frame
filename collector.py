"""
OSINT 수집기 (OSINTCollector)
- Tavily Search API 연동
- 내장 .env 파일 자동 로더 (.env 자동 감지)
- 언어 태그(language: zh, ja, ko, en) 자동 판별
- 화이트리스트 도메인 자동 필터링 및 티어(Tier 1, 2, 3) 메타데이터 태깅
- 순환 보고(Circular Reporting / 재인용) 자동 감지
- 다국어 줄바꿈 안전 문단 분할 (Paragraph Chunking)
- 다국어 쿼리 중복 URL 자동 제거 (Deduplication)
- JSON 파일 저장/불러오기 지원 (export_json, load_json)
"""

import json
import os
import re
import uuid
from pathlib import Path
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


def auto_load_dotenv(env_path: Optional[str] = None) -> None:
    """별도 패키지 설치 없이 .env 파일을 읽어 환경변수에 자동 등록하는 경량 로더"""
    paths_to_check = [
        Path(env_path) if env_path else None,
        Path(".env"),
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in paths_to_check:
        if p and p.is_file():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            clean_k = k.strip()
                            clean_v = v.strip().strip("'\"")
                            if clean_k and clean_k not in os.environ:
                                os.environ[clean_k] = clean_v
                break
            except Exception:
                pass


# 모듈 임포트 시 자동으로 .env 로드 시도
auto_load_dotenv()


class OSINTCollector:
    """국방/안보 OSINT 데이터 전처리 및 수집 엔진"""

    def __init__(self, api_key: Optional[str] = None):
        # 환경변수 또는 직접 전달받은 API 키 사용
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        if TavilyClient is not None and self.api_key:
            self.client = TavilyClient(api_key=self.api_key)
        else:
            self.client = None
        # 화이트리스트에 등록된 모든 도메인을 기본 검색 대상으로 지정
        self.allowed_domains = list(OSINT_WHITELIST.keys())

    def _resolve_tier_meta(self, url: str) -> Dict:
        """URL의 호스트네임을 기반으로 티어/국가/언어/가중치 메타데이터 매핑"""
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        for domain, meta in OSINT_WHITELIST.items():
            if domain in hostname:
                return meta

        return {
            "tier": 4,
            "country": "UNKNOWN",
            "language": "unknown",
            "category": "unverified",
            "name": hostname or "Unknown Source",
            "weight": 0.50,
        }

    def _detect_language(self, url: str, text: str) -> str:
        """도메인 메타데이터 또는 본문 문자 분포를 기반으로 언어(zh, ja, ko, en) 판별"""
        meta = self._resolve_tier_meta(url)
        if meta.get("language") and meta["language"] != "unknown":
            return meta["language"]

        # 도메인 정보가 없을 경우 본문 글자 패턴 분석
        sample = text[:300]
        # 한글 감지 (가-힣)
        if re.search(r'[가-힣]', sample):
            return "ko"
        # 일본어 가나 감지 (히라가나/가타카나)
        if re.search(r'[぀-ヿ]', sample):
            return "ja"
        # 한자(중국어) 감지
        if re.search(r'[一-鿿]', sample):
            return "zh"
        # 영문/기타
        return "en"

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
            print("[-] Tavily 클라이언트가 준비되지 않았습니다. TAVILY_API_KEY 확인 또는 pip install tavily-python 필요")
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
            language = self._detect_language(url, raw_text)

            is_truncated = len(raw_text) > MAX_RAW_CHARS
            status = "success_truncated" if is_truncated else "success_full"

            clipped_text = raw_text[:MAX_RAW_CHARS]
            paragraphs_text = self._split_into_paragraphs(clipped_text)
            quoted_source = self._extract_attribution_hint(clipped_text)

            doc_entry = {
                "doc_id": doc_id,
                "url": url,
                "title": item.get("title", ""),
                "language": language,  # 🌐 [자동 언어 판별 태그: zh, ja, ko, en]

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
                "query": query,  # 🔍 [수집에 사용된 검색어]
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

    def _expand_korean_to_7_actors(self, question: str, event_date: Optional[str] = None) -> Dict[str, str]:
        """
        한국어 질문을 입력받아 7개 주요 안보 행위자
        (중국, 대만, 일본, 한국, 인도, 파키스탄, 미국/글로벌)별 맞춤형 검색 쿼리로 자동 변환
        """
        date_str = f"{event_date} " if event_date else ""
        q_lower = question.lower()

        # [주제 1: 대만해협 / 양안 군사동향]
        if any(k in question for k in ["대만", "양안", "차이잉원", "라이칭더", "중화민국"]):
            return {
                "CN": f"{date_str}台湾海峡 解放军 演习 战备警巡 东部战区 军机",
                "TW": f"{date_str}台灣海峽 國防部 共機 越過中線 演習",
                "JP": f"{date_str}台湾海峡 中国軍機 演習 防衛省 統合幕僚監部",
                "KR": f"{date_str}{question} 국방부 군용기 동향",
                "IN": f"{date_str}Taiwan Strait PLA military aircraft exercise China Taiwan",
                "PK": f"{date_str}Taiwan Strait military activity China Taiwan tension",
                "US": f"{date_str}Taiwan Strait PLA military exercises median line DoD",
            }

        # [주제 2: 인도-파키스탄 / 카슈미르 국경]
        elif any(k in question for k in ["인도", "파키스탄", "카슈미르", "국경"]):
            return {
                "IN": f"{date_str}Indian Army Line of Control Kashmir border infiltration ceasefire",
                "PK": f"{date_str}ISPR Pakistan Army Line of Control border ceasefire Indian firing",
                "CN": f"{date_str}印巴 边境 冲突 克什米尔 实际控制线",
                "KR": f"{date_str}{question} 인도 파키스탄 카슈미르 국경 충돌",
                "JP": f"{date_str}インド パキスタン カシミール 国境 停戦ライン 衝突",
                "TW": f"{date_str}印度 巴基斯坦 邊界 喀什米爾 衝突",
                "US": f"{date_str}India Pakistan border clash Kashmir Line of Control",
            }

        # [주제 3: 일반 안보 질문 기본 변환]
        return {
            "KR": f"{date_str}{question} 국방부 발표",
            "CN": f"{date_str}{question} 国防部 军演",
            "TW": f"{date_str}{question} 國防部 軍事",
            "JP": f"{date_str}{question} 防衛省 自衛隊 発表",
            "US": f"{date_str}{question} military defense statement DoD",
            "IN": f"{date_str}{question} military exercise defence ministry India",
            "PK": f"{date_str}{question} military security ISPR Pakistan",
        }

    def collect_from_korean(
        self,
        question: str,
        event_date: Optional[str] = None,
        max_total_docs: int = 5,
        days_back: int = 30,
    ) -> Dict:
        """
        [핵심 함수] 한국어 질문 1개만 넣으면:
        1. 중국, 대만, 일본, 한국, 인도, 파키스탄, 미국 7개국 쿼리로 자동 변환
        2. 화이트리스트 기반 다국어 수집
        3. 최대 5건으로 압축하여 7개국별로 그룹화 반환
        """
        print(f"\n[🌐] 한국어 질문 감지: '{question}' (일자: {event_date or '전체'})")
        print("[+] 7개국(중국, 대만, 일본, 한국, 인도, 파키스탄, 미국) 맞춤 쿼리로 자동 변환 중...")

        query_map = self._expand_korean_to_7_actors(question, event_date)
        for country_key, q in query_map.items():
            print(f"  - [{country_key}] 쿼리: '{q}'")

        # 각 국가별로 1~2건씩 검색 후 통합
        all_collected = self.collect_multilingual(
            queries=query_map,
            days_back=days_back,
            max_results_per_query=2,
        )

        # 🎯 최대 5건으로 수집 결과 제한
        capped_docs = all_collected[:max_total_docs]
        print(f"\n[🔒] 수집 건수 제한 적용: 총 {len(all_collected)}건 중 최상위 {len(capped_docs)}건 최종 선별 (최대 {max_total_docs}건 제한)")

        # 7개국별로 깔끔하게 그룹화
        by_country = {
            "CN": [],  # 중국
            "TW": [],  # 대만
            "JP": [],  # 일본
            "KR": [],  # 한국
            "IN": [],  # 인도
            "PK": [],  # 파키스탄
            "US": [],  # 미국 / 글로벌
        }

        for doc in capped_docs:
            c = doc.get("country", "").upper()
            if c in by_country:
                by_country[c].append(doc)
            elif c in ("GLOBAL", "SG", "PH"):
                by_country["US"].append(doc)
            else:
                by_country.setdefault("OTHER", []).append(doc)

        return {
            "korean_question": question,
            "event_date": event_date,
            "generated_queries": query_map,
            "by_country": by_country,
            "total_count": len(capped_docs),
            "all_documents": capped_docs,
        }

    def collect_plan(
        self,
        plan: dict,
        days_back: int = 7,
        max_total_docs: int = 5,
        max_results_per_query: int = 3,
    ) -> Dict:
        """
        앞단(Orchestrator/나현님)의 요청 포맷(event, event_date, queries)을 받아 수집하고,
        중국, 대만, 일본, 한국, 인도, 파키스탄, 미국 7개국 그룹화 결과 및 전체 리스트를 반환합니다.
        (결과는 최대 max_total_docs건으로 제한)
        """
        event = plan.get("event", "")
        event_date = plan.get("event_date")
        raw_queries = plan.get("queries", [])

        # 쿼리 파싱
        query_map = {}
        for item in raw_queries:
            if isinstance(item, dict):
                lang = item.get("language", "unknown")
                q = item.get("query", "")
                if q:
                    query_map[lang] = q
            elif isinstance(item, str):
                query_map[f"q_{len(query_map)+1}"] = item

        # 🇰🇷 한국어 쿼리가 없으면 한국 출처 수집을 위해 자동 보강
        if "ko" not in query_map and event:
            date_prefix = f"{event_date} " if event_date else ""
            query_map["ko"] = f"{date_prefix}{event} 군용기 동향 국방부 발표".strip()
            print(f"  [+] 한국 출처 수집을 위해 한국어 쿼리 자동 추가: '{query_map['ko']}'")

        # 다국어 수집 실행
        all_docs = self.collect_multilingual(
            queries=query_map,
            days_back=days_back,
            max_results_per_query=max_results_per_query,
        )

        # 🎯 최대 건수(기본 5건)로 컷
        capped_docs = all_docs[:max_total_docs]

        # 7개국 그룹으로 분류
        by_country = {
            "CN": [],  # 중국
            "TW": [],  # 대만
            "JP": [],  # 일본
            "KR": [],  # 한국
            "IN": [],  # 인도
            "PK": [],  # 파키스탄
            "US": [],  # 미국 및 글로벌
        }

        for doc in capped_docs:
            c = doc.get("country", "").upper()
            if c in by_country:
                by_country[c].append(doc)
            elif c in ("GLOBAL", "SG", "PH"):
                by_country["US"].append(doc)
            else:
                by_country.setdefault("OTHER", []).append(doc)

        response = {
            "event": event,
            "event_date": event_date,
            "by_country": by_country,
            "total_count": len(capped_docs),
            "all_documents": capped_docs,
        }
        return response

    def collect_multilingual(
        self,
        queries: object,
        days_back: int = 3,
        max_results_per_query: int = 5,
    ) -> List[Dict]:
        """다국어 쿼리(리스트 또는 딕셔너리)를 받아 중복 URL을 제거하고 통합 수집"""
        if isinstance(queries, dict):
            query_items = list(queries.items())
        else:
            query_items = [(f"query_{i+1}", q) for i, q in enumerate(queries)]

        all_docs = []
        seen_urls = set()

        for lang_key, q in query_items:
            print(f"  [>] 검색 중 ({lang_key}): '{q}'...")
            docs = self.collect(
                query=q, days_back=days_back, max_results=max_results_per_query
            )
            for d in docs:
                norm_url = d["url"].split("#")[0].rstrip("/")
                if norm_url not in seen_urls:
                    seen_urls.add(norm_url)
                    all_docs.append(d)

        # 수집 통계 출력
        lang_counts = {}
        tier_counts = {}
        for d in all_docs:
            l = d.get("language", "unknown")
            t = f"Tier {d.get('tier', '?')}"
            lang_counts[l] = lang_counts.get(l, 0) + 1
            tier_counts[t] = tier_counts.get(t, 0) + 1

        lang_str = ", ".join(f"{k}: {v}건" for k, v in sorted(lang_counts.items()))
        tier_str = ", ".join(f"{k}: {v}건" for k, v in sorted(tier_counts.items()))
        print(f"[✓] 다국어 수집 완료: 총 {len(all_docs)}건 고유 문서 확보")
        if all_docs:
            print(f"    - 언어 분포: {lang_str}")
            print(f"    - 티어 분포: {tier_str}")

        return all_docs

    @staticmethod
    def export_json(documents: List[Dict], filepath: str) -> None:
        """수집한 문서 리스트를 팀원 공유용 JSON 파일로 저장"""
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)
        print(f"[💾] 파일 저장 완료: {out_path.resolve()} (총 {len(documents)}개 문서)")

    @staticmethod
    def load_json(filepath: str) -> List[Dict]:
        """저장된 OSINT JSON 파일을 다시 읽어오기"""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
