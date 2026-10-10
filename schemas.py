"""
OSINT 수집 파이프라인 데이터 규격 (Schemas)
팀원(나현님, 신엽님)과의 데이터 교환 및 검증을 위한 표준 규격 정의
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ParagraphData(BaseModel):
    """개별 문단 데이터 - LLM의 핀포인트 인용(Citation) 단위"""
    paragraph_id: str = Field(description="문서ID_문단번호 (예: doc_1a2b3c_p1)")
    raw_text: str = Field(description="문단 원문 텍스트")


class DocumentData(BaseModel):
    """수집된 단일 OSINT 문서 데이터 규격"""
    doc_id: str = Field(description="문서 고유 식별자 (예: doc_1a2b3c)")
    url: str = Field(description="출처 원문 URL")
    title: str = Field(description="기사/문서 제목")

    # 🌐 언어 식별
    language: str = Field(default="unknown", description="문서 언어 코드: zh, ja, ko, en, unknown")

    # 🎯 티어 및 출처 평가 메타데이터
    tier: int = Field(description="출처 등급: 1(당사국 공식), 2(제3국 중립 관측), 3(검증 언론)")
    source_name: str = Field(description="기관/언론사 명칭 (예: Taiwan MND, Japan MoD)")
    country: str = Field(description="출처 국가/진영 코드 (TW, CN, JP, SG, PH 등)")
    source_category: str = Field(description="출처 유형 (party_official, neutral_observer, reputable_media)")
    credibility_weight: float = Field(description="기본 신뢰도 가중치 (0.0 ~ 1.0)")

    # 🔄 순환 보고(Circular Reporting / 재인용) 방어 메타데이터
    is_reprint_likely: bool = Field(default=False, description="다른 매체를 재인용한 기사일 가능성 여부")
    quoted_source: Optional[str] = Field(default=None, description="본문에서 감지된 원래 발언 주체/인용 매체 (예: Reuters, Taiwan MND)")

    # ⏱️ 시간 및 수집 상태
    published_date: Optional[str] = Field(default=None, description="확인된 기사/공문서 발행일시")
    event_date: Optional[str] = Field(default=None, description="사건 발생일 (수집단에서는 절대 임의로 채우지 않고 None 유지)")
    status: str = Field(description="수집 및 절단 상태: success_full 또는 success_truncated")

    # 📑 문단 목록
    paragraphs: List[ParagraphData] = Field(default_factory=list, description="분할된 문단 목록")
