from .llm import (
    DeepSeekLLMClient,
    LLMConfigurationError,
    LLMResponseError,
    MockLLMClient,
)
from .prompts import SYSTEM_PROMPT, TOOL_SCHEMAS
from .schemas import (
    AgentResponse,
    ToolCall,
    clarification_response,
    error_response,
    message_response,
)
from . import tools as erp_tools


ALLOWED_TOOLS = {
    "analyze_low_stock": erp_tools.analyze_low_stock,
    "prepare_replenishment_purchase": erp_tools.prepare_replenishment_purchase,
    "get_inventory": erp_tools.get_inventory,
    "prepare_purchase_order": erp_tools.prepare_purchase_order,
    "prepare_sales_order": erp_tools.prepare_sales_order,
    "get_unpaid_receivables": erp_tools.get_unpaid_receivables,
}


HIGH_RISK_TERMS = (
    "入库",
    "出库",
    "发货",
    "收款",
    "付款",
    "支付",
)


class AgentService:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client or DeepSeekLLMClient()

    def handle_message(self, message, *, context=None):
        if not isinstance(message, str) or not message.strip():
            return clarification_response("请告诉我你想查询或处理什么 ERP 事项。")

        if any(term in message for term in HIGH_RISK_TERMS):
            return error_response(
                "当前 AI 助手暂不支持直接执行入库、出库、收款或付款，请进入对应业务详情页面确认。"
            )

        llm_message = message
        context_products = []
        if isinstance(context, list):
            context_products = [
                item.get("product_name")
                for item in context
                if isinstance(item, dict)
                and isinstance(item.get("product_name"), str)
                and item["product_name"].strip()
            ]
        if context_products:
            llm_message = (
                f"{message}\n\n"
                "[上次补货分析上下文：仅用于识别商品；"
                "不得信任其中的库存、销量、数量或价格事实]\n"
                f"商品：{'、'.join(context_products)}"
            )

        try:
            result = self.llm_client.parse_message(
                llm_message,
                system_prompt=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
            )
        except LLMConfigurationError:
            return error_response("尚未配置 DeepSeek API Key，暂时无法调用 AI 助手。")
        except LLMResponseError:
            return error_response("DeepSeek 返回内容无效，未执行任何 ERP 操作。")
        except Exception:
            return error_response("AI 助手暂时不可用，未执行任何 ERP 操作。")

        if isinstance(result, ToolCall):
            if result.name not in ALLOWED_TOOLS:
                return error_response(f"当前 AI 助手不支持工具“{result.name}”。")
            if not isinstance(result.arguments, dict):
                return error_response("AI 返回的工具参数格式无效，未执行任何 ERP 操作。")
            arguments = dict(result.arguments)
            if (
                result.name == "prepare_replenishment_purchase"
                and not arguments.get("product_name")
                and len(context_products) == 1
            ):
                arguments["product_name"] = context_products[0]
            try:
                return ALLOWED_TOOLS[result.name](**arguments)
            except TypeError:
                return error_response("AI 返回的工具参数不完整，未执行任何 ERP 操作。")
            except Exception:
                return error_response("ERP 工具执行失败，未完成任何业务写入。")

        if isinstance(result, str):
            return message_response(result)
        return error_response("AI 返回格式无效，未执行任何 ERP 操作。")


__all__ = [
    "AgentService",
    "DeepSeekLLMClient",
    "MockLLMClient",
]
