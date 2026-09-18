from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import AnswerStatus, InspectionStatus, OccurrenceStatus, Role, Severity


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    role: Role
    active: bool
    mfa_enabled: bool


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=180)
    password: str = Field(min_length=15, max_length=128)
    role: Role

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        normalized = value.casefold()
        blocked = {"aero@123", "aeroops@2026!", "password", "senha123", "administrador", "qwerty123456789"}
        if normalized in blocked or "aeroops" in normalized or "bhairport" in normalized:
            raise ValueError("Senha comum, demonstrativa ou relacionada ao sistema não é permitida")
        return value


class AuthEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int | None
    event_type: str
    outcome: str
    ip_address: str | None
    details: str | None
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int
    entity: str
    entity_id: int
    action: str
    details: str | None
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: Role | None = None
    active: bool | None = None


class Token(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=4096)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=15, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return UserCreate.validate_password_strength(value)


class MfaCode(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


class MfaSetupOut(BaseModel):
    secret: str
    provisioning_uri: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    ip_address: str | None
    user_agent: str | None
    last_seen_at: datetime


class AnswerCreate(BaseModel):
    item_key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=180)
    status: AnswerStatus
    observation: str | None = None
    severity: Severity | None = None
    evidence_url: str | None = None
    grid_cell: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,12}$")

    @model_validator(mode="after")
    def validate_non_compliance(self):
        if self.status == AnswerStatus.NAO_CONFORME:
            if not self.observation or not self.observation.strip():
                raise ValueError("Não conformidade exige observação")
            if not self.severity:
                raise ValueError("Não conformidade exige gravidade")
            if not self.evidence_url:
                raise ValueError("Não conformidade exige ao menos uma evidência")
            if not self.grid_cell:
                raise ValueError("Não conformidade exige localização por quadrícula")
        return self


class AnswerOut(AnswerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class InspectionCreate(BaseModel):
    inspection_type: str = Field(default="PATIO", min_length=2, max_length=40)
    apron: str = Field(min_length=1, max_length=60)
    grid_cell: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,12}$")
    location_text: str | None = Field(default=None, max_length=180)
    shift: str = Field(min_length=1, max_length=30)
    weather: str = Field(default="Não informado", max_length=60)
    notes: str | None = None
    answers: list[AnswerCreate] = Field(min_length=1)


class InspectionPatch(InspectionCreate):
    pass


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    protocol: str
    inspection_type: str
    inspector_id: int
    apron: str
    grid_cell: str | None
    location_text: str | None
    shift: str
    weather: str
    notes: str | None
    status: InspectionStatus
    started_at: datetime
    submitted_at: datetime | None
    answers: list[AnswerOut] = []


class OccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    inspection_id: int
    answer_id: int
    title: str
    description: str
    grid_cell: str
    severity: Severity
    status: OccurrenceStatus
    decision_note: str | None
    assigned_to: int | None
    created_at: datetime
    updated_at: datetime


class OccurrenceTransition(BaseModel):
    status: OccurrenceStatus
    note: str = Field(min_length=3, max_length=2000)


class EquipmentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    company: str = Field(min_length=1, max_length=160)
    last_inspection: date | None = None
    next_inspection: date


class EquipmentOut(EquipmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    active: bool


class EquipmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    company: str | None = Field(default=None, min_length=1, max_length=160)
    last_inspection: date | None = None
    next_inspection: date | None = None
    active: bool | None = None


class GridCellOut(BaseModel):
    code: str
    row: int
    column: str
    occurrences: int
    critical: int


class ReportSummary(BaseModel):
    inspections_by_day: dict[str, int]
    occurrences_by_area: dict[str, int]
    productivity_by_fiscal: dict[str, int]



class DashboardSummary(BaseModel):
    inspections_total: int
    inspections_by_type: dict[str, int]
    occurrences_open: int
    critical_open: int
    equipment_expiring_30_days: int
    occurrences_by_status: dict[str, int]
    occurrences_by_severity: dict[str, int]


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    content_type: str
    storage_path: str
    created_at: datetime
