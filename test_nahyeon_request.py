import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
from collector import OSINTCollector

collector = OSINTCollector()

nahyeon_plan = {
  "event": "대만해협 군사활동",
  "event_date": "2026-10-01",
  "queries": [
    {
      "language": "zh",
      "query": "2026 台湾海峡 演习 军用机 中线"
    },
    {
      "language": "ja",
      "query": "2026 台湾海峡 中国軍機 演習 防衛省"
    },
    {
      "language": "en",
      "query": "Taiwan Strait military aircraft PLA Taiwan defense"
    }
  ]
}

print("=" * 65)
print("🚀 나현님 요청 포맷 수집 테스트 (한국 포함 4개국 그룹화)")
print("=" * 65)

res = collector.collect_plan(nahyeon_plan, days_back=30, max_results_per_query=3)

print("\n📊 4개국별 수집 결과 요약:")
for country_code, docs in res["by_country"].items():
    print(f"  - [{country_code}] 총 {len(docs)}건 수집")
    for d in docs[:2]:
        print(f"    * {d.get('source_name')} ({d.get('language')}) | {d.get('title')[:30]}")

print(f"\n[✓] 전체 문서 수: {len(res['all_documents'])}건")

collector.export_json(res, "nahyeon_response_sample.json")
print("[💾] 'nahyeon_response_sample.json' 저장 완료!")
