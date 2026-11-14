from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.message import Message
from app.models.task import Task


async def _auth_headers(
    client: AsyncClient,
    *,
    username: str,
    email: str,
    password: str = "StrongPassword123!",
) -> dict[str, str]:
    """测试辅助函数：注册并登录用户，返回 Bearer 鉴权请求头。"""
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert reg_res.status_code == 201

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"identifier": username, "password": password},
    )
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_project_crud_and_cascade_delete(
    client: AsyncClient,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers = await _auth_headers(client, username="proj_owner", email="owner@example.com")

    p1_res = await client.post(
        "/api/v1/projects",
        json={"title": "  B+ 树插入原理  "},
        headers=headers,
    )
    assert p1_res.status_code == 201
    p1 = p1_res.json()
    assert p1["title"] == "B+ 树插入原理"
    assert p1["current_revision"] == 0

    p2_res = await client.post(
        "/api/v1/projects",
        json={"title": "Raft 一致性算法"},
        headers=headers,
    )
    assert p2_res.status_code == 201
    p2 = p2_res.json()

    list_res = await client.get("/api/v1/projects?limit=1&offset=0", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["total"] == 2
    assert len(list_res.json()["items"]) == 1

    get_res = await client.get(f"/api/v1/projects/{p1['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == p1["id"]

    patch_res = await client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"title": "B+ 树分裂动画", "current_revision": 2},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "B+ 树分裂动画"
    assert patch_res.json()["current_revision"] == 2

    # 在 p1 下创建消息和任务，验证删除项目会级联清理子记录
    msg_res = await client.post(
        f"/api/v1/projects/{p1['id']}/messages",
        json={"role": "user", "content": "讲解 B+ 树叶子节点分裂"},
        headers=headers,
    )
    assert msg_res.status_code == 201
    msg_id = msg_res.json()["id"]

    task_res = await client.post(
        f"/api/v1/projects/{p1['id']}/tasks",
        json={"type": "create", "request_message_id": msg_id},
        headers=headers,
    )
    assert task_res.status_code == 201

    del_res = await client.delete(f"/api/v1/projects/{p1['id']}", headers=headers)
    assert del_res.status_code == 204

    missing_res = await client.get(f"/api/v1/projects/{p1['id']}", headers=headers)
    assert missing_res.status_code == 404

    async with async_session_factory() as session:
        rem_msgs = (
            await session.exec(select(Message).where(Message.project_id == p1["id"]))
        ).all()
        rem_tasks = (
            await session.exec(select(Task).where(Task.project_id == p1["id"]))
        ).all()
        assert rem_msgs == []
        assert rem_tasks == []

    # 确认 p2 未受影响
    p2_get = await client.get(f"/api/v1/projects/{p2['id']}", headers=headers)
    assert p2_get.status_code == 200


async def test_message_and_task_crud(client: AsyncClient) -> None:
    headers = await _auth_headers(client, username="crud_user", email="crud@example.com")

    proj_a = (
        await client.post("/api/v1/projects", json={"title": "快速排序"}, headers=headers)
    ).json()
    proj_b = (
        await client.post("/api/v1/projects", json={"title": "归并排序"}, headers=headers)
    ).json()

    # 消息 CRUD
    m1_res = await client.post(
        f"/api/v1/projects/{proj_a['id']}/messages",
        json={
            "role": "user",
            "content": "讲解快速排序分区过程",
            "metadata": {"duration_seconds": 90, "resolution": "1920x1080"},
        },
        headers=headers,
    )
    assert m1_res.status_code == 201
    m1 = m1_res.json()
    assert m1["metadata"] == {"duration_seconds": 90, "resolution": "1920x1080"}

    m2_res = await client.post(
        f"/api/v1/projects/{proj_a['id']}/messages",
        json={"role": "assistant", "content": "已规划 4 个分镜"},
        headers=headers,
    )
    assert m2_res.status_code == 201

    msg_list = await client.get(f"/api/v1/projects/{proj_a['id']}/messages", headers=headers)
    assert msg_list.status_code == 200
    assert msg_list.json()["total"] == 2
    assert [item["role"] for item in msg_list.json()["items"]] == ["user", "assistant"]

    msg_get = await client.get(f"/api/v1/messages/{m1['id']}", headers=headers)
    assert msg_get.status_code == 200
    assert msg_get.json()["content"] == "讲解快速排序分区过程"

    msg_patch = await client.patch(
        f"/api/v1/messages/{m1['id']}",
        json={"content": "讲解双指针快排", "metadata": {"duration_seconds": 120}},
        headers=headers,
    )
    assert msg_patch.status_code == 200
    assert msg_patch.json()["content"] == "讲解双指针快排"
    assert msg_patch.json()["metadata"] == {"duration_seconds": 120}

    # 任务 CRUD
    # 不能跨项目引用消息
    cross_task = await client.post(
        f"/api/v1/projects/{proj_b['id']}/tasks",
        json={"type": "create", "request_message_id": m1["id"]},
        headers=headers,
    )
    assert cross_task.status_code == 404

    t1_res = await client.post(
        f"/api/v1/projects/{proj_a['id']}/tasks",
        json={"type": "create", "request_message_id": m1["id"], "base_revision": 0},
        headers=headers,
    )
    assert t1_res.status_code == 201
    t1 = t1_res.json()
    assert t1["status"] == "pending"
    assert t1["phase"] == "pending"
    assert t1["progress"] == 0
    assert t1["request_message_id"] == m1["id"]

    t2_res = await client.post(
        f"/api/v1/projects/{proj_a['id']}/tasks",
        json={"type": "edit", "base_revision": 1},
        headers=headers,
    )
    assert t2_res.status_code == 201

    task_patch = await client.patch(
        f"/api/v1/tasks/{t1['id']}",
        json={
            "status": "running",
            "phase": "render",
            "progress": 80,
        },
        headers=headers,
    )
    assert task_patch.status_code == 200
    assert task_patch.json()["status"] == "running"
    assert task_patch.json()["phase"] == "render"
    assert task_patch.json()["progress"] == 80

    # 按状态过滤任务列表
    running_list = await client.get(
        f"/api/v1/projects/{proj_a['id']}/tasks?status=running",
        headers=headers,
    )
    assert running_list.status_code == 200
    assert running_list.json()["total"] == 1
    assert running_list.json()["items"][0]["id"] == t1["id"]

    # 删除关联消息后，任务中的 request_message_id 置空而任务保留
    del_msg = await client.delete(f"/api/v1/messages/{m1['id']}", headers=headers)
    assert del_msg.status_code == 204

    t1_after_msg_del = await client.get(f"/api/v1/tasks/{t1['id']}", headers=headers)
    assert t1_after_msg_del.status_code == 200
    assert t1_after_msg_del.json()["request_message_id"] is None

    del_task = await client.delete(f"/api/v1/tasks/{t1['id']}", headers=headers)
    assert del_task.status_code == 204
    assert (await client.get(f"/api/v1/tasks/{t1['id']}", headers=headers)).status_code == 404


async def test_resource_ownership_isolation_returns_404(client: AsyncClient) -> None:
    headers_a = await _auth_headers(client, username="alice_iso", email="alice_iso@example.com")
    headers_b = await _auth_headers(client, username="bob_iso", email="bob_iso@example.com")

    proj_a = (
        await client.post("/api/v1/projects", json={"title": "Alice 的项目"}, headers=headers_a)
    ).json()
    msg_a = (
        await client.post(
            f"/api/v1/projects/{proj_a['id']}/messages",
            json={"role": "user", "content": "讲解 TCP 三次握手"},
            headers=headers_a,
        )
    ).json()
    task_a = (
        await client.post(
            f"/api/v1/projects/{proj_a['id']}/tasks",
            json={"type": "create", "request_message_id": msg_a["id"]},
            headers=headers_a,
        )
    ).json()

    # 用户 B 对用户 A 的所有资源操作均统一返回 404
    assert (
        await client.get(f"/api/v1/projects/{proj_a['id']}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/projects/{proj_a['id']}",
            json={"title": "篡改"},
            headers=headers_b,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/projects/{proj_a['id']}", headers=headers_b)
    ).status_code == 404

    assert (
        await client.post(
            f"/api/v1/projects/{proj_a['id']}/messages",
            json={"role": "user", "content": "越权写入"},
            headers=headers_b,
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{proj_a['id']}/messages", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/messages/{msg_a['id']}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/messages/{msg_a['id']}",
            json={"content": "越权修改"},
            headers=headers_b,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/messages/{msg_a['id']}", headers=headers_b)
    ).status_code == 404

    assert (
        await client.post(
            f"/api/v1/projects/{proj_a['id']}/tasks",
            json={"type": "create"},
            headers=headers_b,
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{proj_a['id']}/tasks", headers=headers_b)
    ).status_code == 404
    assert (await client.get(f"/api/v1/tasks/{task_a['id']}", headers=headers_b)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/tasks/{task_a['id']}",
            json={"status": "failed"},
            headers=headers_b,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/tasks/{task_a['id']}", headers=headers_b)
    ).status_code == 404
