"""FastAPI application setup and client-safe exception handlers."""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.exceptions import BusinessRuleError, EntityNotFoundError, SlotConflictError
from app.routers import router

app = FastAPI(
    title="Внутренняя CRM — API звонков и встреч",
    summary="REST API для организаций, звонков и встреч менеджеров.",
    description=(
        "API фиксирует результаты обзвона организаций и управляет встречами.\n\n"
        "Все значения `datetime` передаются и возвращаются в UTC (ISO 8601) "
        "с указанием часового пояса. Рабочее время проверяется по `Asia/Almaty`: "
        "понедельник–пятница, 09:00–18:00. Встреча длится 60 минут.\n\n"
        'Отказы возвращаются с JSON-телом вида `{"detail": "описание ошибки"}`. '
        "Основные коды: 404 — сущность не найдена, 409 — конфликт расписания "
        "или уникальности, 422 — неверный запрос или нарушение бизнес-правила."
    ),
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Организации",
            "description": "Создание организаций и получение списка с фильтрацией и пагинацией.",
        },
        {
            "name": "Звонки",
            "description": "Регистрация результата звонка и привязка встречи.",
        },
        {
            "name": "Встречи",
            "description": "Назначение, перенос и отмена 60-минутных встреч.",
        },
        {
            "name": "Расписание",
            "description": "Активные встречи менеджера за календарный день Алматы.",
        },
        {"name": "Сервис", "description": "Проверка доступности API."},
    ],
)
app.include_router(router)


@app.get(
    "/health",
    tags=["Сервис"],
    summary="Проверить доступность API",
    description="Возвращает `status: ok`, если приложение отвечает на запросы.",
)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(EntityNotFoundError)
async def entity_not_found_handler(
    request: Request, exc: EntityNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": exc.detail}
    )


@app.exception_handler(SlotConflictError)
async def slot_conflict_handler(
    request: Request, exc: SlotConflictError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": exc.detail}
    )


@app.exception_handler(BusinessRuleError)
async def business_rule_handler(
    request: Request, exc: BusinessRuleError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    messages = [
        f"{'/'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "; ".join(messages)},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    original = exc.orig
    sqlstate = getattr(original, "sqlstate", None)
    constraint_name = getattr(getattr(original, "diag", None), "constraint_name", None)

    if constraint_name == "ex_meetings_manager_time" or sqlstate == "23P01":
        detail = "У менеджера уже есть встреча в это время"
        response_status = status.HTTP_409_CONFLICT
    elif constraint_name == "uq_meetings_active_company":
        detail = "У организации уже есть активная встреча"
        response_status = status.HTTP_409_CONFLICT
    elif sqlstate == "23505":
        detail = "Запись с таким уникальным значением уже существует"
        response_status = status.HTTP_409_CONFLICT
    elif sqlstate == "23503":
        detail = "Связанная организация, менеджер или встреча не найдены"
        response_status = status.HTTP_404_NOT_FOUND
    elif sqlstate == "23514":
        detail = "Переданные данные нарушают допустимые ограничения"
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        detail = "Нарушено ограничение целостности данных"
        response_status = status.HTTP_400_BAD_REQUEST

    return JSONResponse(
        status_code=response_status,
        content={"detail": detail},
    )
