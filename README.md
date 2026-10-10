# 🛡️ KoreanDefense / frame - 안보 OSINT 수집 및 검증 프레임워크

이 폴더(`frame`)는 **해커톤 Track T2-1 (Fusion OSINT Copilot)**의 **데이터 수집 및 전처리 파이프라인**을 독립적으로 개발하고 테스트하기 위해 만들어진 모듈입니다.

기존 코드베이스에 구애받지 않고, 우리 팀(기찬, 신엽, 나현, 다슬)의 설계 철학과 나현님이 정의한 엄격한 검증 규격에 맞춰 제작되었습니다.

---

## 📁 파일 구성 및 역할

| 파일명 | 역할 | 설명 |
| :--- | :--- | :--- |
| `config.py` | **설정 및 도메인 티어 정의** | 화이트리스트 도메인(Tier 1~3), 언어 매핑, 신뢰도 가중치, 다국어 재인용 감지 정규식 |
| `schemas.py` | **데이터 스키마 정의** | Pydantic 기반의 문서 및 문단 표준 데이터 규격 (`DocumentData`, `ParagraphData`) |
| `collector.py` | **핵심 수집 엔진 (`OSINTCollector`)** | Tavily API 검색, 내장 `.env` 로더, 언어 자동 판별, 티어 자동 태깅, 재인용 감지, 안전한 문단 분할, 다국어 중복 제거, JSON 내보내기/불러오기 |
| `demo_run.py` | **실행 및 검증 스크립트** | 로컬 환경에서 단독으로 수집 데이터 구조를 검증할 수 있는 테스트 스크립트 |

---

## 🌟 주요 기능 및 실전 편의 요소

1. **경량 내장 `.env` 로더**:
   - `python-dotenv` 같은 외부 패키지 설치 없이도, 폴더 내 `.env` 파일(`TAVILY_API_KEY=tvly-...`)을 자동으로 읽어옵니다.
2. **다국어 언어 자동 태그 (`language`)**:
   - 도메인 메타데이터 및 본문 문자 분포를 분석하여 `zh`(중국어), `ja`(일본어), `ko`(한국어), `en`(영어)를 자동 판별해 부착합니다.
   - 뒷단에서 LLM 프롬프트를 처리할 때 언어별 분기가 매우 쉬워집니다.
3. **JSON 파일 내보내기/불러오기 도우미**:
   - `collector.export_json(results, "output.json")`: 수집된 대량의 기사 데이터를 즉시 파일로 저장해 팀원들에게 전달 가능.
   - `collector.load_json("output.json")`: 저장된 JSON을 뒷단 파이프라인에서 바로 로드.

---

## 🏛️ 출처 티어(Tier) 체계 및 가중치

국방·안보 OSINT에서는 **"누가 말했는가"**에 따라 신뢰도와 성격이 완전히 달라집니다. 수집기에서부터 각 문서에 아래 메타데이터를 자동으로 부착합니다.

| Tier | 분류명 | 포함 도메인 | 기본 언어 | 가중치 | 역할 및 성격 |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **Tier 1** | **당사국 공식 발표**<br>(Primary Parties) | `mnd.gov.tw` (대만 국방부)<br>`mod.gov.cn` (중국 국방부)<br>`ccg.gov.cn` (중국 해경) | `zh` | `0.85` | **1차 공식 발표**. 공식성은 최고이나 자국에 유리한 왜곡/선전(Propaganda) 가능성 감안. |
| **Tier 2** | **역내 제3국 감시기구**<br>(Regional Observers) | `mod.go.jp` (일본 방위성·레이더 항적)<br>`coastguard.gov.ph` (필리핀 해경)<br>`mnd.go.kr` (한국 국방부) | `ja` / `en` / `ko` | `0.95` | **최고 가산점 대상!** 당사자가 아니므로 가장 객관적인 레이더/항적 교차검증 근거 제공. |
| **Tier 3** | **공신력 검증 언론**<br>(Reputable Media) | `channelnewsasia.com` (싱가포르 CNA)<br>`kyodonews.net` (일본 교도통신)<br>`nhk.or.jp` (일본 NHK)<br>`reuters.com` (로이터) | `en` / `ja` | `0.75` | **신속한 팩트 보도**. 사건 발생 개요 파악 및 교차 보도 확인. |

---

## 🔄 순환 보고(Circular Reporting / 재인용) 방어 메커니즘

### 문제 상황
로이터 통신의 한 줄 보도를 여러 언론사(교도통신, CNA 등)가 단순히 재인용하여 받아쓴 경우, 알고리즘이 "여러 언론이 일치했으니 신뢰도 99%다!"라고 잘못 판단하는 **가짜 일치(Corroboration Illusion)** 현상이 발생합니다.

### 우리 프레임워크의 해결책
1. **수집기 (`collector.py`)**:
   - 본문 초반에서 다국어 패턴(`according to...`, `据...报道`, `~によると`, `~에 따르면`)을 감지하여 `quoted_source` 필드에 인용된 원천을 기록합니다.
   - `is_reprint_likely: True` 태그 부여.
2. **뒷단 검증단 (신엽님/나현님)**:
   - 기사가 여러 건이어도 `quoted_source`가 동일한 원천(예: "Taiwan MND")이면, **1개의 단일 출처 클러스터**로 묶어 점수 거품을 제거합니다.
   - **서로 다른 독립된 원천(예: 대만 국방부 성명 + 일본 방위성 레이더)**이 일치할 때만 최고 교차검증 점수를 부여합니다.

---

## 🤝 팀원 연동 규격 (최종 산출물 JSON 포맷)

앞단(Orchestrator)이 다국어 쿼리를 넘겨주면, 수집기는 뒷단(검증/LLM)에 아래 규격의 리스트(`List[Dict]`)를 전달합니다:

```json
{
  "doc_id": "doc_a1b2c3d4",
  "url": "https://www.mod.go.jp/j/press/news/2026/10/10a.html",
  "title": "中国海軍艦艇の動向について",
  "language": "ja",
  
  "tier": 2,
  "source_name": "Japan MoD / Joint Staff",
  "country": "JP",
  "source_category": "neutral_observer",
  "credibility_weight": 0.95,
  
  "is_reprint_likely": false,
  "quoted_source": null,
  
  "published_date": "2026-10-10",
  "event_date": null,
  "status": "success_full",
  
  "paragraphs": [
    {
      "paragraph_id": "doc_a1b2c3d4_p1",
      "raw_text": "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。"
    },
    {
      "paragraph_id": "doc_a1b2c3d4_p2",
      "raw_text": "自衛隊は哨戒機及び護衛艦により所要の情報収集と警戒監視を実施した。"
    }
  ]
}
```

- **`language`**: 원문 언어 코드 (`zh`, `ja`, `ko`, `en`).
- **`event_date: null`**: 나현님 요구사항대로 사건일은 수집단에서 절대 임의로 채우지 않으며, 뒷단 LLM이 본문 문맥을 읽고 채웁니다.
- **`paragraph_id`**: LLM이 최종 보고서를 쓸 때 핀포인트 인용(`Citation`)할 수 있도록 모든 문단에 고유 ID를 부여합니다.

---

## 🚀 빠른 테스트 방법

터미널에서 아래 명령어로 즉시 테스트할 수 있습니다:

```bash
cd c:\KoreanDefense\frame
python demo_run.py
```
