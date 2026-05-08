// Dark Mode Toggle Functionality
(function () {
  const currentTheme = localStorage.getItem('theme') || 'light';
  const root = document.documentElement;
  const body = document.body;

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    body.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }

  applyTheme(currentTheme);

  function buildThemeToggle(id) {
    const toggle = document.createElement('button');
    toggle.id = id;
    toggle.className = 'theme-toggle';
    toggle.type = 'button';
    toggle.setAttribute('aria-label', 'Toggle dark mode');
    toggle.innerHTML = `
      <span class="theme-toggle-icon sun">☀️</span>
      <span class="theme-toggle-icon moon">🌙</span>
    `;
    return toggle;
  }

  function toggleTheme() {
    const current = root.getAttribute('data-theme') || 'light';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  }

  function attachToggle(button) {
    if (!button) return;
    button.removeEventListener('click', toggleTheme);
    button.addEventListener('click', toggleTheme);
  }

  const existingToggle = document.getElementById('theme-toggle');
  if (existingToggle) {
    attachToggle(existingToggle);
  }

  if (!existingToggle) {
    const navActions = document.querySelector('.nav-actions');
    if (navActions) {
      const themeToggle = buildThemeToggle('theme-toggle');
      attachToggle(themeToggle);
      const logoutLink = navActions.querySelector('a[href="/logout"]');
      if (logoutLink) {
        navActions.insertBefore(themeToggle, logoutLink);
      } else {
        navActions.appendChild(themeToggle);
      }
    }
  }

  const adminSidebar = document.getElementById('admin-sidebar');
  if (adminSidebar) {
    let sidebarToggle = document.getElementById('sidebar-theme-toggle');
    if (!sidebarToggle) {
      const sidebarLogoutLink = adminSidebar.querySelector('a[href="/logout"]');
      if (sidebarLogoutLink) {
        sidebarToggle = buildThemeToggle('sidebar-theme-toggle');
        attachToggle(sidebarToggle);
        sidebarLogoutLink.parentNode.insertBefore(sidebarToggle, sidebarLogoutLink);
      }
    } else {
      attachToggle(sidebarToggle);
    }
  }
})();

document.addEventListener("DOMContentLoaded", () => {
  const toggleBtn = document.getElementById("chatbot-toggle");
  const closeBtn = document.getElementById("chatbot-close");
  const hint = document.getElementById("chatbot-hint");
  const panel = document.getElementById("chatbot-panel");
  const chatForm = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const messages = document.getElementById("chat-messages");
  const quickActionsWrap = document.querySelector(".chat-quick-actions");
  const currentProductId = document.body?.dataset?.currentProductId || null;
  const history = [];

  function escapeHtml(text = "") {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatBotText(text = "") {
    const safe = escapeHtml(text);
    const lines = safe.split("\n").filter(Boolean);

    if (lines.length <= 1) {
      return `<div class="msg-text">${safe}</div>`;
    }

    const first = lines.shift();
    const listItems = lines.map((line) => `<li>${line.replace(/^-\s*/, "")}</li>`).join("");
    return `
      <div class="msg-text">${first}</div>
      <ul class="msg-list">${listItems}</ul>
    `;
  }

  function addMessage(text, cls) {
    if (!messages) return;
    const div = document.createElement("div");
    div.className = cls;

    if (cls.includes("bot")) {
      div.innerHTML = formatBotText(text);
    } else {
      div.innerHTML = `<div class="msg-text">${escapeHtml(text)}</div>`;
    }

    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    history.push({ role: cls.includes("user") ? "user" : "assistant", content: text });
    if (history.length > 12) history.shift();
  }

  function addTyping() {
    if (!messages) return;
    removeTyping();
    const div = document.createElement("div");
    div.className = "bot-msg typing-msg";
    div.id = "typing-msg";
    div.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function removeTyping() {
    const typing = document.getElementById("typing-msg");
    if (typing) typing.remove();
  }

  function openChat() {
    if (panel) panel.classList.remove("hidden");
    if (hint) hint.classList.add("hidden");
    if (input) input.focus();
  }

  function closeChat() {
    if (panel) panel.classList.add("hidden");
  }

  function renderQuickActions(actions = []) {
    if (!quickActionsWrap) return;
    quickActionsWrap.innerHTML = "";

    actions.forEach((action) => {
      const btn = document.createElement("button");
      btn.className = "chip-btn";
      btn.type = "button";
      btn.textContent = action.label || "Ask";

      if (action.chat) {
        btn.addEventListener("click", () => {
          openChat();
          sendMessage(action.chat);
        });
      } else if (action.ticket) {
        btn.addEventListener("click", () => {
          openChat();
          raiseTicket(action.ticket);
        });
      }

      quickActionsWrap.appendChild(btn);
    });
  }

  async function sendMessage(prefilledText = null) {
    const text = prefilledText || input?.value?.trim();
    if (!text) return;

    addMessage(text, "user-msg");
    if (input) input.value = "";
    addTyping();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          current_product_id: currentProductId,
          history
        })
      });

      const data = await response.json().catch(() => ({}));
      removeTyping();
      addMessage(data.response || "Sorry, I could not process that.", "bot-msg");
      renderQuickActions(data.quick_actions || []);
    } catch (e) {
      removeTyping();
      addMessage("Sorry, something went wrong. Please try again.", "bot-msg");
    }
  }

  async function raiseTicket(message) {
    addMessage(message, "user-msg");
    addTyping();

    try {
      const response = await fetch("/api/raise-ticket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          current_product_id: currentProductId,
          history
        })
      });

      const data = await response.json().catch(() => ({}));
      removeTyping();
      addMessage(data.response || "Your request has been submitted.", "bot-msg");
      renderQuickActions(data.quick_actions || []);
    } catch (e) {
      removeTyping();
      addMessage("Unable to raise a ticket right now.", "bot-msg");
    }
  }

  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      if (panel?.classList.contains("hidden")) {
        openChat();
      } else {
        closeChat();
      }
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener("click", closeChat);
  }

  if (chatForm) {
    chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      sendMessage();
    });
  }

  renderQuickActions([
    { label: "Black shirts", chat: "Recommend black shirts" },
    { label: "Track orders", chat: "Track my orders" },
    { label: "Track tickets", chat: "Track my tickets" },
    { label: "Trending", chat: "Show trending products" }
  ]);

  window.setTimeout(() => {
    if (hint && panel?.classList.contains("hidden")) {
      hint.classList.remove("hidden");
    }
  }, 1200);
});
