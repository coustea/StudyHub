from app.resource.planning import build_default_resource_plan


def test_default_resource_plan_prioritizes_core_then_enhancement_then_presentation():
    plan = build_default_resource_plan(
        task={
            "course": "计算机网络",
            "gap": "TCP 三次握手理解不牢",
            "need": "review",
            "extra": "结合前端请求链路举例",
        },
        allowed_agents=None,
    )

    assert plan.core_agents == ["content", "mindmap", "quiz"]
    assert plan.enhancement_agents == ["reading", "code", "image"]
    assert plan.presentation_agents == ["ppt", "video"]
    assert plan.dependencies["image"] == ["content", "mindmap"]
    assert plan.dependencies["video"] == ["content", "image", "ppt"]
    assert plan.agent_parameters["content"]["course"] == "计算机网络"

