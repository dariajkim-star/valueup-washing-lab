"""소스 어댑터 공통 인터페이스 (AD-3).

각 원천 소스(dart/krx/ecos)는 이 인터페이스를 구현하며,
자기가 맡은 원천 테이블의 유일한 writer다. 파이프-필터: fetch → normalize → upsert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class SourceAdapter(ABC):
    """수집 어댑터 베이스. fetch(원천 호출) → normalize(정규화) → upsert(멱등 적재)."""

    #: 소스 식별자 (dart / krx / ecos)
    source: str = ""

    @abstractmethod
    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        """외부 소스에서 원시 데이터를 가져온다(네트워크·키 필요)."""

    @abstractmethod
    def normalize(self, raw: Any) -> Any:
        """원시 데이터를 DB 적재용 레코드로 정규화한다(순수 로직, 테스트 가능)."""

    @abstractmethod
    def upsert(self, session: Session, records: Any) -> int:
        """정규화 레코드를 자연키 기준 멱등 upsert한다(AD-7). 적재 행 수 반환."""
