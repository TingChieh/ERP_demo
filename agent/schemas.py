from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP


def format_money(value):
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:.2f}"


@dataclass
class AgentResponse:
    type: str
    content: str | None = None
    message: str | None = None
    candidates: list[dict] = field(default_factory=list)
    data: dict | None = None
    action: str | None = None
    preview: dict | None = None
    payload: dict | None = None
    confirmation_token: str | None = None

    def to_dict(self):
        result = {"type": self.type}
        if self.content is not None:
            result["content"] = self.content
        if self.message is not None:
            result["message"] = self.message
        if self.candidates:
            result["candidates"] = self.candidates
        if self.data is not None:
            result["data"] = self.data
        if self.action is not None:
            result["action"] = self.action
        if self.preview is not None:
            result["preview"] = self.preview
        if self.confirmation_token is not None:
            result["confirmation_token"] = self.confirmation_token
        return result


@dataclass
class ToolCall:
    name: str
    arguments: dict


def message_response(content, data=None):
    return AgentResponse(type="message", content=content, data=data)


def clarification_response(message, candidates=None, data=None):
    return AgentResponse(
        type="clarification",
        message=message,
        candidates=candidates or [],
        data=data,
    )


def confirmation_response(action, preview, payload):
    return AgentResponse(
        type="confirmation",
        action=action,
        preview=preview,
        payload=payload,
    )


def error_response(message):
    return AgentResponse(type="error", message=message)
