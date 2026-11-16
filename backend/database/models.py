"""SQLite persistence (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="Untitled investigation")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    horizon_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolutions: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[list] = mapped_column(JSON, default=list)
    extraction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    files: Mapped[list["UploadedFile"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(back_populates="investigation", cascade="all, delete-orphan",
                                                      order_by="Question.position")
    agent_runs: Mapped[list["AgentRun"]] = relationship(back_populates="investigation", cascade="all, delete-orphan",
                                                        order_by="AgentRun.started_at")
    facts: Mapped[list["FactRecord"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")
    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="investigation", cascade="all, delete-orphan")


class UploadedFile(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    original_name: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(Text)
    file_type: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    investigation: Mapped[Investigation] = relationship(back_populates="files")


class FactRecord(Base):
    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"), index=True)
    fact_id: Mapped[str] = mapped_column(String(20), index=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(60))
    period: Mapped[str | None] = mapped_column(String(10), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    file_id: Mapped[str] = mapped_column(String(36))
    file_name: Mapped[str] = mapped_column(String(300))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    record_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(20))
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON)
    investigation: Mapped[Investigation] = relationship(back_populates="facts")


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(200))
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(20))
    input_type: Mapped[str] = mapped_column(String(20), default="choice")
    options: Mapped[list] = mapped_column(JSON, default=list)
    related_fields: Mapped[list] = mapped_column(JSON, default=list)
    related_fact_ids: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(30), default="rules")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | answered | skipped
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    interpretation: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_analysis: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    investigation: Mapped[Investigation] = relationship(back_populates="questions")


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    agent: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # success | failed | skipped | cached
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    investigation: Mapped[Investigation] = relationship(back_populates="agent_runs")


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id", ondelete="CASCADE"))
    input: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    investigation: Mapped[Investigation] = relationship(back_populates="scenarios")


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
