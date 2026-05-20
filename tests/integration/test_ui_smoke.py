from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from fastapi import FastAPI


def test_dashboard_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


def test_users_list_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/users")
    assert response.status_code == 200
    assert "Users" in response.text


def test_combined_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/combined")
    assert response.status_code == 200
    assert "Combinadas" in response.text


def test_settings_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/settings")
    assert response.status_code == 200
    assert "Settings" in response.text


def test_activity_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/activity")
    assert response.status_code == 200
    assert "Actividad" in response.text


def test_endpoints_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/endpoints")
    assert response.status_code == 200
    assert "Endpoints" in response.text


def test_combined_new_sublist_form_renders(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/combined/sublists/new")
    assert response.status_code == 200
    assert "Nueva sublista combinada" in response.text
