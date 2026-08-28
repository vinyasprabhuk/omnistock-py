// Repeatable line-item rows for the Purchase/Stock Issue forms.
//
// Markup contract:
//   <table>
//     <tbody id="some-id">...initial <tr> rows...</tbody>
//   </table>
//   <template id="some-id-template"><tr>...one blank row...</tr></template>
//   <button type="button" class="js-add-line" data-target="some-id">+ Add line</button>
//
// Each row's remove control is a button with class "js-remove-line".
document.addEventListener("click", (e) => {
  const addBtn = e.target.closest(".js-add-line");
  if (addBtn) {
    const targetId = addBtn.getAttribute("data-target");
    const tbody = document.getElementById(targetId);
    const template = document.getElementById(`${targetId}-template`);
    if (tbody && template) {
      const clone = template.content.cloneNode(true);
      tbody.appendChild(clone);
    }
    return;
  }

  const removeBtn = e.target.closest(".js-remove-line");
  if (removeBtn) {
    const row = removeBtn.closest("tr");
    const tbody = row && row.parentElement;
    if (tbody && tbody.querySelectorAll("tr").length > 1) {
      row.remove();
    }
  }
});

// Unit auto-populate: selecting an item (via a <select class="js-item-select">
// whose <option>s carry data-unit="...") fills in the read-only unit display
// in that same row (a cell with class "js-unit-display"). Delegated so it
// works on rows cloned in later via the +Add line handler above.
document.addEventListener("change", (e) => {
  if (!e.target.classList.contains("js-item-select")) return;
  const row = e.target.closest("tr");
  if (!row) return;
  const unitDisplay = row.querySelector(".js-unit-display");
  if (!unitDisplay) return;
  const selectedOption = e.target.options[e.target.selectedIndex];
  unitDisplay.textContent = selectedOption ? selectedOption.getAttribute("data-unit") || "" : "";
});
