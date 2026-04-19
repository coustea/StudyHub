import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from app.resource.agents.ppt.tools.save_ppt_file import SlideContent, _classify_slide


def test_classify_slide_uses_statement_layout_for_hook_slide():
    content = SlideContent(callouts=["为什么 TCP 不能只用两次握手？"])

    assert _classify_slide("引入问题", content) == "statement"
