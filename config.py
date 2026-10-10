"""
OSINT 수집기 설정 및 도메인 티어(Tier) 정의
"""

# 🎯 도메인별 티어, 기본 언어, 국가, 기관명, 기본 신뢰도 가중치
OSINT_WHITELIST = {
    # [Tier 1] 역내 제3국 및 공식 감시·국방 기관 (가장 객관적인 레이더/공식 감시 팩트 -> 가중치 0.95 최고점)
    "mod.go.jp": {
        "tier": 1, "country": "JP", "language": "ja", "category": "neutral_observer",
        "name": "Japan MoD / Joint Staff", "weight": 0.95
    },
    "mnd.go.kr": {
        "tier": 1, "country": "KR", "language": "ko", "category": "neutral_observer",
        "name": "Korea MND", "weight": 0.95
    },
    "jcs.mil.kr": {
        "tier": 1, "country": "KR", "language": "ko", "category": "neutral_observer",
        "name": "Korea JCS (합동참모본부)", "weight": 0.95
    },
    "coastguard.gov.ph": {
        "tier": 1, "country": "PH", "language": "en", "category": "neutral_observer",
        "name": "Philippine Coast Guard", "weight": 0.95
    },
    "defense.gov": {
        "tier": 1, "country": "US", "language": "en", "category": "neutral_observer",
        "name": "US DoD (미 국방부)", "weight": 0.95
    },

    # [Tier 2] 당사국 공식 발표 (공식성은 높으나 자국 유리 왜곡·일방 주장 가능성 감안 -> 가중치 0.85)
    "mnd.gov.tw": {
        "tier": 2, "country": "TW", "language": "zh", "category": "party_official",
        "name": "Taiwan MND", "weight": 0.85
    },
    "mod.gov.cn": {
        "tier": 2, "country": "CN", "language": "zh", "category": "party_official",
        "name": "China MoD", "weight": 0.85
    },
    "ccg.gov.cn": {
        "tier": 2, "country": "CN", "language": "zh", "category": "party_official",
        "name": "China Coast Guard", "weight": 0.85
    },

    # [Tier 3] 공신력 있는 역내/글로벌 팩트 언론 (취재 기반 2차 보도 -> 가중치 0.75)
    "yna.co.kr": {
        "tier": 3, "country": "KR", "language": "ko", "category": "reputable_media",
        "name": "Yonhap News (연합뉴스)", "weight": 0.75
    },
    "channelnewsasia.com": {
        "tier": 3, "country": "SG", "language": "en", "category": "reputable_media",
        "name": "CNA Singapore", "weight": 0.75
    },
    "kyodonews.net": {
        "tier": 3, "country": "JP", "language": "ja", "category": "reputable_media",
        "name": "Kyodo News", "weight": 0.75
    },
    "nhk.or.jp": {
        "tier": 3, "country": "JP", "language": "ja", "category": "reputable_media",
        "name": "NHK World", "weight": 0.75
    },
    "reuters.com": {
        "tier": 3, "country": "GLOBAL", "language": "en", "category": "reputable_media",
        "name": "Reuters", "weight": 0.75
    },
    "apnews.com": {
        "tier": 3, "country": "US", "language": "en", "category": "reputable_media",
        "name": "AP News", "weight": 0.75
    }
}

# 🔄 다국어 재인용(Circular Reporting) 감지 정규식 패턴 (영어, 중국어, 일본어, 한국어)
QUOTE_PATTERNS = [
    r'according to\s+([A-Za-z0-9\s]+?)(?:,|\.|\s+that|\s+on)',  # according to Reuters, according to Taiwan MND
    r'citing\s+([A-Za-z0-9\s]+?)(?:,|\.|\s+that|\s+on)',        # citing Kyodo News
    r'据(.*?)报道',                                              # 据路透社报道 (중국어: ~보도에 따르면)
    r'根据(.*?)(?:消息|表示|发布)',                              # 根据台湾国防部表示 (중국어: ~에 따르면)
    r'(.*?)によると',                                            # ロイターによると (일본어: ~에 따르면)
    r'(.*?)を引用し',                                            # ~를 인용하여
    r'(.*?)(?:에 따르면|를 인용해|의 발표에)'                       # 한국어: ~에 따르면
]

# 텍스트 및 파싱 제한 상수
MAX_RAW_CHARS = 4000          # 1개 문서당 최대 본문 길이 (토큰 및 비용 절약)
MAX_PARAGRAPH_CHARS = 400     # 1개 문단 최대 글자 수 (LLM 문맥 크기 최적화)
MIN_PARAGRAPH_CHARS = 15      # 너무 짧은 무의미한 줄 제거 기준
