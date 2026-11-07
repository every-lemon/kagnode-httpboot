/* KagNode HTTP Boot: existing authority operations, no synthetic Client data. */
(() => {
  const $ = (id) => document.getElementById(id),
    pages = {
      overview: [
        "Overview",
        "Review your Server, Clients, and recent boot health.",
      ],
      clients: [
        "Clients",
        "Review pairing requests and assign existing Client accounts.",
      ],
      accounts: [
        "Client accounts",
        "Accounts available from the HTTP Boot authority.",
      ],
      images: [
        "Images & kernels",
        "Inspect published images, kernel versions and architecture.",
      ],
      reports: [
        "Boot reports",
        "Read the latest retained, sanitized Client diagnostics.",
      ],
      access: [
        "Console access",
        "Manage access to this browser without interrupting Clients.",
      ],
    };
  const key = "kagnode.httpboot.console";
  let token = "",
    state = null,
    timer = null,
    pending = false,
    choicesReady = false,
    generation = 0,
    lastRender = "",
    accountSignature = "";
  let editingClient = null;
  const node = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  };
  const empty = (box, text) => {
    box.replaceChildren(node("p", text, "empty"));
  };
  function closeNavigation() {
    document.body.classList.remove("mobile-open");
    $("sidebar-scrim").hidden = true;
    $("mobile-menu").setAttribute("aria-expanded", "false");
  }
  function route() {
    const part = location.pathname.replace(/^\//, "") || "overview";
    return Object.hasOwn(pages, part) ? part : "overview";
  }
  function view() {
    const id = route(),
      [title, description] = pages[id];
    $("page-title").textContent = title;
    $("topbar-title").textContent = title;
    $("page-description").textContent = description;
    document.title = title + " · KagNode. HTTP Boot";
    document
      .querySelectorAll("[data-view]")
      .forEach((e) => (e.hidden = e.dataset.view !== id));
    document.querySelectorAll(".sidebar [data-route]").forEach((a) => {
      if (a.pathname === "/" + id) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    closeNavigation();
  }
  function feedback(message) {
    $("page-feedback").textContent = message;
    $("page-feedback").hidden = !message;
  }
  function lock() {
    generation++;
    token = "";
    state = null;
    lastRender = "";
    choicesReady = false;
    accountSignature = "";
    pending = false;
    $("refresh").disabled = false;
    clearTimeout(timer);
    try {
      sessionStorage.removeItem(key);
      sessionStorage.removeItem("token");
    } catch {}
    $("workspace").hidden = true;
    $("connect-screen").hidden = false;
    $("console-token").value = "";
    $("assignment-dialog").close();
    $("assignment-choices").replaceChildren();
    $("assignment-client").textContent = "";
    $("assignment-feedback").textContent = "";
    editingClient = null;
    $("connect-error").hidden = true;
    closeNavigation();
    $("console-token").focus();
  }
  async function call(path, data) {
    const response = await fetch(path, {
      method: data ? "POST" : "GET",
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/json",
        ...(data ? { "Content-Type": "application/json" } : {}),
      },
      body: data ? JSON.stringify(data) : undefined,
      signal: AbortSignal.timeout(15000),
      redirect: "error",
    });
    const result = await response.json();
    if (!response.ok) {
      const error = Error(
        result.error ||
          result.message ||
          "The Server could not complete the request.",
      );
      error.status = response.status;
      throw error;
    }
    return result;
  }
  function table(headers, rows) {
    const wrap = node("div", undefined, "table-scroll");
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute("aria-label", headers.join(", "));
    const t = node("table"),
      head = node("thead"),
      tr = node("tr"),
      body = node("tbody");
    for (const h of headers) tr.append(node("th", h));
    head.append(tr);
    for (const values of rows) {
      const row = node("tr");
      for (const value of values) {
        const cell = node("td");
        cell.append(
          value instanceof Node
            ? value
            : document.createTextNode(String(value)),
        );
        row.append(cell);
      }
      body.append(row);
    }
    t.append(head, body);
    wrap.append(t);
    return wrap;
  }
  function clientName(client) {
    try {
      const data = JSON.parse(client.hardware || "{}");
      return data.product_name || data.model || data.architecture || "Client";
    } catch {
      return "Client";
    }
  }
  function render() {
    if (!state) return;
    const clients = state.clients || [],
      accounts = state.accounts || [],
      reports = state.reports || [];
    const now = Date.now() / 1000;
    $("approved-count").textContent = clients.filter((c) => c.approved).length;
    $("pending-count").textContent = clients.filter(
      (c) => !c.approved && c.expires > now,
    ).length;
    $("account-count").textContent = accounts.length;
    $("report-count").textContent = reports.length;
    $("server-health").textContent = state.health;
    $("last-checked").textContent =
      "Checked " + new Date().toLocaleTimeString();
    $("ui-version").textContent = state.console_version || "";
    $("authority-version").textContent =
      state.authority_version || "HTTP Boot Server";
    $("connection-status").textContent = "Connected";
    const boot = $("boot-health");
    if (state.boothealth && Object.keys(state.boothealth).length) {
      const wasOpen = !!boot.querySelector("details[open]");
      const details = node("details"),
        summary = node("summary", "View boot health"),
        pre = node("pre", JSON.stringify(state.boothealth, null, 2));
      details.open = wasOpen;
      details.append(summary, pre);
      boot.replaceChildren(details);
    } else empty(boot, "No Client boot health is available yet.");
    $("client-list-count").textContent = clients.length + " registered";
    const rows = clients.map((client) => {
      const name = node("div"),
        strong = node("strong", clientName(client), "table-main"),
        id = node("small", client.id, "table-detail");
      name.append(strong, id);
      const approved = !!client.approved,
        expired = !approved && client.expires <= now,
        status = node(
          "span",
          approved ? "Approved" : expired ? "Expired" : "Awaiting approval",
          "status-badge" + (approved ? "" : " pending"),
        );
      const action = approved
        ? node("button", "Manage accounts", "button")
        : expired
          ? node("span", "Start pairing again on the Client", "small muted")
          : node("button", "Review pairing", "button");
      if (!approved && !expired)
        action.onclick = () => {
          $("pairing-code").value = client.code;
          $("pairing-code").focus();
          $("approve-form").scrollIntoView({
            behavior: matchMedia("(prefers-reduced-motion:reduce)").matches
              ? "instant"
              : "smooth",
            block: "center",
          });
        };
      if (approved)
        action.onclick = () => {
          editingClient = client.id;
          $("assignment-client").textContent =
            clientName(client) + " · " + client.id;
          $("assignment-feedback").textContent = "";
          $("assignment-choices").replaceChildren();
          for (const account of accounts) {
            const label = node("label", undefined, "account-choice"),
              input = node("input");
            input.type = "checkbox";
            input.value = account.name;
            input.checked = (client.accounts || []).includes(account.name);
            label.append(input, node("span", account.name));
            $("assignment-choices").append(label);
          }
          $("assignment-dialog").showModal();
        };
      return [
        name,
        status,
        approved
          ? (client.accounts || []).join(", ") || "No accounts assigned"
          : client.code,
        action,
      ];
    });
    if (rows.length)
      $("client-list").replaceChildren(
        table(["Client", "Status", "Accounts / pairing code", "Action"], rows),
      );
    else
      empty(
        $("client-list"),
        "No Clients have registered. Start a Client to create its pairing request.",
      );
    if (accounts.length)
      $("account-list").replaceChildren(
        table(
          ["Account", "Client privilege"],
          accounts.map((a) => [
            a.name,
            a.system_admin ? "Administrator" : "Standard account",
          ]),
        ),
      );
    else
      empty(
        $("account-list"),
        "No Client accounts have been created yet. Use the local Server account tools first.",
      );
    if (accountSignature !== JSON.stringify(accounts)) {
      accountSignature = JSON.stringify(accounts);
      const selected = new Set(
        [...$("account-choices").querySelectorAll("input:checked")].map(
          (e) => e.value,
        ),
      );
      $("account-choices").replaceChildren();
      for (const account of accounts) {
        const label = node("label", undefined, "account-choice"),
          input = node("input"),
          text = node("span"),
          name = node("strong", account.name),
          role = node(
            "small",
            account.system_admin ? "Administrator" : "Standard account",
          );
        input.type = "checkbox";
        input.value = account.name;
        input.checked = choicesReady
          ? selected.has(account.name)
          : (state.defaults || []).includes(account.name);
        text.append(name, role);
        label.append(input, text);
        $("account-choices").append(label);
      }
      choicesReady = true;
      if (!accounts.length)
        empty(
          $("account-choices"),
          "Create a Client account on the Server before assigning it.",
        );
    }
    const images = state.images || [];
    if (images.length)
      $("image-list").replaceChildren(
        table(
          ["Release", "Status", "Kernel", "Architecture", "Artifacts"],
          images.map((i) => [
            i.release,
            i.active ? "Current" : "Retained",
            i.kernel,
            i.architecture,
            (i.size / 1024 ** 3).toFixed(2) + " GiB",
          ]),
        ),
      );
    else empty($("image-list"), "No published image records are available.");
    $("report-list").replaceChildren();
    const term = $("report-filter").value.trim().toLowerCase();
    for (const report of reports.filter(
      (r) => !term || JSON.stringify(r).toLowerCase().includes(term),
    )) {
      const details = node("details", undefined, "report-card"),
        summary = node("summary"),
        title = node(
          "strong",
          String(report.stage || "Boot report").replaceAll("-", " "),
        ),
        status = node(
          "span",
          report.exit_status === 0
            ? "Completed"
            : "Exit status " + report.exit_status,
          "status-badge" + (report.exit_status === 0 ? "" : " pending"),
        ),
        pre = node("pre", JSON.stringify(report, null, 2));
      summary.append(title, status);
      details.append(summary, pre);
      const save = node("button", "Download report", "button");
      save.type = "button";
      save.onclick = () => {
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(report, null, 2)], {
              type: "application/json",
            }),
          ),
          a = node("a");
        a.href = url;
        a.download = "kagnode-boot-report.json";
        document.body.append(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      };
      details.append(save);
      $("report-list").append(details);
    }
    if (!$("report-list").children.length)
      empty(
        $("report-list"),
        reports.length
          ? "No reports match this filter."
          : "No recent diagnostic reports are retained. New Client reports will appear here.",
      );
  }
  async function refresh() {
    if (pending || !token) return;
    const epoch = generation;
    pending = true;
    $("refresh").disabled = true;
    clearTimeout(timer);
    try {
      const next = await call("/api/state");
      if (epoch !== generation || !token) return false;
      state = next;
      try {
        sessionStorage.setItem(key, token);
        sessionStorage.removeItem("token");
      } catch {}
      $("connect-error").hidden = true;
      $("connect-screen").hidden = true;
      $("workspace").hidden = false;
      $("loading").hidden = true;
      feedback("");
      const fingerprint = JSON.stringify({
        clients: state.clients,
        accounts: state.accounts,
        reports: state.reports,
        boothealth: state.boothealth,
        expired: (state.clients || []).map(
          (c) => !c.approved && c.expires <= Date.now() / 1000,
        ),
      });
      if (fingerprint !== lastRender) {
        lastRender = fingerprint;
        render();
      } else
        $("last-checked").textContent =
          "Checked " + new Date().toLocaleTimeString();
      return true;
    } catch (error) {
      if (epoch !== generation) return false;
      if (!state) {
        token = "";
        try {
          sessionStorage.removeItem(key);
          sessionStorage.removeItem("token");
        } catch {}
        $("connect-error").textContent =
          error.status === 400 || error.status === 401
            ? "The console credential was not accepted."
            : error.message;
        $("connect-error").hidden = false;
        return false;
      }
      feedback(
        "Status could not refresh. The last successful view is retained.",
      );
      if (error.status === 401) lock();
    } finally {
      if (epoch === generation) {
        pending = false;
        $("refresh").disabled = false;
        if (token && !document.hidden) timer = setTimeout(refresh, 10000);
      }
    }
  }
  $("connect-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    generation++;
    pending = false;
    token = $("console-token").value.trim();
    const button = event.currentTarget.querySelector("[type=submit]");
    button.disabled = true;
    try {
      if (await refresh()) {
        try {
          sessionStorage.setItem(key, token);
        } catch {}
        $("console-token").value = "";
      } else token = "";
    } finally {
      button.disabled = false;
    }
  });
  $("report-filter").addEventListener("input", () => render());
  $("assignment-close").onclick = () => $("assignment-dialog").close();
  $("assignment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('[type="submit"]'),
      epoch = generation;
    if (!editingClient) return;
    button.disabled = true;
    $("assignment-feedback").textContent = "Saving account access…";
    try {
      await call("/api/assignments", {
        device: editingClient,
        accounts: [
          ...$("assignment-choices").querySelectorAll("input:checked"),
        ].map((i) => i.value),
      });
      if (epoch !== generation) return;
      $("assignment-dialog").close();
      await refresh();
      feedback("Client account access updated.");
    } catch (error) {
      if (epoch === generation)
        $("assignment-feedback").textContent = error.status
          ? error.message
          : "Outcome unconfirmed. Refresh status before retrying.";
    } finally {
      button.disabled = false;
    }
  });
  $("approve-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const accounts = [
      ...$("account-choices").querySelectorAll("input:checked"),
    ].map((e) => e.value);
    if (!accounts.length) {
      $("approve-feedback").textContent =
        "Choose at least one existing account.";
      return;
    }
    const epoch = generation;
    const button = event.currentTarget.querySelector("[type=submit]");
    button.disabled = true;
    $("approve-feedback").textContent = "Approving Client…";
    try {
      await call("/api/approve", {
        code: $("pairing-code").value.trim().toUpperCase(),
        accounts,
      });
      if (epoch !== generation) return;
      $("approve-feedback").textContent =
        "Client approved and accounts assigned.";
      $("pairing-code").value = "";
      await refresh();
    } catch (error) {
      if (epoch !== generation) return;
      $("approve-feedback").textContent = error.status
        ? error.message
        : "Approval outcome is unconfirmed. Refresh status before trying again.";
    } finally {
      button.disabled = false;
    }
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-route]");
    if (
      link &&
      !event.metaKey &&
      !event.ctrlKey &&
      !event.shiftKey &&
      !event.altKey
    ) {
      event.preventDefault();
      history.pushState(null, "", link.pathname);
      view();
      $("page-title").tabIndex = -1;
      $("page-title").focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    }
  });
  addEventListener("popstate", view);
  $("refresh").onclick = refresh;
  $("lock-console").onclick = lock;
  $("access-lock").onclick = lock;
  $("reveal-token").onclick = () => {
    const show = $("console-token").type === "password";
    $("console-token").type = show ? "text" : "password";
    $("reveal-token").textContent = show ? "Hide" : "Show";
    $("reveal-token").setAttribute(
      "aria-label",
      (show ? "Hide" : "Show") + " console credential",
    );
  };
  $("mobile-menu").onclick = () => {
    document.body.classList.add("mobile-open");
    $("sidebar-scrim").hidden = false;
    $("mobile-menu").setAttribute("aria-expanded", "true");
  };
  $("sidebar-scrim").onclick = closeNavigation;
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeNavigation();
  });
  try {
    const theme = localStorage.getItem("kagnode.theme");
    if (["light", "dark"].includes(theme))
      document.documentElement.dataset.theme = theme;
  } catch {}
  $("theme-toggle").onclick = () => {
    const next =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("kagnode.theme", next);
    } catch {}
  };
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden && token) refresh();
  });
  addEventListener("pagehide", () => clearTimeout(timer));
  const fragment = location.hash.slice(1);
  if (fragment) history.replaceState(null, "", location.pathname);
  try {
    token = /^[A-Za-z0-9_-]{32,100}$/.test(fragment)
      ? fragment
      : sessionStorage.getItem(key) || sessionStorage.getItem("token") || "";
  } catch {}
  if (location.pathname === "/") history.replaceState(null, "", "/overview");
  view();
  if (token) refresh();
})();
