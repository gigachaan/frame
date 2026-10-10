import json
import sys

sys.stdout.reconfigure(encoding='utf-8')
from collector import OSINTCollector

collector = OSINTCollector()

print("=" * 65)
print("🚀 [테스트] 한국어 질문 1개 -> 7개국 자동 확장 및 최대 5건 수집")
print("=" * 65)

korean_input = "대만해협 군사활동"
korean_date = "2026-10-01"

# 실행: 한국어 질문만 주면 알아서 7개국 쿼리 생성 -> 수집 -> 최대 5건 반환
result = collector.collect_from_korean(
    question=korean_input,
    event_date=korean_date,
    max_total_docs=5, # 🎯 사용자 요청: 최대 5건 제한
    days_back=30
)

print(f"\n📊 [7개국별 최종 수집 결과] (총 {result['total_count']}건 / 최대 5건 제한):")
for country_code, docs in result["by_country"].items():
    print(f"  - [{country_code}] {len(docs)}건")
    for d in docs:
        print(f"    * [{d.get('tier')}티어] {d.get('source_name')} ({d.get('language')}) | {d.get('title')[:35]}")

collector.export_json(result, "korean_expanded_result.json")
print("\n[💾] 'korean_expanded_result.json' 저장 완료!")
