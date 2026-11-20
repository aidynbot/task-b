"""Pydantic request and response schemas for the CRM API."""

import re
from datetime import UTC, datetime
from datetime import date as Date
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

CompanyStatus = Literal["new", "no_answer", "refused", "meeting_set"]
CallResult = Literal["meeting_set", "no_answer", "refused"]
MeetingStatus = Literal["scheduled", "cancelled"]


def _to_utc(value: datetime) -> datetime:
    """Normalize an aware timestamp to UTC after AwareDatetime validation."""
    return value.astimezone(UTC)


UTCDateTime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
Bin = Annotated[str, StringConstraints(pattern=r"^[0-9]{12}$")]


def _normalize_kazakhstan_phone(value: str) -> str:
    """Normalize +7, 7, or domestic 8 prefixes to +7XXXXXXXXXX."""
    compact = re.sub(r"[\s().-]", "", value)
    if compact.startswith("+"):
        if not compact.startswith("+7"):
            raise ValueError("Телефон должен использовать код Казахстана +7 или 8")
        digits = compact[1:]
    else:
        digits = compact

    if not digits.isascii() or not digits.isdigit() or len(digits) != 11:
        raise ValueError("Укажите номер из 11 цифр, например +77001234567")
    if digits[0] not in {"7", "8"}:
        raise ValueError("Номер должен начинаться с +7, 7 или 8")
    if digits[0] == "8":
        digits = "7" + digits[1:]
    return f"+{digits}"


PhoneNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
    AfterValidator(_normalize_kazakhstan_phone),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorResponse(BaseModel):
    detail: str = Field(description="Краткое объяснение причины отказа.")


class CompanyCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "ТОО Пример",
                    "bin": "123456789012",
                    "phone": "+7 (700) 123-45-67",
                }
            ]
        }
    )

    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
        Field(description="Название организации."),
    ]
    bin: Annotated[Bin, Field(description="БИН организации: ровно 12 цифр.")]
    phone: Annotated[
        PhoneNumber,
        Field(
            description=(
                "Телефон Казахстана. Принимаются +7, 7 или внутренний префикс 8; "
                "пробелы, скобки и дефисы удаляются, результат хранится как +7XXXXXXXXXX."
            )
        ),
    ]


class CompanyResponse(ORMModel):
    id: int
    name: str
    bin: Annotated[Bin, Field(description="Уникальный БИН организации.")]
    phone: PhoneNumber
    status: CompanyStatus
    created_at: UTCDateTime


class CompanyListResponse(BaseModel):
    items: list[CompanyResponse] = Field(description="Организации на текущей странице.")
    total: int = Field(ge=0, description="Общее число организаций после фильтрации.")
    limit: int = Field(ge=1, description="Максимум организаций в ответе.")
    offset: int = Field(ge=0, description="Число пропущенных записей.")


class MeetingDraft(BaseModel):
    """Meeting details nested in a call; company and manager come from the call."""

    start_time: UTCDateTime = Field(
        description="Начало новой встречи в UTC, ISO 8601 с часовым поясом.",
        examples=["2026-11-23T04:00:00Z"],
    )


class MeetingCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": 1,
                    "manager_id": 1,
                    "start_time": "2026-11-23T04:00:00Z",
                }
            ]
        }
    )

    company_id: int = Field(gt=0, description="ID организации.")
    manager_id: int = Field(gt=0, description="ID менеджера.")
    start_time: UTCDateTime = Field(
        description=(
            "Начало встречи в UTC, ISO 8601 с часовым поясом. "
            "Время проверяется по рабочему календарю Asia/Almaty."
        ),
        examples=["2026-11-23T04:00:00Z"],
    )


class CallCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": 1,
                    "manager_id": 1,
                    "result": "meeting_set",
                    "meeting_id": 10,
                },
                {
                    "company_id": 1,
                    "manager_id": 1,
                    "result": "meeting_set",
                    "meeting": {"start_time": "2026-11-23T04:00:00Z"},
                },
                {"company_id": 1, "manager_id": 1, "result": "no_answer"},
            ]
        }
    )

    company_id: int = Field(gt=0, description="ID организации, которой звонили.")
    manager_id: int = Field(gt=0, description="ID менеджера, выполнившего звонок.")
    result: CallResult = Field(
        description="Итог звонка: встреча назначена, нет ответа или отказ."
    )
    meeting_id: int | None = Field(
        default=None,
        gt=0,
        description="ID существующей активной встречи этой организации.",
    )
    meeting: MeetingDraft | None = Field(
        default=None,
        description=(
            "Данные для атомарного создания встречи. Укажите вместо meeting_id; "
            "допустимо только при result=meeting_set."
        ),
    )

    @model_validator(mode="after")
    def validate_meeting_binding(self) -> "CallCreate":
        has_meeting_id = self.meeting_id is not None
        has_meeting_payload = self.meeting is not None

        if self.result == "meeting_set":
            if has_meeting_id == has_meeting_payload:
                raise ValueError(
                    "Для результата meeting_set укажите ровно одно: meeting_id или meeting"
                )
        elif has_meeting_id or has_meeting_payload:
            raise ValueError(
                "Поля meeting_id и meeting допустимы только для результата meeting_set"
            )
        return self


class MeetingResponse(ORMModel):
    id: int
    company_id: int
    manager_id: int
    start_time: UTCDateTime
    end_time: UTCDateTime
    initial_start_time: UTCDateTime
    status: MeetingStatus
    rescheduled_count: int = Field(ge=0)
    created_at: UTCDateTime
    updated_at: UTCDateTime


class CallResponse(ORMModel):
    id: int
    company_id: int
    manager_id: int
    result: CallResult
    meeting_id: int | None
    created_at: UTCDateTime


class MeetingPatch(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"start_time": "2026-11-23T05:00:00Z"},
                {"status": "cancelled"},
            ]
        }
    )

    start_time: UTCDateTime | None = Field(
        default=None,
        description="Новое время начала в UTC для переноса встречи.",
        examples=["2026-11-23T05:00:00Z"],
    )
    status: Literal["cancelled"] | None = Field(
        default=None, description="Передайте cancelled для отмены встречи."
    )

    @model_validator(mode="after")
    def require_one_action(self) -> "MeetingPatch":
        if (self.start_time is None) == (self.status is None):
            raise ValueError(
                "Укажите ровно одно действие: новое start_time или status='cancelled'"
            )
        return self


class ManagerScheduleResponse(BaseModel):
    manager_id: int = Field(description="ID менеджера.")
    date: Date = Field(description="Календарная дата в часовом поясе Asia/Almaty.")
    items: list[MeetingResponse] = Field(description="Активные встречи этого дня.")
