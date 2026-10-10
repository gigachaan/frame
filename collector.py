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
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

from config import (
    OSINT_WHITELIST,
    COUNTRY_DOMAINS,
    QUOTE_PATTERNS,
    MAX_RAW_CHARS,
    MAX_PARAGRAPH_CHARS,
    MIN_PARAGRAPH_CHARS,
    DEFENSE_LEXICON,
    DEFAULT_MIN_SCORE,
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
            # 이미지 마크다운 잔여물이나 단순 링크 라인 제거
            if re.match(r'^!\[.*?\]\(.*?\)$', piece) or re.match(r'^\[.*?\]\(.*?\)$', piece):
                continue
            if len(piece) < MIN_PARAGRAPH_CHARS:
                continue

            for i in range(0, len(piece), MAX_PARAGRAPH_CHARS):
                chunk = piece[i : i + MAX_PARAGRAPH_CHARS].strip()
                if chunk:
                    paragraphs.append(chunk)

        if not paragraphs and text.strip():
            fallback = text[:MAX_PARAGRAPH_CHARS].strip()
            if len(fallback) >= MIN_PARAGRAPH_CHARS:
                paragraphs = [fallback]

        return paragraphs

    def _is_article_url(self, url: str) -> bool:
        """
        기사/보도자료 상세 본문 페이지가 아닌 사이트 메인, 인덱스, 카테고리, 목차, 페이징 URL을 필터링하여 제외
        """
        if not url:
            return False
        parsed = urlparse(url)
        path = parsed.path.lower().rstrip('/')
        query = parsed.query.lower()

        # 1. 도메인 메인 홈페이지만 있는 경우 (/ 또는 /index.html 등)
        if not path or path in ('', '/index.html', '/index.htm', '/home', '/default.aspx', '/index'):
            return False

        # 2. 인덱스/페이징/카테고리/목록/색인 패턴 차단
        blacklist_patterns = [
            r'/index(_\d+)?\.(html?|php|jsp|aspx?)$',  # index.html, index_4.html 등
            r'pageindex=\d+',                          # 페이징 파라미터
            r'/overview(\.html?|\.aspx?)?$',           # 목록 개요 페이지
            r'/sitemap',                               # 사이트맵
            r'/wzdt_',                                 # 사이트맵(중국어)
            r'sakuin\.pdf$',                           # 50음도 색인 pdf
            r'/category/',                             # 카테고리
            r'/channel/',                              # 채널
            r'/tag/',                                  # 태그 목록
            r'/topic/',                                # 토픽 목록
        ]
        for pat in blacklist_patterns:
            if re.search(pat, path) or re.search(pat, query):
                return False

        return True

    def _clean_content(self, text: str) -> tuple:
        """
        HTML 태그 및 마크다운 내비게이션/이미지/보일러플레이트 요소를 완전 제거하여
        기사의 순수 본문 텍스트만 추출하고, 제거된 블록 유형 목록을 반환
        """
        if not text or not text.strip():
            return "", []

        cleaned = text
        removed_blocks = []

        # 1. HTML 형식일 경우 BeautifulSoup으로 1차 정제
        if "<html" in cleaned.lower() or "<body" in cleaned.lower() or "<div" in cleaned.lower() or "<p" in cleaned.lower():
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(cleaned, "html.parser")

                has_boilerplate_tags = bool(soup.find_all(["script", "style", "nav", "header", "footer", "aside"]))
                for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "iframe", "svg"]):
                    tag.decompose()
                if has_boilerplate_tags:
                    removed_blocks.append("내비게이션/헤더/푸터 태그")

                has_img = bool(soup.find_all(["img", "picture", "figure"]))
                for tag in soup(["img", "picture", "figure"]):
                    tag.decompose()
                if has_img:
                    removed_blocks.append("광고/이미지 태그")

                best_tag = soup.body if soup.body else soup
                articles = soup.find_all("article")
                if articles:
                    best_tag = max(articles, key=lambda a: len(a.get_text(strip=True)))
                else:
                    mains = soup.find_all(["main", "div", "section"])
                    valid_mains = []
                    for m in mains:
                        cls = m.get("class", [])
                        if not isinstance(cls, list):
                            cls = [cls]
                        attrs = str(m.get("id", "")) + " " + " ".join(cls)
                        if any(x in attrs.lower() for x in ["content", "article", "main", "body", "news", "post"]):
                            valid_mains.append(m)
                    if valid_mains:
                        best_tag = max(valid_mains, key=lambda m: len(m.get_text(strip=True)))

                cleaned = best_tag.get_text(separator="\n")
            except Exception:
                pass

        # 2. 마크다운 및 텍스트 수준의 보일러플레이트 정제 (Tavily raw_content 마크다운 대응)
        cleaned = re.sub(r'<script.*?>.*?</script>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<style.*?>.*?</style>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<[^>]+>', ' ', cleaned)

        # 마크다운 이미지 완전 제거 (![...](...) 및 [![...](...)](...))
        if re.search(r'!\[.*?\]\(.*?\)', cleaned):
            removed_blocks.append("마크다운 이미지 블록")
        cleaned = re.sub(r'\[!\[.*?\]\(.*?\)\]\(.*?\)', '', cleaned)
        cleaned = re.sub(r'!\[.*?\]\(.*?\)', '', cleaned)

        # 마크다운 메뉴 목록 제거 (예: `* [메뉴](링크)`, `+ [메뉴](링크)`)
        if re.search(r'^\s*[\*\+\-]\s*\[.*?\]\(.*?\)\s*$', cleaned, flags=re.MULTILINE):
            removed_blocks.append("메뉴/링크 목록")
        cleaned = re.sub(r'^\s*[\*\+\-]\s*\[.*?\]\(.*?\)\s*$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\[.*?\]\(#[^\)]*\)', '', cleaned)

        # 3. 사이트 내비게이션/헤더/푸터 보일러플레이트 키워드 필터링
        boilerplate_kws = [
            '본문 바로가기', '메뉴 바로가기', '기사제보', '저작권자', 'all rights reserved',
            'copyright', 'epaper', 'live tv', 'gift a subscription', 'you are logged in',
            'english', '繁體版', '网站地图', '跳到中央內容區塊', '點這裡瞭解', 'privacy statement',
            '本網站使用相關技術', 'share this article', 'follow us on', 'subscribe to',
            'active subscription', '구독하기', '추천 기사', '관련 기사 목록'
        ]

        clean_lines = []
        for line in cleaned.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            lower_line = line_str.lower()
            # 90자 미만의 짧은 안내 배너/링크 줄인 경우에만 정제 (기사 본문 문장은 안전 보존)
            if len(line_str) < 90 and any(kw in lower_line for kw in boilerplate_kws):
                removed_blocks.append("구독/광고/안내 배너")
                continue
            # 순수 마크다운 링크 또는 브레드크럼(경로 이동)만 나열된 줄 스킵
            if re.match(r'^(\s*(\[.*?\]\(.*?\)|[>/»›\|·\-])\s*)+(/정문|/正文|/)?$', line_str):
                removed_blocks.append("경로 탐색(브레드크럼)")
                continue
            if re.match(r'^(\s*\[.*?\]\(.*?\)\s*)+$', line_str):
                removed_blocks.append("단독 링크 나열 줄")
                continue
            clean_lines.append(line_str)

        unique_removed = sorted(list(set(removed_blocks)))
        return "\n\n".join(clean_lines), unique_removed

    def collect(
        self,
        query: str,
        days_back: int = 3,
        max_results: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        include_domains: Optional[List[str]] = None,
    ) -> List[Dict]:
        """단일 검색어로 Tavily를 검색하고 규격화된 문서 딕셔너리 리스트 반환 (인덱스 제외 및 본문 정제)"""
        if self.client is None:
            print("[-] Tavily 클라이언트가 준비되지 않았습니다. TAVILY_API_KEY 확인 또는 pip install tavily-python 필요")
            return []

        time_range = "day" if days_back <= 1 else "week" if days_back <= 7 else "month"
        domains_to_use = include_domains if include_domains is not None else self.allowed_domains

        fetch_count = min(max_results * 2, 10)
        try:
            response = self.client.search(
                query=query,
                search_depth="advanced",
                include_domains=domains_to_use,
                time_range=time_range,
                include_raw_content=True,
                max_results=fetch_count,
            )
        except Exception as e:
            print(f"[-] Tavily 검색 실패 (Query: '{query}'): {e}")
            return []

        processed_candidates = []
        for item in response.get("results", []):
            url = item.get("url", "")
            # 1. 인덱스/홈페이지/목록 페이지 배제
            if not self._is_article_url(url):
                continue

            score = round(float(item.get("score") or 0.0), 4)

            # 원본 보존 (나현님 요청: raw_content)
            raw_text = item.get("raw_content") or item.get("content") or ""
            cleaned_text, removed_blocks = self._clean_content(raw_text)

            # 내용이 부족하면 Tavily의 content 필드로 폴백 정제
            if len(cleaned_text.strip()) < 80 and item.get("content"):
                alt_cleaned, alt_blocks = self._clean_content(item.get("content"))
                if len(alt_cleaned) > len(cleaned_text):
                    cleaned_text = alt_cleaned
                    removed_blocks = sorted(list(set(removed_blocks + alt_blocks)))

            if len(cleaned_text.strip()) < 40:
                continue

            tier_info = self._resolve_tier_meta(url)
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"
            language = self._detect_language(url, cleaned_text)

            is_truncated = len(cleaned_text) > MAX_RAW_CHARS
            status = "success_truncated" if is_truncated else "success_full"

            clipped_text = cleaned_text[:MAX_RAW_CHARS]
            paragraphs_text = self._split_into_paragraphs(clipped_text)
            if not paragraphs_text:
                continue
            quoted_source = self._extract_attribution_hint(clipped_text)

            # 수동 검토 필요 여부 판별 (needs_review)
            paywall_keywords = ["subscribe to read", "active subscription", "로그인 후", "구독회원 전용", "有料会員"]
            is_paywall_likely = any(pw in raw_text.lower() for pw in paywall_keywords) and len(cleaned_text) < 400
            needs_review = bool(len(cleaned_text) < 200 or is_paywall_likely)

            doc_entry = {
                "doc_id": doc_id,
                "url": url,
                "title": item.get("title", ""),
                "score": score,  # 🎯 [Tavily score 검색 관련도 점수]
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

                # 📦 [나현님 요청 신규 스펙: 원본 보존 및 정제 텍스트]
                "raw_content": raw_text[:MAX_RAW_CHARS],  # 원본 보존 (검토/대조용)
                "article_text": cleaned_text,             # 광고·구독·메뉴 제거된 순수 기사 본문
                "cleaning": {
                    "removed_blocks": removed_blocks,
                    "needs_review": needs_review,
                },

                # 📑 [문단 단위 목록 (Ollama 입력용)]
                "paragraphs": [
                    {
                        "paragraph_id": f"{doc_id}_p{idx + 1}",
                        "raw_text": p_text,
                        "id": f"{doc_id}_p{idx + 1}",  # 나현님 id 필드 호환
                        "text": p_text,                # 나현님 text 필드 호환
                    }
                    for idx, p_text in enumerate(paragraphs_text)
                ],
            }
            processed_candidates.append(doc_entry)

        # 🎯 min_score (기본 0.7) 필터링 및 선별
        # 1차: min_score(0.7) 이상인 고관련도 문서 선별
        primary_docs = [d for d in processed_candidates if d.get("score", 0.0) >= min_score]
        
        if strict_min_score:
            return primary_docs[:max_results]

        # strict 모드가 아닐 때: 0.7 이상 문서 우선 채택 후, 부족 시 타깃 도메인 내 최고점 순으로 보충
        documents = primary_docs[:max_results]
        if len(documents) < max_results:
            remaining = [d for d in processed_candidates if d not in documents]
            # score 내림차순 정렬
            remaining.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            for d in remaining:
                if len(documents) >= max_results:
                    break
                d["cleaning"]["score_notice"] = f"기본 임계값(0.7) 미만이나 도메인 내 최고 관련도(score: {d.get('score')})로 선별됨"
                documents.append(d)

        return documents

    def _translate_to_actor_query(self, question: str, target: str) -> str:
        """한국어 질문 문장을 대상 국가/언어(KR, CN, TW, JP, EN)에 맞게 1:1 자연 번역"""
        if target == "KR":
            # 🇰🇷 한국어 질문은 인위적인 수식어/키워드 추가 없이 질문 원문 그대로 깨끗하게 전달
            return question.strip()

        target_lang = "EN" if target in ("US", "IN", "PK") else target

        # 한국어 조사 및 불필요 문장 어미 정리
        cleaned = question
        particles = [
            r'은\b', r'는\b', r'이\b', r'가\b', r'을\b', r'를\b', r'의\b',
            r'에\b', r'에서\b', r'에\s*대한\b', r'내역은\b', r'있나요\b',
            r'알려줘\b', r'어떻게\s*되나요\b', r'어떤가요\b', r'\?'
        ]
        for p in particles:
            cleaned = re.sub(p, ' ', cleaned)

        # 긴 구문부터 우선 치환
        sorted_lexicon = sorted(DEFENSE_LEXICON, key=lambda x: len(x[0]), reverse=True)
        translated = cleaned
        for phrase, trans_map in sorted_lexicon:
            if phrase in translated:
                replacement = trans_map.get(target_lang, trans_map.get("EN", phrase))
                translated = translated.replace(phrase, f" {replacement} ")

        # 공백 정리
        final_query = " ".join(translated.split())
        return final_query if final_query else question.strip()

    def _expand_korean_to_7_actors(self, question: str, event_date: Optional[str] = None) -> Dict[str, str]:
        """
        한국어 질문 문장 1개를 받아 7개 안보 행위자
        (중국 CN, 대만 TW, 일본 JP, 한국 KR, 인도 IN, 파키스탄 PK, 미국 US)별 맞춤형 쿼리로 1:1 직역/변환
        - 인위적인 키워드 샐러드 없이 사용자의 질문 의도를 정확하고 깨끗하게 반영
        """
        clean_q = question.strip()
        queries = {
            "KR": self._translate_to_actor_query(clean_q, "KR"),
            "CN": self._translate_to_actor_query(clean_q, "CN"),
            "TW": self._translate_to_actor_query(clean_q, "TW"),
            "JP": self._translate_to_actor_query(clean_q, "JP"),
            "US": self._translate_to_actor_query(clean_q, "US"),
            "IN": self._translate_to_actor_query(clean_q, "IN"),
            "PK": self._translate_to_actor_query(clean_q, "PK"),
        }
        return queries

    def collect_from_korean(
        self,
        question: str,
        event_date: Optional[str] = None,
        max_docs_per_country: int = 5,
        days_back: int = 30,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        **kwargs,
    ) -> Dict:
        """
        [핵심 함수] 한국어 질문 1개만 입력받아:
        1. 7대 주요 안보 행위자(중국 CN, 대만 TW, 일본 JP, 한국 KR, 인도 IN, 파키스탄 PK, 미국 US)별 전용 맞춤 쿼리로 1:1 직역/변환
        2. 화이트리스트 기반 Tavily 다국어 수집
        3. 🎯 각 국가별로 최대 5건(max_docs_per_country)씩 선별하여 7개국 그룹으로 반환
        """
        # 하위 호환성 지원 (max_total_docs 전달 시 max_docs_per_country로 매핑)
        if "max_total_docs" in kwargs and kwargs["max_total_docs"] is not None:
            max_docs_per_country = kwargs["max_total_docs"]

        print(f"\n[🌐] 한국어 질문 감지: '{question}' (일자: {event_date or '전체'})")
        print(f"[+] 7개국(중국, 대만, 일본, 한국, 인도, 파키스탄, 미국) 맞춤 쿼리 1:1 변환 및 국가별 최대 {max_docs_per_country}건 수집 시작...")

        query_map = self._expand_korean_to_7_actors(question, event_date)
        for country_key, q in query_map.items():
            print(f"  - [{country_key}] 쿼리: '{q}'")

        # 7개국별 문서 버킷 초기화 (나라별로 묶어 관리)
        by_country = {
            "CN": [],  # 중국
            "TW": [],  # 대만
            "JP": [],  # 일본
            "KR": [],  # 한국
            "IN": [],  # 인도
            "PK": [],  # 파키스탄
            "US": [],  # 미국 / 글로벌
        }

        seen_urls = set()

        for country_key, q in query_map.items():
            print(f"  [>] 검색 중 ({country_key}): '{q}'...")
            target_domains = COUNTRY_DOMAINS.get(country_key, self.allowed_domains)
            docs = self.collect(
                query=q,
                days_back=days_back,
                max_results=max_docs_per_country,
                min_score=min_score,
                strict_min_score=strict_min_score,
                include_domains=target_domains,
            )
            for d in docs:
                norm_url = d["url"].split("#")[0].rstrip("/")
                if norm_url in seen_urls:
                    continue
                seen_urls.add(norm_url)

                if d.get("country") in ("UNKNOWN", "GLOBAL") and country_key != "US":
                    d["target_actor"] = country_key

                if len(by_country[country_key]) < max_docs_per_country:
                    by_country[country_key].append(d)

        # 전체 수집 문서 합산 (각 국가별 최대 max_docs_per_country 건)
        all_documents = []
        for c_key, c_docs in by_country.items():
            all_documents.extend(c_docs)

        print(f"\n[🔒] 국가별 최대 {max_docs_per_country}건 선별 완료 (총 {len(all_documents)}건):")
        for c_code, docs in by_country.items():
            print(f"  - [{c_code}] {len(docs)}건 / 최대 {max_docs_per_country}건")

        return {
            "by_country": by_country,
            "korean_question": question,
            "event_date": event_date,
            "generated_queries": query_map,
            "total_count": len(all_documents),
            "all_documents": all_documents,
            **by_country,  # result["CN"], result["TW"] 등 국가 코드로도 직관적으로 바로 접근 가능
        }

    def collect_plan(
        self,
        plan: dict,
        days_back: int = 7,
        max_docs_per_country: int = 5,
        max_results_per_query: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
        **kwargs,
    ) -> Dict:
        """
        앞단(Orchestrator/나현님)의 요청 포맷(event, event_date, queries)을 받아 수집하고,
        중국, 대만, 일본, 한국, 인도, 파키스탄, 미국 7개국별로 각각 최대 max_docs_per_country건씩 선별하여 반환합니다.
        """
        if "max_total_docs" in kwargs and kwargs["max_total_docs"] is not None:
            max_docs_per_country = kwargs["max_total_docs"]

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

        # 🇰🇷 한국어 쿼리가 없으면 한국 출처 수집을 위해 자동 보강 (원문 그대로 1:1 추가)
        if "ko" not in query_map and event:
            query_map["ko"] = event.strip()
            print(f"  [+] 한국 출처 수집을 위해 한국어 쿼리 자동 추가: '{query_map['ko']}'")

        # 다국어 수집 실행
        all_docs = self.collect_multilingual(
            queries=query_map,
            days_back=days_back,
            max_results_per_query=max_results_per_query,
            min_score=min_score,
            strict_min_score=strict_min_score,
        )

        # 7개국 그룹으로 분류 (각 국가별 최대 max_docs_per_country건 제한)
        by_country = {
            "CN": [],  # 중국
            "TW": [],  # 대만
            "JP": [],  # 일본
            "KR": [],  # 한국
            "IN": [],  # 인도
            "PK": [],  # 파키스탄
            "US": [],  # 미국 및 글로벌
        }

        for doc in all_docs:
            c = doc.get("country", "").upper()
            if c in by_country:
                target_key = c
            elif c in ("GLOBAL", "SG", "PH"):
                target_key = "US"
            else:
                target_key = "OTHER"

            if target_key in by_country:
                if len(by_country[target_key]) < max_docs_per_country:
                    by_country[target_key].append(doc)
            else:
                by_country.setdefault("OTHER", []).append(doc)

        retained_docs = []
        for c_list in by_country.values():
            retained_docs.extend(c_list)

        print(f"\n[🔒] 플랜 수집 완료: 각 국가별 최대 {max_docs_per_country}건 선별 (총 {len(retained_docs)}건)")
        for c_code, docs in by_country.items():
            print(f"  - [{c_code}] {len(docs)}건 / 최대 {max_docs_per_country}건")

        response = {
            "by_country": by_country,
            "event": event,
            "event_date": event_date,
            "total_count": len(retained_docs),
            "all_documents": retained_docs,
            **by_country,  # result["CN"], result["TW"] 등 국가 코드로도 직관적으로 바로 접근 가능
        }
        return response

    def collect_multilingual(
        self,
        queries: object,
        days_back: int = 3,
        max_results_per_query: int = 5,
        min_score: float = DEFAULT_MIN_SCORE,
        strict_min_score: bool = False,
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
                query=q, days_back=days_back, max_results=max_results_per_query, min_score=min_score, strict_min_score=strict_min_score
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
    def export_json(documents: Union[List[Dict], Dict], filepath: str) -> None:
        """수집한 문서 리스트 또는 응답 딕셔너리를 팀원 공유용 JSON 파일로 저장"""
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(documents, f, indent=2, ensure_ascii=False)
        count = (
            len(documents.get("all_documents", []))
            if isinstance(documents, dict) and "all_documents" in documents
            else len(documents)
        )
        print(f"[💾] 파일 저장 완료: {out_path.resolve()} (총 {count}개 문서)")

        # 상위 디렉토리(루트)에도 동일 파일이 존재하거나 frame 하위에서 실행된 경우 자동 동기화
        try:
            parent_target = out_path.parent.parent / out_path.name
            if parent_target.parent.exists() and parent_target.resolve() != out_path.resolve():
                with open(parent_target, "w", encoding="utf-8") as f:
                    json.dump(documents, f, indent=2, ensure_ascii=False)
                print(f"  [🔄] 루트 디렉토리 동기화 완료: {parent_target.resolve()}")
        except Exception:
            pass

    @staticmethod
    def load_json(filepath: str) -> List[Dict]:
        """저장된 OSINT JSON 파일을 다시 읽어오기"""
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
