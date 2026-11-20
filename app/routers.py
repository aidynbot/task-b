"""Thin HTTP routes delegating all business logic to services."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
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
    ErrorResponse,
    ManagerScheduleResponse,
    MeetingCreate,
    MeetingPatch,
    MeetingResponse,
)

router = APIRouter(
    responses={
        422: {
            "model": ErrorResponse,
            "description": "Некорректные параметры или тело запроса.",
        }
    }
)
DbSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/companies",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Организации"],
    summary="Создать организацию",
    description=(
        "Создаёт организацию со статусом `new`. БИН должен состоять из 12 цифр. "
        "Телефон Казахстана принимается с префиксом `+7`, `7` или внутренним `8` "
        "и сохраняется в нормализованном формате `+7XXXXXXXXXX`."
    ),
    responses={
        409: {
            "model": ErrorResponse,
            "description": "Организация с таким БИН уже существует.",
        },
        422: {
            "model": ErrorResponse,
            "description": "Некорректный БИН, телефон или тело запроса.",
        },
    },
)
def create_company(payload: CompanyCreate, db: DbSession) -> CompanyResponse:
    return services.create_company(db, payload)


@router.get(
    "/companies",
    response_model=CompanyListResponse,
    tags=["Организации"],
    summary="Получить список организаций",
    description=(
        "Возвращает страницу организаций. `offset` задаёт число пропускаемых "
        "записей; например, при `limit=20` значение `offset=20` запрашивает "
        "следующую страницу."
    ),
)
def list_companies(
    db: DbSession,
    status_filter: Annotated[
        CompanyStatus | None,
        Query(
            alias="status",
            description="Необязательный фильтр: new, no_answer, refused или meeting_set.",
        ),
    ] = None,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Число организаций в ответе (1–100).")
    ] = 50,
    offset: Annotated[
        int, Query(ge=0, description="Сколько записей пропустить перед выдачей.")
    ] = 0,
) -> CompanyListResponse:
    items, total = services.list_companies(
        db, status=status_filter, limit=limit, offset=offset
    )
    return CompanyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/calls",
    response_model=CallResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Звонки"],
    summary="Записать результат звонка",
    description=(
        "Фиксирует один результат звонка. Для `meeting_set` укажите ровно один "
        "вариант: `meeting_id` существующей активной встречи этой организации "
        "или объект `meeting` с `start_time` для атомарного создания встречи. "
        "Встреча не должна быть связана с другим звонком. Для `no_answer` и "
        "`refused` поля встречи не передаются."
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Не найдена организация, менеджер или встреча.",
        },
        409: {
            "model": ErrorResponse,
            "description": "Конфликт ограничения целостности.",
        },
        422: {
            "model": ErrorResponse,
            "description": "Результат или связь со встречей не соответствует правилам.",
        },
    },
)
def create_call(payload: CallCreate, db: DbSession) -> CallResponse:
    return services.create_call(db, payload)


@router.post(
    "/meetings",
    response_model=MeetingResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Встречи"],
    summary="Назначить встречу",
    description=(
        "Создаёт активную встречу длительностью 60 минут. Время передаётся в UTC "
        "и проверяется по календарю `Asia/Almaty`: понедельник–пятница, "
        "09:00–18:00. У менеджера не допускаются пересечения; у организации "
        "может быть только одна активная встреча."
    ),
    responses={
        404: {
            "model": ErrorResponse,
            "description": "Организация или менеджер не найдены.",
        },
        409: {
            "model": ErrorResponse,
            "description": "У менеджера занят интервал или у организации уже есть активная встреча.",
        },
        422: {
            "model": ErrorResponse,
            "description": "Время вне рабочих часов, naive datetime или неверное тело запроса.",
        },
    },
)
def create_meeting(payload: MeetingCreate, db: DbSession) -> MeetingResponse:
    return services.create_meeting(db, payload)


@router.patch(
    "/meetings/{meeting_id}",
    response_model=MeetingResponse,
    tags=["Встречи"],
    summary="Перенести или отменить встречу",
    description=(
        "Передайте ровно одно действие: `start_time` для переноса либо "
        "`status: cancelled` для отмены. При переносе первоначальное время "
        "`initial_start_time` сохраняется, а счётчик переносов увеличивается."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Встреча не найдена."},
        409: {
            "model": ErrorResponse,
            "description": "Новое время конфликтует с другой встречей.",
        },
        422: {
            "model": ErrorResponse,
            "description": "Некорректное время или PATCH содержит не ровно одно действие.",
        },
    },
)
def patch_meeting(
    meeting_id: Annotated[int, Path(gt=0, description="ID встречи.")],
    payload: MeetingPatch,
    db: DbSession,
) -> MeetingResponse:
    return services.patch_meeting(db, meeting_id, payload)


@router.get(
    "/managers/{manager_id}/schedule",
    response_model=ManagerScheduleResponse,
    tags=["Расписание"],
    summary="Получить расписание менеджера на дату",
    description=(
        "Возвращает активные встречи менеджера, начало которых попадает в "
        "указанный календарный день `Asia/Almaty`. Границы дня переводятся в UTC "
        "для выборки; время встреч в ответе также указано в UTC."
    ),
    responses={
        404: {"model": ErrorResponse, "description": "Менеджер не найден."},
        422: {
            "model": ErrorResponse,
            "description": "Дата должна быть календарной датой в формате YYYY-MM-DD.",
        },
    },
)
def get_manager_schedule(
    manager_id: Annotated[int, Path(gt=0, description="ID менеджера.")],
    db: DbSession,
    schedule_date: Annotated[
        date,
        Query(
            alias="date",
            description="Календарная дата расписания по часовому поясу Asia/Almaty.",
            examples=["2026-11-23"],
        ),
    ],
) -> ManagerScheduleResponse:
    meetings = services.get_manager_schedule(db, manager_id, schedule_date)
    return ManagerScheduleResponse(
        manager_id=manager_id, date=schedule_date, items=meetings
    )
