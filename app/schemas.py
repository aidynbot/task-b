"""Pydantic request and response schemas for the CRM API."""

import re
from datetime import UTC, date, datetime
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


class CompanyCreate(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]
    bin: Bin
    phone: PhoneNumber


class CompanyResponse(ORMModel):
    id: int
    name: str
    bin: Bin
    phone: PhoneNumber
    status: CompanyStatus
    created_at: UTCDateTime


class CompanyListResponse(BaseModel):
    items: list[CompanyResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class MeetingDraft(BaseModel):
    """Meeting details nested in a call; company and manager come from the call."""

    start_time: UTCDateTime


class MeetingCreate(BaseModel):
    company_id: int = Field(gt=0)
    manager_id: int = Field(gt=0)
    start_time: UTCDateTime


class CallCreate(BaseModel):
    company_id: int = Field(gt=0)
    manager_id: int = Field(gt=0)
    result: CallResult
    meeting_id: int | None = Field(default=None, gt=0)
    meeting: MeetingDraft | None = None

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
    start_time: UTCDateTime | None = None
    status: Literal["cancelled"] | None = None

    @model_validator(mode="after")
    def require_one_action(self) -> "MeetingPatch":
        if (self.start_time is None) == (self.status is None):
            raise ValueError(
                "Укажите ровно одно действие: новое start_time или status='cancelled'"
            )
        return self


class ManagerScheduleResponse(BaseModel):
    manager_id: int
    date: date
    items: list[MeetingResponse]
