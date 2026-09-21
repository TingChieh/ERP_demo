import json
import os
from time import perf_counter
from typing import Protocol

from flask import has_app_context
from openai import OpenAI

from services.logging import record_api_call

from .schemas import ToolCall


class LLMConfigurationError(RuntimeError):
    pass


class LLMResponseError(RuntimeError):
    pass


class LLMClient(Protocol):
    def parse_message(self, message, *, system_prompt, tools):
        ...


class MockLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def parse_message(self, message, *, system_prompt, tools):
        self.calls.append(
            {"message": message, "system_prompt": system_prompt, "tools": tools}
        )
        if not self.responses:
            raise LLMResponseError("Mock LLM 没有更多响应")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class DeepSeekLLMClient:
    def __init__(self, api_key=None, model=None, base_url=None, client=None):
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.base_url = base_url or os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        )
        self.client = client
        if self.client is None and self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _record_call(
        self,
        *,
        started,
        status,
        message,
        tools,
        response=None,
        tool_name=None,
        error_message=None,
        http_status=None,
    ):
        if not has_app_context():
            return
        usage = getattr(response, "usage", None)
        record_api_call(
            provider="deepseek",
            model=self.model,
            endpoint=f"{self.base_url.rstrip('/')}/chat/completions",
            request_id=getattr(response, "id", None),
            status=status,
            http_status=http_status,
            duration_ms=(perf_counter() - started) * 1000,
            tool_name=tool_name,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
            detail={
                "message_chars": len(message),
                "tool_count": len(tools or []),
                "response_type": "tool_call" if tool_name else "text",
            },
            error_message=error_message,
        )

    def parse_message(self, message, *, system_prompt, tools):
        started = perf_counter()
        if self.client is None:
            self._record_call(
                started=started,
                status="configuration_error",
                message=message,
                tools=tools,
                error_message="未配置 DeepSeek API Key",
            )
            raise LLMConfigurationError("未配置 DeepSeek API Key")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
        except Exception as exc:
            response = getattr(exc, "response", None)
            self._record_call(
                started=started,
                status="error",
                message=message,
                tools=tools,
                http_status=getattr(response, "status_code", None),
                error_message=str(exc)[:500],
            )
            raise LLMResponseError(f"DeepSeek 请求失败：{exc}") from exc

        try:
            choices = response.choices
            if not choices:
                raise LLMResponseError("DeepSeek 返回为空")
            assistant_message = choices[0].message
        except (AttributeError, IndexError) as exc:
            raise LLMResponseError("DeepSeek 响应格式无效") from exc

        tool_calls = getattr(assistant_message, "tool_calls", None) or []
        if len(tool_calls) > 1:
            raise LLMResponseError("一次请求返回了多个工具调用")
        if tool_calls:
            function = tool_calls[0].function
            raw_arguments = getattr(function, "arguments", None)
            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise LLMResponseError("工具调用参数 JSON 无效") from exc
            if not isinstance(arguments, dict):
                raise LLMResponseError("工具调用参数必须是对象")
            result = ToolCall(name=function.name, arguments=arguments)
            self._record_call(
                started=started,
                status="success",
                message=message,
                tools=tools,
                response=response,
                tool_name=result.name,
                http_status=200,
            )
            return result

        content = getattr(assistant_message, "content", None)
        if not content or not str(content).strip():
            raise LLMResponseError("DeepSeek 没有返回可用内容")
        self._record_call(
            started=started,
            status="success",
            message=message,
            tools=tools,
            response=response,
            http_status=200,
        )
        return str(content).strip()
