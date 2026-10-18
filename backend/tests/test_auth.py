from fastapi.testclient import TestClient

LOGIN = {"username": "tester", "password": "test-password"}


def test_me_requires_login(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_login_sets_session_cookie_and_allows_me(client: TestClient) -> None:
    response = client.post("/api/auth/login", json=LOGIN)

    assert response.status_code == 200
    assert response.json() == {"username": "tester"}
    set_cookie = response.headers["set-cookie"].lower()
    assert "mystock_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert client.get("/api/auth/me").json() == {"username": "tester"}


def test_login_rejects_wrong_password_without_cookie(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={**LOGIN, "password": "wrong"})

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 401


def test_login_rejects_wrong_username(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={**LOGIN, "username": "someone"})

    assert response.status_code == 401


def test_logout_ends_session(client: TestClient) -> None:
    client.post("/api/auth/login", json=LOGIN)

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_without_login_is_ok(client: TestClient) -> None:
    assert client.post("/api/auth/logout").status_code == 204
