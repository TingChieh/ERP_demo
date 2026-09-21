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

  function addResponse(response) {
    if (response.type === "confirmation") {
      const card = document.createElement("div");
      card.className = "assistant-preview surface-card assistant-preview-card";
      const title = response.action === "create_purchase_order" ? "采购订单预览" : "销售订单预览";
      const party = response.preview.supplier_name || response.preview.customer_name;
      card.innerHTML = `<strong>${title}</strong><div class="small text-muted mt-1">${party}</div>`;
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
      const actions = document.createElement("div");
      actions.className = "assistant-preview-actions";
      actions.innerHTML = '<button type="button" class="btn btn-primary btn-sm">确认创建</button><button type="button" class="btn btn-outline-secondary btn-sm">取消</button>';
      const buttons = actions.querySelectorAll("button");
      buttons[0].addEventListener("click", () => confirmPreview(response.confirmation_token, "confirm"));
      buttons[1].addEventListener("click", () => confirmPreview(response.confirmation_token, "cancel"));
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
