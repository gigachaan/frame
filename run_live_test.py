import sys
sys.stdout.reconfigure(encoding='utf-8')

from collector import OSINTCollector

def test_live():
    print("=" * 65)
    print("🚀 [KoreanDefense/frame] Tavily 실제 라이브 검색 테스트 시작")
    print("=" * 65)

    collector = OSINTCollector()
    print(f"[+] API 키 로드 확인: {collector.api_key[:12]}...")
    print(f"[+] 검색 화이트리스트 도메인 ({len(collector.allowed_domains)}개): {', '.join(collector.allowed_domains[:5])} 등")

    # 대만 해협 관련 실제 3개 국어 쿼리
    queries = {
        "zh": "解放军 台湾海峡 演习",
        "ja": "台湾海峡 中国軍 演習",
        "en": "Taiwan Strait Chinese military drill"
    }

    print("\n🔍 다국어 쿼리 실행 중...")
    docs = collector.collect_multilingual(queries, days_back=30, max_results_per_query=3)

    if docs:
        output_file = "collected_live.json"
        collector.export_json(docs, output_file)
        print(f"\n[★] 성공! 실제 라이브 데이터 샘플 (첫 번째 문서):")
        d = docs[0]
        print(f"  - 제목: {d.get('title')}")
        print(f"  - 출처: {d.get('source_name')} ({d.get('country')}, Tier {d.get('tier')})")
        print(f"  - 언어: {d.get('language')}")
        print(f"  - URL: {d.get('url')}")
        print(f"  - 문단 수: {len(d.get('paragraphs', []))}개")
        if d.get('is_reprint_likely'):
            print(f"  - ⚠️ 재인용 감지: {d.get('quoted_source')}")
    else:
        print("[-] 수집된 결과가 0건입니다. 쿼리 또는 도메인 매칭을 확인합니다.")

if __name__ == "__main__":
    test_live()
