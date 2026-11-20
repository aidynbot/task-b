"""Thin HTTP routes delegating all business logic to services."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import services
from app.database import get_db
from app.schemas import (
    CallCreate,
    CallResponse,
    CompanyCreate,
    CompanyListResponse,
    CompanyResponse,
    CompanyStatus,
    ManagerScheduleResponse,
    MeetingCreate,
    MeetingPatch,
    MeetingResponse,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED
)
def create_company(payload: CompanyCreate, db: DbSession) -> CompanyResponse:
    return services.create_company(db, payload)


@router.get("/companies", response_model=CompanyListResponse)
def list_companies(
    db: DbSession,
    status_filter: Annotated[CompanyStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CompanyListResponse:
    items, total = services.list_companies(
        db, status=status_filter, limit=limit, offset=offset
    )
    return CompanyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/calls", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
def create_call(payload: CallCreate, db: DbSession) -> CallResponse:
    return services.create_call(db, payload)


@router.post(
    "/meetings", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED
)
def create_meeting(payload: MeetingCreate, db: DbSession) -> MeetingResponse:
    return services.create_meeting(db, payload)


@router.patch("/meetings/{meeting_id}", response_model=MeetingResponse)
def patch_meeting(
    meeting_id: int, payload: MeetingPatch, db: DbSession
) -> MeetingResponse:
    return services.patch_meeting(db, meeting_id, payload)


@router.get("/managers/{manager_id}/schedule", response_model=ManagerScheduleResponse)
def get_manager_schedule(
    manager_id: int,
    db: DbSession,
    schedule_date: Annotated[date, Query(alias="date")],
) -> ManagerScheduleResponse:
    meetings = services.get_manager_schedule(db, manager_id, schedule_date)
    return ManagerScheduleResponse(
        manager_id=manager_id, date=schedule_date, items=meetings
    )
