(function () {
  const chat = document.getElementById("assistant-chat");
  const form = document.getElementById("assistant-form");
  const input = document.getElementById("assistant-input");

  function addBubble(text, kind) {
    const bubble = document.createElement("div");
    bubble.className = `assistant-bubble assistant-bubble-${kind}`;
    bubble.textContent = text;
    chat.appendChild(bubble);
    chat.scrollTop = chat.scrollHeight;
  }

  function addPreviewText(parent, tagName, text, className) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function addReplenishmentBasis(card, recommendation) {
    if (!recommendation) return;
    const basis = document.createElement("div");
    basis.className = "assistant-replenishment-basis";
    addPreviewText(basis, "strong", "补货依据");
    const values = [
      ["当前库存", recommendation.current_stock],
      ["7 天销量", recommendation.sales_7d],
      ["日均销量", recommendation.avg_daily_sales_7d],
      ["库存覆盖", recommendation.coverage == null ? "近期无销量" : `${recommendation.coverage} 天`],
      ["待入库数量", recommendation.pending_purchase_qty],
      ["推荐补货", recommendation.recommended_purchase_qty],
    ];
    values.forEach(([label, value]) => {
      addPreviewText(basis, "div", `${label}：${value}`, "assistant-replenishment-basis-line");
    });
    card.appendChild(basis);
  }

  function addResponse(response) {
    if (response.type === "confirmation") {
      const card = document.createElement("div");
      card.className = "assistant-preview surface-card assistant-preview-card";
      const title = response.action === "create_purchase_order" ? "采购订单预览" : "销售订单预览";
      const party = response.preview.supplier_name || response.preview.customer_name;
      addPreviewText(card, "strong", title);
      addPreviewText(card, "div", party, "small text-muted mt-1");
      response.preview.items.forEach((item) => {
        const line = document.createElement("div");
        line.className = "assistant-preview-line";
        line.textContent = `${item.product_name} × ${item.quantity} · ${item.unit_price} 元 · 小计 ${item.subtotal} 元`;
        card.appendChild(line);
      });
      const total = document.createElement("div");
      total.className = "assistant-preview-total";
      total.textContent = `总金额：${response.preview.total_amount} 元`;
      card.appendChild(total);
      addReplenishmentBasis(card, response.preview.recommendation);
      const actions = document.createElement("div");
      actions.className = "assistant-preview-actions";
      const confirmButton = document.createElement("button");
      confirmButton.type = "button";
      confirmButton.className = "btn btn-primary btn-sm";
      confirmButton.textContent = "确认创建";
      confirmButton.addEventListener("click", () => confirmPreview(response.confirmation_token, "confirm"));
      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "btn btn-outline-secondary btn-sm";
      cancelButton.textContent = "取消";
      cancelButton.addEventListener("click", () => confirmPreview(response.confirmation_token, "cancel"));
      actions.append(confirmButton, cancelButton);
      card.appendChild(actions);
      chat.appendChild(card);
      return;
    }
    addBubble(response.content || response.message || "无法处理该请求。", response.type);
  }

  async function sendMessage(message) {
    addBubble(message, "user");
    const response = await fetch("/assistant/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    addResponse(await response.json());
  }

  async function confirmPreview(token, action) {
    const response = await fetch("/assistant/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_token: token, action }),
    });
    addResponse(await response.json());
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    sendMessage(message);
  });

  document.querySelectorAll(".assistant-example").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.textContent.trim();
      input.focus();
    });
  });
})();
