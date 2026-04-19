from app.resource.schemas import LearnerProfileSnapshot


def test_snapshot_preserves_profile_scores_and_user_identity():
    snapshot = LearnerProfileSnapshot.from_sources(
        user_data={"major": "计算机科学", "grade": "大二", "school": "某大学"},
        profile_data={
            "knowledge_level": "有离散数学基础，但网络协议掌握薄弱",
            "knowledge_level_score": 58,
            "cognitive_style": "偏好图解和案例驱动",
            "cognitive_style_score": 72,
            "profile_summary": "适合先图解再做题的复习路径",
        },
    )

    assert snapshot.major == "计算机科学"
    assert snapshot.grade == "大二"
    assert snapshot.school == "某大学"
    assert snapshot.knowledge_level_score == 58
    assert snapshot.cognitive_style == "偏好图解和案例驱动"
    assert snapshot.profile_summary == "适合先图解再做题的复习路径"

