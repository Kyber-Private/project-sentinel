"""Session helpers and small query functions."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from database.models import FactRecord, Investigation, SessionLocal
from domain import Fact


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_investigation(session: Session, inv_id: str) -> Investigation | None:
    return session.get(Investigation, inv_id)


def replace_facts(session: Session, inv_id: str, facts: list[Fact]) -> None:
    session.execute(delete(FactRecord).where(FactRecord.investigation_id == inv_id))
    for f in facts:
        session.add(
            FactRecord(
                investigation_id=inv_id, fact_id=f.id, entity_type=f.entity_type, entity=f.entity,
                metric=f.metric, period=f.period, value=f.value, text_value=f.text_value, currency=f.currency,
                file_id=f.source.file_id, file_name=f.source.file_name, page=f.source.page, sheet=f.source.sheet,
                row=f.source.row, record_id=f.source.record_id, excerpt=f.source.excerpt,
                extraction_method=f.extraction_method, superseded=f.superseded, data=f.model_dump(),
            )
        )


def get_facts(session: Session, inv_id: str, ids: list[str] | None = None) -> list[FactRecord]:
    q = select(FactRecord).where(FactRecord.investigation_id == inv_id)
    if ids:
        q = q.where(FactRecord.fact_id.in_(ids))
    return list(session.scalars(q.order_by(FactRecord.fact_id)))
