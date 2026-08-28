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
