// Recipe page: typing a quantity (kg or pax) into a recipe card swaps its
// full-batch table for that recipe scaled to the quantity, with a cost per
// ingredient and the total food cost. The math lives on the server
// (GET /recipe/<id>/scale, see services/recipe_scaling.py) so it matches
// Production/Wastage exactly -- this file only fetches and draws.
(function () {
  const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const money = (n) => "₹" + inr.format(n);
  const qtyText = (n) => String(Number(n.toFixed(3)));

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function row(cells, isHeader) {
    const tr = el("tr");
    cells.forEach((c) => {
      const td = el(isHeader ? "th" : "td", c.text, c.className);
      if (c.colSpan) td.colSpan = c.colSpan;
      if (c.hint) td.appendChild(el("div", c.hint, "text-muted")).style.fontSize = "0.75rem";
      tr.appendChild(td);
    });
    return tr;
  }

  // Three columns, not five: the rate rides under the ingredient name and
  // the unit sits with the qty, so Cost stays on screen on a phone.
  function render(data) {
    const table = el("table");
    const thead = el("thead");
    thead.appendChild(row([{ text: "Ingredient" }, { text: "Qty" }, { text: "Cost", className: "num" }], true));
    table.appendChild(thead);

    const tbody = el("tbody");
    data.lines.forEach((line) => {
      let hint;
      if (!line.matched) hint = "No item match";
      else if (line.price == null) hint = "No price set";
      else hint = money(line.price) + (line.unit ? " / " + line.unit : "");
      tbody.appendChild(row([
        { text: line.name, hint },
        { text: qtyText(line.qty) + (line.unit ? " " + line.unit : "") },
        { text: line.cost == null ? "—" : money(line.cost), className: "num" },
      ]));
    });
    table.appendChild(tbody);

    const tfoot = el("tfoot");
    tfoot.appendChild(row([{ text: "Total food cost", colSpan: 2 }, { text: money(data.totalCost), className: "num" }]));
    tfoot.firstChild.style.fontWeight = "700";
    table.appendChild(tfoot);
    return table;
  }

  function note(data) {
    const unit = data.mode === "kg" ? "kg" : "pax";
    const times = Number(data.multiplier.toFixed(2));
    let text = `Scaled to ${qtyText(data.amount)} ${unit} (${times}× the full batch).`;
    if (data.uncostedCount) {
      const n = data.uncostedCount;
      text += ` ${n} ingredient${n === 1 ? "" : "s"} couldn't be priced (no item match or no price), so the total is partial.`;
    }
    return text;
  }

  const timers = new WeakMap();
  const requestIds = new WeakMap();

  function refresh(card) {
    const value = card.querySelector(".js-scale-value").value.trim();
    const mode = card.querySelector(".js-scale-mode").value;
    const result = card.querySelector(".js-scale-result");
    const message = card.querySelector(".js-scale-message");
    const fullBatch = card.querySelector(".js-full-batch");

    function showFullBatch(msg) {
      result.hidden = true;
      fullBatch.hidden = false;
      message.hidden = !msg;
      message.textContent = msg || "";
    }

    if (!value || Number(value) <= 0) { showFullBatch(""); return; }

    const id = (requestIds.get(card) || 0) + 1;
    requestIds.set(card, id);
    const url = `/recipe/${encodeURIComponent(card.dataset.recipeId)}/scale?mode=${encodeURIComponent(mode)}&value=${encodeURIComponent(value)}`;
    fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        if (requestIds.get(card) !== id) return; // a newer keystroke superseded this response
        if (!ok) { showFullBatch(body.error || "Couldn't scale this recipe."); return; }
        result.replaceChildren(render(body));
        result.hidden = false;
        fullBatch.hidden = true;
        message.hidden = false;
        message.textContent = note(body);
      })
      .catch(() => {
        if (requestIds.get(card) === id) showFullBatch("Couldn't reach the server -- try again.");
      });
  }

  function schedule(card) {
    clearTimeout(timers.get(card));
    timers.set(card, setTimeout(() => refresh(card), 250));
  }

  document.addEventListener("input", (e) => {
    if (e.target.matches(".js-scale-value")) schedule(e.target.closest(".rcard"));
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches(".js-scale-mode")) refresh(e.target.closest(".rcard"));
  });
})();
