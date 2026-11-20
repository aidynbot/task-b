"""Integration coverage for CRM API rules."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

_ALMATY = ZoneInfo("Asia/Almaty")
_MONDAY = date(2026, 11, 23)


def _utc_time(day: date, hour: int, minute: int = 0) -> str:
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=_ALMATY)
        .replace(hour=hour, minute=minute)
        .astimezone(UTC)
        .isoformat()
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _create_company(client: TestClient, bin_number: int) -> int:
    response = client.post(
        "/companies",
        json={
            "name": f"Test company {bin_number}",
            "bin": f"{bin_number:012d}",
            "phone": "+77001234567",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_meeting(
    client: TestClient,
    company_id: int,
    *,
    manager_id: int = 1,
    day: date = _MONDAY,
    hour: int = 10,
    minute: int = 0,
):
    return client.post(
        "/meetings",
        json={
            "company_id": company_id,
            "manager_id": manager_id,
            "start_time": _utc_time(day, hour, minute),
        },
    )


def test_meeting_workday_boundaries(client: TestClient) -> None:
    cases = [
        (_MONDAY, 9, 0, 201),
        (_MONDAY, 8, 59, 422),
        (_MONDAY, 17, 0, 201),
        (_MONDAY, 17, 1, 422),
        (_MONDAY, 17, 30, 422),
        (date(2026, 11, 28), 10, 0, 422),
        (date(2026, 11, 29), 10, 0, 422),
    ]

    for bin_number, (day, hour, minute, expected_status) in enumerate(cases, start=1):
        company_id = _create_company(client, bin_number)
        response = _create_meeting(
            client, company_id, day=day, hour=hour, minute=minute
        )
        assert response.status_code == expected_status, response.text
        if expected_status == 422:
            assert isinstance(response.json()["detail"], str)


def test_manager_overlap_is_rejected_but_adjacent_meetings_are_allowed(
    client: TestClient,
) -> None:
    first_company = _create_company(client, 101)
    overlap_company = _create_company(client, 102)
    adjacent_company = _create_company(client, 103)

    first = _create_meeting(client, first_company, hour=10)
    overlap = _create_meeting(client, overlap_company, hour=10, minute=30)
    adjacent = _create_meeting(client, adjacent_company, hour=11)

    assert first.status_code == 201, first.text
    assert overlap.status_code == 409
    assert "менеджера" in overlap.json()["detail"].lower()
    assert adjacent.status_code == 201, adjacent.text


def test_company_can_have_only_one_active_meeting(client: TestClient) -> None:
    company_id = _create_company(client, 201)
    first = _create_meeting(client, company_id, manager_id=1, hour=10)
    second = _create_meeting(client, company_id, manager_id=2, hour=13)

    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert "организации" in second.json()["detail"].lower()


def test_meeting_set_call_requires_a_valid_unlinked_company_meeting(
    client: TestClient,
) -> None:
    company_id = _create_company(client, 301)
    no_meeting = client.post(
        "/calls",
        json={"company_id": company_id, "manager_id": 1, "result": "meeting_set"},
    )
    assert no_meeting.status_code == 422

    another_company_id = _create_company(client, 302)
    another_meeting = _create_meeting(client, another_company_id)
    wrong_company = client.post(
        "/calls",
        json={
            "company_id": company_id,
            "manager_id": 1,
            "result": "meeting_set",
            "meeting_id": another_meeting.json()["id"],
        },
    )
    assert wrong_company.status_code == 422

    cancelled_company_id = _create_company(client, 303)
    cancelled_meeting = _create_meeting(client, cancelled_company_id, hour=11)
    cancelled = client.patch(
        f"/meetings/{cancelled_meeting.json()['id']}",
        json={"status": "cancelled"},
    )
    assert cancelled.status_code == 200
    cancelled_call = client.post(
        "/calls",
        json={
            "company_id": cancelled_company_id,
            "manager_id": 1,
            "result": "meeting_set",
            "meeting_id": cancelled_meeting.json()["id"],
        },
    )
    assert cancelled_call.status_code == 422

    valid_company_id = _create_company(client, 304)
    valid_meeting = _create_meeting(client, valid_company_id, hour=12)
    valid_call = client.post(
        "/calls",
        json={
            "company_id": valid_company_id,
            "manager_id": 1,
            "result": "meeting_set",
            "meeting_id": valid_meeting.json()["id"],
        },
    )
    assert valid_call.status_code == 201, valid_call.text
    assert valid_call.json()["meeting_id"] == valid_meeting.json()["id"]

    duplicate_call = client.post(
        "/calls",
        json={
            "company_id": valid_company_id,
            "manager_id": 1,
            "result": "meeting_set",
            "meeting_id": valid_meeting.json()["id"],
        },
    )
    assert duplicate_call.status_code == 422


def test_nested_meeting_is_created_atomically_with_call(client: TestClient) -> None:
    company_id = _create_company(client, 401)
    response = client.post(
        "/calls",
        json={
            "company_id": company_id,
            "manager_id": 1,
            "result": "meeting_set",
            "meeting": {"start_time": _utc_time(_MONDAY, 10)},
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["meeting_id"] is not None
    schedule = client.get(f"/managers/1/schedule?date={_MONDAY.isoformat()}").json()
    assert len(schedule["items"]) == 1


def test_reschedule_preserves_initial_time_and_releases_old_slot(
    client: TestClient,
) -> None:
    first_company = _create_company(client, 501)
    meeting = _create_meeting(client, first_company, hour=10).json()
    moved = client.patch(
        f"/meetings/{meeting['id']}",
        json={"start_time": _utc_time(_MONDAY, 12)},
    )

    assert moved.status_code == 200, moved.text
    assert _parse_datetime(moved.json()["start_time"]) == _parse_datetime(
        _utc_time(_MONDAY, 12)
    )
    assert _parse_datetime(moved.json()["initial_start_time"]) == _parse_datetime(
        _utc_time(_MONDAY, 10)
    )
    assert _parse_datetime(moved.json()["end_time"]) == _parse_datetime(
        _utc_time(_MONDAY, 13)
    )
    assert moved.json()["rescheduled_count"] == 1

    second_company = _create_company(client, 502)
    old_slot = _create_meeting(client, second_company, hour=10)
    assert old_slot.status_code == 201, old_slot.text


def test_cancellation_releases_manager_slot(client: TestClient) -> None:
    first_company = _create_company(client, 601)
    meeting = _create_meeting(client, first_company, hour=10).json()
    cancelled = client.patch(f"/meetings/{meeting['id']}", json={"status": "cancelled"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    second_company = _create_company(client, 602)
    available = _create_meeting(client, second_company, hour=10)
    assert available.status_code == 201, available.text


def test_naive_datetime_is_rejected(client: TestClient) -> None:
    company_id = _create_company(client, 701)
    response = client.post(
        "/meetings",
        json={
            "company_id": company_id,
            "manager_id": 1,
            "start_time": "2026-11-23T05:00:00",
        },
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_company_phone_formats_are_normalized(client: TestClient) -> None:
    phone_formats = [
        "+7 (700) 123-45-67",
        "7 700 123 45 67",
        "8 (700) 123-45-67",
    ]
    for bin_number, phone in enumerate(phone_formats, start=901):
        response = client.post(
            "/companies",
            json={
                "name": f"Phone format {bin_number}",
                "bin": f"{bin_number:012d}",
                "phone": phone,
            },
        )
        assert response.status_code == 201, response.text
        assert response.json()["phone"] == "+77001234567"


def test_invalid_company_phone_is_rejected(client: TestClient) -> None:
    for bin_number, phone in enumerate(
        ["+7700123456", "770012345678", "+8 700 123 45 67", "+7 700 ABC 45 67"],
        start=911,
    ):
        response = client.post(
            "/companies",
            json={
                "name": f"Invalid phone {bin_number}",
                "bin": f"{bin_number:012d}",
                "phone": phone,
            },
        )
        assert response.status_code == 422


def test_openapi_documents_endpoints_fields_and_error_body() -> None:
    from app.main import app

    spec = app.openapi()
    assert spec["info"]["title"] == "Внутренняя CRM — API звонков и встреч"
    create_call = spec["paths"]["/calls"]["post"]
    assert create_call["summary"] == "Записать результат звонка"
    assert "meeting_id" in create_call["description"]
    error_schema = create_call["responses"]["422"]["content"]["application/json"][
        "schema"
    ]
    assert error_schema["$ref"].endswith("/ErrorResponse")
    phone_schema = spec["components"]["schemas"]["CompanyCreate"]["properties"]["phone"]
    assert "результат хранится как" in phone_schema["description"]


def test_concurrent_requests_for_same_manager_slot_create_one_meeting(
    client: TestClient,
) -> None:
    first_company = _create_company(client, 801)
    second_company = _create_company(client, 802)

    def book(company_id: int) -> int:
        response = _create_meeting(client, company_id, hour=15)
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(book, [first_company, second_company]))

    assert sorted(statuses) == [201, 409]
