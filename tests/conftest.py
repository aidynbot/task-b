"""Isolated PostgreSQL fixtures for API integration tests."""

import os
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Manager


@pytest.fixture(scope="session")
def test_engine():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "Set TEST_DATABASE_URL to the isolated PostgreSQL test database "
            "(for example, the test-db service in docker-compose.yml)."
        )
    database_name = make_url(database_url).database
    if database_name is None or "test" not in database_name.lower():
        raise RuntimeError(
            "TEST_DATABASE_URL must point to a database with 'test' in its name."
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(test_engine) -> Generator[None, None, None]:
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)

    def reset() -> None:
        with test_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE TABLE calls, meetings, companies, managers RESTART IDENTITY CASCADE"
                )
            )
        with session_factory.begin() as session:
            session.add_all(
                [
                    Manager(id=1, name="Manager 1"),
                    Manager(id=2, name="Manager 2"),
                    Manager(id=3, name="Manager 3"),
                ]
            )

    reset()
    yield
    reset()


@pytest.fixture
def client(test_engine) -> Generator[TestClient, None, None]:
    test_session_factory = sessionmaker(
        bind=test_engine, class_=Session, autoflush=False, expire_on_commit=False
    )

    def override_get_db() -> Generator[Session, None, None]:
        with test_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
