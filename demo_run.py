"""
OSINT 수집기 로컬 검증 및 데모 스크립트
실행 방법: python demo_run.py
"""

import json
import os
import sys

# Windows 터미널 한글/특수문자 인코딩 대응
sys.stdout.reconfigure(encoding='utf-8')

from collector import OSINTCollector, TavilyClient

def main():
    print("=" * 65)
    print("🚀 [KoreanDefense/frame] 안보 OSINT 수집 엔진 테스트")
    print("=" * 65)

    api_key = os.getenv("TAVILY_API_KEY")
    if TavilyClient is None or not api_key:
        if TavilyClient is None:
            print("[i] 'tavily-python' 패키지가 미설치 상태입니다.")
        if not api_key:
            print("[i] TAVILY_API_KEY 환경변수(.env)가 설정되지 않았습니다.")
            
        print("\n👉 [모의 데이터 검증 모드] 로직(언어 판별, 티어 분류, 재인용 감지, JSON 저장)을 테스트합니다.\n")
        
        mock_collector = OSINTCollector(api_key="mock_key")
        
        # 샘플 1: 일본 방위성(Tier 2, ja) 발표 (원문 인용 감지 포함)
        sample_url = "https://www.mod.go.jp/j/press/news/2026/10/10a.html"
        sample_text = (
            "According to Taiwan MND reports on earlier movements, the PLA increased presence.\n\n"
            "防衛省統合幕僚監部は、本日午前8時頃、中国海軍の艦艇2隻が台湾海峡周辺を航行したことを確認した。\n"
            "自衛隊は哨戒機及び護衛艦により所要の情報収集と警戒監視を実施した。"
        )
        
        tier_meta = mock_collector._resolve_tier_meta(sample_url)
        lang = mock_collector._detect_language(sample_url, sample_text)
        quoted = mock_collector._extract_attribution_hint(sample_text)
        paragraphs = mock_collector._split_into_paragraphs(sample_text)
        
        mock_output = [
            {
                "doc_id": "doc_sample01",
                "url": sample_url,
                "title": "中国海軍艦艇の動向について (防衛省)",
                "language": lang,
                "tier": tier_meta["tier"],
                "source_name": tier_meta["name"],
                "country": tier_meta["country"],
                "source_category": tier_meta["category"],
                "credibility_weight": tier_meta["weight"],
                "is_reprint_likely": bool(quoted),
                "quoted_source": quoted,
                "published_date": "2026-10-10",
                "event_date": None,
                "status": "success_full",
                "paragraphs": [
                    {"paragraph_id": f"doc_sample01_p{i+1}", "raw_text": p}
                    for i, p in enumerate(paragraphs)
                ]
            }
        ]
        
        print("✅ [테스트 결과 - 최종 규격 JSON]:")
        print(json.dumps(mock_output[0], indent=2, ensure_ascii=False))
        
        # 파일 저장 테스트
        test_file = "sample_output.json"
        mock_collector.export_json(mock_output, test_file)
        print(f"[✓] export_json 테스트 성공: {test_file} 생성됨")
        
        print("\n" + "=" * 65)
        print("💡 안내: .env 파일에 TAVILY_API_KEY=tvly-... 를 적어두시면")
        print("   실제 라이브 웹 검색 모드로 자동 전환됩니다.")
        print("=" * 65)
        return

    # 실제 Tavily API 키가 있을 경우
    print("[+] TAVILY_API_KEY 감지 완료. 실제 웹 검색을 진행합니다.")
    collector = OSINTCollector(api_key=api_key)
    
    test_queries = [
        "Taiwan Strait PLA naval exercise",
        "台湾海峡 東部戦区 演習",
    ]
    
    results = collector.collect_multilingual(test_queries, days_back=7)
    
    print(f"\n[✓] 총 수집 문서 건수: {len(results)}건")
    if results:
        print("\n--- 첫 번째 문서 데이터 샘플 ---")
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
        collector.export_json(results, "collected_live.json")

if __name__ == "__main__":
    main()
