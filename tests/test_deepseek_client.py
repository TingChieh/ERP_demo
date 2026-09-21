from types import SimpleNamespace

import pytest

from agent.schemas import ToolCall
from agent.service import AgentService
from agent.llm import DeepSeekLLMClient, LLMConfigurationError, LLMResponseError, MockLLMClient


class FakeDeepSeekClient:
    def __init__(self, response):
        self.response = response
        self.last_request = None

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.last_request = kwargs
        return self.response


def tool_response(name, arguments):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(name=name, arguments=arguments)
                        )
                    ],
                )
            )
        ]
    )


def text_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=[]))]
    )


def test_deepseek_client_builds_function_call_request():
    fake = FakeDeepSeekClient(
        tool_response("get_inventory", '{"product_name": "机械键盘", "sku": null}')
    )
    client = DeepSeekLLMClient(
        api_key="test-key",
        model="deepseek-chat",
        base_url="https://example.test",
        client=fake,
    )

    result = client.parse_message(
        "查库存",
        system_prompt="你是 ERP 助手。",
        tools=[{"type": "function", "function": {"name": "get_inventory"}}],
    )

    assert result == ToolCall(
        name="get_inventory", arguments={"product_name": "机械键盘", "sku": None}
    )
    assert fake.last_request["model"] == "deepseek-chat"
    assert fake.last_request["tool_choice"] == "auto"
    assert fake.last_request["tools"][0]["function"]["name"] == "get_inventory"
    assert fake.last_request["messages"][0] == {
        "role": "system",
        "content": "你是 ERP 助手。",
    }


def test_deepseek_client_returns_plain_text_when_no_tool_call():
    fake = FakeDeepSeekClient(text_response("请告诉我商品名称。"))
    client = DeepSeekLLMClient(api_key="test-key", client=fake)

    result = client.parse_message("查库存", system_prompt="系统提示", tools=[])

    assert result == "请告诉我商品名称。"


def test_deepseek_client_rejects_malformed_tool_arguments():
    fake = FakeDeepSeekClient(tool_response("get_inventory", "not-json"))
    client = DeepSeekLLMClient(api_key="test-key", client=fake)

    with pytest.raises(LLMResponseError, match="参数"):
        client.parse_message("查库存", system_prompt="系统提示", tools=[])


def test_deepseek_client_requires_api_key_without_injected_client():
    client = DeepSeekLLMClient(api_key="")

    with pytest.raises(LLMConfigurationError, match="API Key"):
        client.parse_message("查库存", system_prompt="系统提示", tools=[])


def test_agent_service_rejects_unknown_action_without_running_business_logic():
    service = AgentService(
        MockLLMClient([ToolCall(name="unknown_action", arguments={})])
    )

    response = service.handle_message("执行未知动作")

    assert response.type == "error"
    assert "不支持" in response.message


def test_agent_service_rejects_malformed_tool_arguments():
    service = AgentService(
        MockLLMClient([ToolCall(name="get_inventory", arguments="not-a-dict")])
    )

    response = service.handle_message("查库存")

    assert response.type == "error"
    assert "参数" in response.message


def test_agent_service_refuses_high_risk_operation():
    service = AgentService(MockLLMClient(["把 PO20260921001 入库"]))

    response = service.handle_message("把 PO20260921001 入库")

    assert response.type == "error"
    assert "暂不支持" in response.message
