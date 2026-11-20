"""Business operations and invariants for the CRM API."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import (
    BusinessRuleError,
    EntityNotFoundError,
    SlotConflictError,
)
from app.models import Call, Company, Manager, Meeting
from app.schemas import (
    CallCreate,
    CompanyCreate,
    CompanyStatus,
    MeetingCreate,
    MeetingPatch,
)

_BUSINESS_TIMEZONE = ZoneInfo(settings.timezone)
_MEETING_DURATION = timedelta(minutes=60)


@contextmanager
def _write_transaction(db: Session) -> Iterator[None]:
    """Commit a write atomically and translate known booking constraint races."""
    try:
        with db.begin():
            yield
    except IntegrityError as exc:
        constraint_name = getattr(
            getattr(exc.orig, "diag", None), "constraint_name", None
        )
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if constraint_name == "ex_meetings_manager_time" or (
            sqlstate == "23P01" and constraint_name is None
        ):
            raise SlotConflictError("У менеджера уже есть встреча в это время") from exc
        if constraint_name == "uq_meetings_active_company":
            raise SlotConflictError("У организации уже есть активная встреча") from exc
        raise


def _lock_manager_then_company(
    db: Session, manager_id: int, company_id: int
) -> tuple[Manager, Company]:
    """Lock parent rows in the same order for every meeting write."""
    manager = db.scalar(
        select(Manager).where(Manager.id == manager_id).with_for_update()
    )
    if manager is None:
        raise EntityNotFoundError(f"Менеджер с id={manager_id} не найден")

    company = db.scalar(
        select(Company).where(Company.id == company_id).with_for_update()
    )
    if company is None:
        raise EntityNotFoundError(f"Организация с id={company_id} не найдена")
    return manager, company


def _validate_meeting_time(start_time: datetime) -> datetime:
    """Validate a 60-minute slot against the configured business timezone."""
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise BusinessRuleError("Время встречи должно содержать часовой пояс")

    start_utc = start_time.astimezone(UTC)
    end_utc = start_utc + _MEETING_DURATION
    local_start = start_utc.astimezone(_BUSINESS_TIMEZONE)
    local_end = end_utc.astimezone(_BUSINESS_TIMEZONE)

    if local_start.weekday() >= 5:
        raise BusinessRuleError("Встречи назначаются только с понедельника по пятницу")
    if (
        local_start.date() != local_end.date()
        or local_start.time().replace(tzinfo=None) < time(9, 0)
        or local_end.time().replace(tzinfo=None) > time(18, 0)
    ):
        raise BusinessRuleError(
            "Встреча длится 60 минут и должна полностью проходить в интервале 09:00–18:00 Asia/Almaty"
        )
    return end_utc


def _check_booking_conflicts(
    db: Session,
    *,
    manager_id: int,
    company_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_meeting_id: int | None = None,
) -> None:
    manager_conflict = select(Meeting.id).where(
        Meeting.manager_id == manager_id,
        Meeting.status == "scheduled",
        Meeting.start_time < end_time,
        Meeting.end_time > start_time,
    )
    company_conflict = select(Meeting.id).where(
        Meeting.company_id == company_id,
        Meeting.status == "scheduled",
    )
    if exclude_meeting_id is not None:
        manager_conflict = manager_conflict.where(Meeting.id != exclude_meeting_id)
        company_conflict = company_conflict.where(Meeting.id != exclude_meeting_id)

    if db.scalar(manager_conflict.limit(1)) is not None:
        raise SlotConflictError("У менеджера уже есть встреча в это время")
    if db.scalar(company_conflict.limit(1)) is not None:
        raise SlotConflictError("У организации уже есть активная встреча")


def _create_meeting(
    db: Session,
    *,
    company: Company,
    manager: Manager,
    start_time: datetime,
) -> Meeting:
    """Create a meeting within an existing transaction and acquired parent locks."""
    end_time = _validate_meeting_time(start_time)
    start_utc = start_time.astimezone(UTC)
    _check_booking_conflicts(
        db,
        manager_id=manager.id,
        company_id=company.id,
        start_time=start_utc,
        end_time=end_time,
    )
    meeting = Meeting(
        company_id=company.id,
        manager_id=manager.id,
        start_time=start_utc,
        end_time=end_time,
        initial_start_time=start_utc,
        status="scheduled",
    )
    db.add(meeting)
    company.status = "meeting_set"
    db.flush()
    return meeting


def create_company(db: Session, payload: CompanyCreate) -> Company:
    company = Company(name=payload.name, bin=payload.bin, phone=payload.phone)
    with _write_transaction(db):
        db.add(company)
        db.flush()
    return company


def list_companies(
    db: Session,
    *,
    status: CompanyStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Company], int]:
    filters = [Company.status == status] if status is not None else []
    total = db.scalar(select(func.count(Company.id)).where(*filters)) or 0
    items = db.scalars(
        select(Company).where(*filters).order_by(Company.id).limit(limit).offset(offset)
    ).all()
    return items, total


def create_meeting(db: Session, payload: MeetingCreate) -> Meeting:
    with _write_transaction(db):
        manager, company = _lock_manager_then_company(
            db, payload.manager_id, payload.company_id
        )
        meeting = _create_meeting(
            db, company=company, manager=manager, start_time=payload.start_time
        )
    return meeting


def create_call(db: Session, payload: CallCreate) -> Call:
    with _write_transaction(db):
        manager, company = _lock_manager_then_company(
            db, payload.manager_id, payload.company_id
        )
        meeting_id = payload.meeting_id

        if payload.result == "meeting_set":
            if payload.meeting is not None:
                meeting = _create_meeting(
                    db,
                    company=company,
                    manager=manager,
                    start_time=payload.meeting.start_time,
                )
                meeting_id = meeting.id
            else:
                assert meeting_id is not None
                meeting = db.scalar(
                    select(Meeting).where(Meeting.id == meeting_id).with_for_update()
                )
                if meeting is None:
                    raise EntityNotFoundError(f"Встреча с id={meeting_id} не найдена")
                if meeting.company_id != company.id:
                    raise BusinessRuleError(
                        "Встреча не относится к указанной организации"
                    )
                if meeting.status != "scheduled":
                    raise BusinessRuleError(
                        "Нельзя связать звонок с отменённой встречей"
                    )
                already_linked = db.scalar(
                    select(Call.id).where(Call.meeting_id == meeting.id).limit(1)
                )
                if already_linked is not None:
                    raise BusinessRuleError("Встреча уже связана с другим звонком")
                company.status = "meeting_set"
        else:
            company.status = payload.result

        call = Call(
            company_id=company.id,
            manager_id=manager.id,
            result=payload.result,
            meeting_id=meeting_id,
        )
        db.add(call)
        db.flush()
    return call


def patch_meeting(db: Session, meeting_id: int, payload: MeetingPatch) -> Meeting:
    with _write_transaction(db):
        identity = db.get(Meeting, meeting_id)
        if identity is None:
            raise EntityNotFoundError(f"Встреча с id={meeting_id} не найдена")

        _lock_manager_then_company(db, identity.manager_id, identity.company_id)
        meeting = db.scalar(
            select(Meeting).where(Meeting.id == meeting_id).with_for_update()
        )
        if meeting is None:
            raise EntityNotFoundError(f"Встреча с id={meeting_id} не найдена")
        if meeting.status != "scheduled":
            raise BusinessRuleError("Можно изменить только активную встречу")

        if payload.status == "cancelled":
            meeting.status = "cancelled"
        else:
            assert payload.start_time is not None
            end_time = _validate_meeting_time(payload.start_time)
            start_utc = payload.start_time.astimezone(UTC)
            _check_booking_conflicts(
                db,
                manager_id=meeting.manager_id,
                company_id=meeting.company_id,
                start_time=start_utc,
                end_time=end_time,
                exclude_meeting_id=meeting.id,
            )
            meeting.start_time = start_utc
            meeting.end_time = end_time
            meeting.rescheduled_count += 1
        meeting.updated_at = datetime.now(UTC)
        db.flush()
    return meeting


def get_manager_schedule(
    db: Session, manager_id: int, schedule_date: date
) -> list[Meeting]:
    manager = db.get(Manager, manager_id)
    if manager is None:
        raise EntityNotFoundError(f"Менеджер с id={manager_id} не найден")

    local_start = datetime.combine(schedule_date, time.min, tzinfo=_BUSINESS_TIMEZONE)
    local_end = datetime.combine(
        schedule_date + timedelta(days=1), time.min, tzinfo=_BUSINESS_TIMEZONE
    )
    start_utc = local_start.astimezone(UTC)
    end_utc = local_end.astimezone(UTC)
    return list(
        db.scalars(
            select(Meeting)
            .where(
                Meeting.manager_id == manager_id,
                Meeting.status == "scheduled",
                Meeting.start_time >= start_utc,
                Meeting.start_time < end_utc,
            )
            .order_by(Meeting.start_time)
        ).all()
    )
