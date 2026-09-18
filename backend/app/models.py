import enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(str, enum.Enum):
    FISCAL = "FISCAL"
    SUPERVISOR = "SUPERVISOR"
    ANALISTA = "ANALISTA"
    COORDENACAO = "COORDENACAO"
    ADMINISTRADOR = "ADMINISTRADOR"


class InspectionStatus(str, enum.Enum):
    RASCUNHO = "RASCUNHO"
    CONCLUIDA = "CONCLUIDA"


class AnswerStatus(str, enum.Enum):
    CONFORME = "CONFORME"
    NAO_CONFORME = "NAO_CONFORME"
    NAO_APLICA = "NAO_APLICA"


class OccurrenceStatus(str, enum.Enum):
    ABERTA = "ABERTA"
    EM_VALIDACAO = "EM_VALIDACAO"
    VALIDADA = "VALIDADA"
    REJEITADA = "REJEITADA"
    EM_TRATAMENTO = "EM_TRATAMENTO"
    RESOLVIDA = "RESOLVIDA"


class Severity(str, enum.Enum):
    BAIXA = "BAIXA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class ChecklistStatus(str, enum.Enum):
    RASCUNHO = "RASCUNHO"
    EM_REVISAO = "EM_REVISAO"
    PUBLICADO = "PUBLICADO"
    ARQUIVADO = "ARQUIVADO"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    inspection_type: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ChecklistStatus] = mapped_column(Enum(ChecklistStatus), default=ChecklistStatus.RASCUNHO, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    items: Mapped[list["ChecklistItem"]] = relationship(cascade="all, delete-orphan", order_by="ChecklistItem.position")
    attachments: Mapped[list["Attachment"]] = relationship(foreign_keys="Attachment.checklist_id", cascade="all, delete-orphan")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("checklist_templates.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(180))
    group_name: Mapped[str] = mapped_column(String(100), default="Operacional")
    position: Mapped[int] = mapped_column(Integer, default=1)
    observation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    severity_required: Mapped[bool] = mapped_column(Boolean, default=True)
    location_required: Mapped[bool] = mapped_column(Boolean, default=True)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True)


class Inspection(Base):
    __tablename__ = "inspections"
    id: Mapped[int] = mapped_column(primary_key=True)
    protocol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    inspection_type: Mapped[str] = mapped_column(String(40), default="PATIO")
    inspector_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    apron: Mapped[str] = mapped_column(String(60))
    grid_cell: Mapped[str | None] = mapped_column(String(12))
    location_text: Mapped[str | None] = mapped_column(String(180))
    shift: Mapped[str] = mapped_column(String(30))
    weather: Mapped[str] = mapped_column(String(60), default="Não informado")
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[InspectionStatus] = mapped_column(Enum(InspectionStatus), default=InspectionStatus.RASCUNHO)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    inspector: Mapped[User] = relationship()
    answers: Mapped[list["InspectionAnswer"]] = relationship(cascade="all, delete-orphan")
    occurrences: Mapped[list["Occurrence"]] = relationship(cascade="all, delete-orphan")


class InspectionAnswer(Base):
    __tablename__ = "inspection_answers"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"))
    item_key: Mapped[str] = mapped_column(String(80))
    label: Mapped[str] = mapped_column(String(180))
    status: Mapped[AnswerStatus] = mapped_column(Enum(AnswerStatus))
    observation: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity | None] = mapped_column(Enum(Severity))
    evidence_url: Mapped[str | None] = mapped_column(String(500))
    grid_cell: Mapped[str | None] = mapped_column(String(12))


class Occurrence(Base):
    __tablename__ = "occurrences"
    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(ForeignKey("inspections.id"), index=True)
    answer_id: Mapped[int] = mapped_column(ForeignKey("inspection_answers.id"))
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    grid_cell: Mapped[str] = mapped_column(String(12))
    severity: Mapped[Severity] = mapped_column(Enum(Severity))
    status: Mapped[OccurrenceStatus] = mapped_column(Enum(OccurrenceStatus), default=OccurrenceStatus.EM_VALIDACAO)
    decision_note: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("occurrences.id"))
    checklist_id: Mapped[int | None] = mapped_column(ForeignKey("checklist_templates.id"), index=True)
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inspections.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    storage_path: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    company: Mapped[str] = mapped_column(String(160))
    last_inspection: Mapped[date | None] = mapped_column(Date)
    next_inspection: Mapped[date] = mapped_column(Date, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("id", "entity", name="uq_audit_identity"),)
