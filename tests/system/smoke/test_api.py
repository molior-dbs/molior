"""API smoke tests: the server answers, login and permissions work, basic objects can be created.
No mirror and no build is needed."""
from conftest import Api, ADMIN_PASSWORD


def test_status_is_public(public):
    r = public.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["version_molior_server"]
    assert data["maintenance_mode"] is False


def test_openapi_docs(public):
    assert public.get("/api2/openapi.json").status_code == 200
    assert public.get("/api2/docs").status_code == 200


def test_login_fails_with_wrong_password(public):
    r = public.post("/api/login", json={"username": "admin", "password": ADMIN_PASSWORD + "x"})
    assert r.status_code == 400


def test_api_needs_login(public):
    r = public.get("/api/userinfo")
    assert r.status_code == 200 and r.json() is None  # null when not logged in (no 401 on the login page)
    assert public.get("/api/projects").status_code == 401


def test_admin_login_and_logout(admin):
    r = admin.get("/api/userinfo")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["is_admin"] is True
    assert admin.get("/api/logout").status_code == 200
    assert admin.get("/api/userinfo").json() is None


def test_lists_answer(admin):
    for path in ["/api/projects", "/api/mirrors", "/api/builds", "/api/repositories", "/api/users",
                 "/api/projectversions", "/api/buildstates", "/api2/tokens"]:
        r = admin.get(path)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"


def test_create_user_and_login(admin, unique):
    name = unique("user")
    r = admin.post("/api/users", json={"name": name, "email": f"{name}@example.com", "password": "pw-" + name})
    assert r.status_code == 200, r.text
    user = Api().login(name, "pw-" + name)
    info = user.get("/api/userinfo").json()
    assert info["username"] == name
    assert info["is_admin"] is False
    # a normal user may not create projects
    assert user.post("/api/projects", json={"name": unique("proj")}).status_code == 403


def test_create_project_and_permissions(admin, unique):
    project, name = unique("proj"), unique("user")
    assert admin.post("/api/projects", json={"name": project, "description": "smoke"}).status_code == 200
    assert admin.post("/api/projects", json={"name": project}).status_code == 400  # name taken

    r = admin.get(f"/api2/projectbase/{project}")
    assert r.status_code == 200
    assert r.json()["name"] == project
    assert admin.get(f"/api2/projectbase/{project}/versions").json()["total_result_count"] == 0

    admin.post("/api/users", json={"name": name, "email": f"{name}@example.com", "password": "pw-" + name})
    r = admin.post(f"/api2/projectbase/{project}/permissions", json={"username": name, "role": "member"})
    assert r.status_code == 200, r.text
    roles = admin.get(f"/api2/projectbase/{project}/permissions").json()["results"]
    assert [(x["username"], x["role"]) for x in roles] == [(name, "member")]

    # a member is not owner: may not add permissions
    member = Api().login(name, "pw-" + name)
    r = member.post(f"/api2/projectbase/{project}/permissions", json={"username": name, "role": "owner"})
    assert r.status_code == 403

    assert admin.delete(f"/api2/projectbase/{project}").status_code == 200
    assert admin.get(f"/api2/projectbase/{project}").status_code == 404
    assert admin.delete(f"/api2/projectbase/{project}").status_code == 400


def test_project_version_needs_a_base_mirror(admin, unique):
    project = unique("proj")
    admin.post("/api/projects", json={"name": project})
    r = admin.post(f"/api2/projectbase/{project}/versions",
                   json={"name": "1.0", "architectures": ["amd64"], "basemirror": "nomirror/1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Base mirror not found: nomirror/1"
    r = admin.post(f"/api2/projectbase/{project}/versions",
                   json={"name": "1.0", "architectures": ["amd64"], "baseproject": "noproject/1"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Base project not found: noproject/1"


def test_global_token(admin, unique):
    description = unique("token")
    r = admin.post("/api2/tokens", json={"description": description})
    assert r.status_code == 200
    raw = r.json()["token"]
    tokens = admin.get("/api2/tokens", params={"description": description}).json()["results"]
    assert len(tokens) == 1

    # the token may create a project
    bot = Api(headers={"X-MoliorToken": raw})
    project = unique("proj")
    assert bot.post("/api/projects", json={"name": project}).status_code == 200

    assert admin.delete("/api2/tokens", json={"id": tokens[0]["id"]}).status_code == 200
    assert bot.post("/api/projects", json={"name": unique("proj")}).status_code == 401
