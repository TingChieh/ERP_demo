(function () {
  const chat = document.getElementById("assistant-chat");
  const form = document.getElementById("assistant-form");
  const input = document.getElementById("assistant-input");
  const documentInput = document.getElementById("assistant-document");

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

  function addExportDownload(response) {
    const data = response.data;
    if (!data || typeof data.download_url !== "string") return;

    let downloadUrl;
    try {
      downloadUrl = new URL(data.download_url, window.location.href);
    } catch (_) {
      return;
    }
    if (
      downloadUrl.origin !== window.location.origin ||
      !downloadUrl.pathname.startsWith("/exports/download/")
    ) return;

    const card = document.createElement("div");
    card.className = "assistant-preview surface-card assistant-preview-card";
    addPreviewText(card, "strong", "导出文件已准备好");
    const link = document.createElement("a");
    link.className = "btn btn-outline-primary btn-sm mt-3";
    link.href = downloadUrl.pathname;
    link.textContent = `下载 ${String(data.filename || "导出文件")}`;
    card.appendChild(link);
    chat.appendChild(card);
    chat.scrollTop = chat.scrollHeight;
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
    addExportDownload(response);
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

  async function sendDocument(question, file) {
    const prompt = question || "请总结并解读这个文件。";
    addBubble(`${prompt}\n附件：${file.name}`, "user");
    const formData = new FormData();
    formData.append("document", file);
    formData.append("question", question);

    try {
      const response = await fetch("/assistant/document", {
        method: "POST",
        body: formData,
      });
      const result = await response.json().catch(() => null);
      if (!result) {
        addBubble("文件解读失败，请稍后重试。", "error");
        return;
      }
      if (!response.ok && !result.type) {
        addBubble("文件解读失败，请稍后重试。", "error");
        return;
      }
      addResponse(result);
    } catch (_) {
      addBubble("无法连接 AI 助手，请稍后重试。", "error");
    }
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
    const file = documentInput.files[0];
    if (!message && !file) return;
    input.value = "";
    if (file) {
      sendDocument(message, file).finally(() => {
        documentInput.value = "";
      });
    } else {
      sendMessage(message);
    }
  });

  document.querySelectorAll(".assistant-example").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.textContent.trim();
      input.focus();
    });
  });
})();
