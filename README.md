# 🛡️ KoreanDefense / frame - 안보 OSINT 수집 및 검증 프레임워크

이 저장소(`frame`)는 **해커톤 Track T2-1 (Fusion OSINT Copilot)**의 **데이터 수집 및 전처리 파이프라인** 모듈입니다.
기존 베이스라인 코드에 종속되지 않는 독립 모듈로 개발되었으며, 팀원(신엽님, 나현님, 다슬님)의 분석 엔진 및 오케스트레이터와 유기적으로 연동됩니다.

---

## 📁 파일 구성

| 파일명 | 역할 | 설명 |
| :--- | :--- | :--- |
| `config.py` | **설정 및 도메인 티어 정의** | 7개국 화이트리스트 도메인(Tier 1~3), 언어 매핑, 신뢰도 가중치, 순환 보고 방어 정규식 |
| `schemas.py` | **데이터 스키마 정의** | Pydantic 기반 표준 데이터 규격 (`DocumentData`, `ParagraphData`, `SearchPlanRequest`) |
| `collector.py` | **핵심 수집 엔진 (`OSINTCollector`)** | Tavily 연동, 한국어 질문 -> 7개국 자동 확장, **국가별 최대 5건 캡**, 언어 판별, 티어 태깅, 순환 보고 감지, 문단 분할 |
| `demo_run.py` | **검증 및 데모 실행 스크립트** | 모의 데이터 테스트 및 실제 Tavily 기반 7개국 라이브 수집 단일 실행 검증 스크립트 |

---

## 🌐 핵심 기능: 한국어 질문 1개 -> 7대 안보 행위자 자동 변환 & 국가별 5건 선별

질문이 한국어로 들어오면, 내부에서 7대 주요 안보 행위자 언어/관점별 전용 쿼리로 자동 변환하여 수집합니다:

- **중국 (CN)**: 중국 국방부, 신화통신, 해경 (중문 간체 쿼리)
- **대만 (TW)**: 대만 국방부, 중앙통신사 (중문 번체 쿼리)
- **일본 (JP)**: 일본 방위성/통합막료감부, 교도통신, NHK (일본어 쿼리)
- **한국 (KR)**: 대한민국 국방부, 합동참모본부, 연합뉴스 (한국어 쿼리)
- **인도 (IN)**: 인도 국방부, PIB 공보국, The Hindu (영어 쿼리)
- **파키스탄 (PK)**: 파키스탄 군 홍보원(ISPR), Dawn (영어 쿼리)
- **미국/글로벌 (US)**: 미 국방부(DoD), 로이터, AP (영어 쿼리)

### 🎯 국가별 균등 수집 (`max_docs_per_country = 5`)
- 전체 문서 일괄 슬라이스로 인해 특정 국가가 선점하여 다른 국가가 0건으로 누락되는 문제를 원천 차단.
- **각 국가(CN, TW, JP, KR, IN, PK, US)마다 최대 5건**씩 균등 선별하여 그룹화(`by_country`) 및 통합 리스트(`all_documents`)로 제공합니다.

---

## 🏛️ 7개국 출처 티어(Tier) 체계 및 가중치

국방·안보 OSINT에서는 **"누가 말했는가"**에 따라 신뢰도와 성격이 완전히 달라집니다. 수집기에서 각 문서에 아래 메타데이터를 자동으로 부착합니다.

| Tier | 분류명 | 포함 도메인 | 기본 언어 | 가중치 | 역할 및 성격 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **Tier 1** | **역내 제3국 및 공식 감시기구**<br>(Regional Observers) | `mod.go.jp` (일본 방위성·레이더 항적)<br>`mnd.go.kr` (한국 국방부)<br>`jcs.mil.kr` (한국 합동참모본부)<br>`coastguard.gov.ph` (필리핀 해경)<br>`defense.gov` (미 국방부) | `ja`<br>`ko`<br>`en` | **`0.95`** | **최고 신뢰도 (1순위)!** 직접 이해관계가 배제된 제3국이 레이더/초계기로 직접 확인한 객관적 물리 팩트. |
| **Tier 2** | **당사국 공식 발표**<br>(Primary Parties) | `mnd.gov.tw` (대만 국방부)<br>`mod.gov.cn` (중국 국방부)<br>`ccg.gov.cn` (중국 해경)<br>`news.cn` (신화통신 관영)<br>`mod.gov.in` (인도 국방부)<br>`pib.gov.in` (인도 정부 공보국)<br>`ispr.gov.pk` (파키스탄 군 홍보원) | `zh`<br>`en` | **`0.85`** | **공식 2순위**. 공식성은 높으나 자국에 유리하게 왜곡/선전(Propaganda)·일방 주장 가능성 감안. |
| **Tier 3** | **공신력 검증 언론**<br>(Reputable Media) | `yna.co.kr` (한국 연합뉴스)<br>`cna.com.tw` (대만 중앙통신사)<br>`kyodonews.net` (일본 교도통신)<br>`nhk.or.jp` (일본 NHK)<br>`thehindu.com` (인도 The Hindu)<br>`dawn.com` (파키스탄 Dawn)<br>`channelnewsasia.com` (싱가포르 CNA)<br>`reuters.com` (로이터 통신)<br>`apnews.com` (AP 통신) | `ko`<br>`zh`<br>`ja`<br>`en` | **`0.75`** | **취재 3순위**. 신속한 팩트 보도. 사건 발생 개요 파악 및 2차 교차 보도 확인. |

---

## 🔄 순환 보고(Circular Reporting / 재인용) 방어 메커니즘

- **감지 로직**: 본문 초반에서 다국어 인용 구절(`according to...`, `据...报道`, `~によると`, `~에 따르면`)을 자동 감지하여 `quoted_source` 필드에 인용 주체를 기록하고 `is_reprint_likely: True`를 마킹합니다.
- **분석단 활용**: 동일한 원천(예: "Taiwan MND")을 단순 전재한 기사들이 다수 있더라도 1개의 단일 출처 클러스터로 묶어 가짜 일치(Corroboration Illusion)로 인한 점수 거품을 방지합니다.

---

## 🤝 팀원 연동 규격 (최종 산출물 JSON 포맷)

```json
{
  "korean_question": "대만해협 군사활동",
  "event_date": "2026-10-01",
  "generated_queries": {
    "CN": "2026-10-01 台湾海峡 解放军 演习 战备警巡 东部战区 军机",
    "TW": "2026-10-01 台灣海峽 國防部 共機 越過中線 演習",
    "JP": "2026-10-01 台湾海峡 中国軍機 演習 防衛省 統合幕僚監部",
    "KR": "2026-10-01 대만해협 군사활동 국방부 군용기 동향",
    "IN": "2026-10-01 Taiwan Strait PLA military aircraft exercise China Taiwan",
    "PK": "2026-10-01 Taiwan Strait military activity China Taiwan tension",
    "US": "2026-10-01 Taiwan Strait PLA military exercises median line DoD"
  },
  "by_country": {
    "CN": [ /* 중국 문서 최대 5건 */ ],
    "TW": [ /* 대만 문서 최대 5건 */ ],
    "JP": [ /* 일본 문서 최대 5건 */ ],
    "KR": [ /* 한국 문서 최대 5건 */ ],
    "IN": [ /* 인도 문서 최대 5건 */ ],
    "PK": [ /* 파키스탄 문서 최대 5건 */ ],
    "US": [ /* 미국/글로벌 문서 최대 5건 */ ]
  },
  "total_count": 24,
  "all_documents": [ /* 전체 수집 문서 리스트 */ ]
}
```

각 개별 문서는 아래 메타데이터 규격을 준수합니다:

```json
{
  "doc_id": "doc_a1b2c3d4",
  "url": "https://www.mod.go.jp/j/press/news/2026/10/10a.html",
  "title": "中国海軍艦艇の動向について",
  "language": "ja",
  "tier": 1,
  "source_name": "Japan MoD / Joint Staff",
  "country": "JP",
  "source_category": "neutral_observer",
  "credibility_weight": 0.95,
  "is_reprint_likely": false,
  "quoted_source": null,
  "query": "2026-10-01 台湾海峡 中国軍機 演習 防衛省 統合幕僚監部",
  "published_date": "2026-10-10",
  "event_date": null,
  "status": "success_full",
  "paragraphs": [
    {
      "paragraph_id": "doc_a1b2c3d4_p1",
      "raw_text": "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。"
    }
  ]
}
```

---

## 🚀 빠른 테스트 방법

```bash
cd c:\KoreanDefense\frame
python demo_run.py
```
- `.env` 파일에 `TAVILY_API_KEY=tvly-...` 설정 시 실제 7개국 라이브 수집 모드로 즉시 동작합니다.
