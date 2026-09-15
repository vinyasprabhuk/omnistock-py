// Daily Tracker (Admin only): the small pencil button next to each row's
// Issued figure opens dialog#issue-adjust-dialog, prefilled from the
// button's data-* attributes, to POST a correcting Stock Issue entry
// (see tracker.adjust_issued) without leaving the Tracker page.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".js-adjust-issued");
  if (!btn) return;

  const dialog = document.getElementById("issue-adjust-dialog");
  if (!dialog) return;

  dialog.querySelector("#issue-adjust-item-id").value = btn.dataset.itemId;
  dialog.querySelector("#issue-adjust-item-name").textContent = btn.dataset.itemName;
  dialog.querySelector("#issue-adjust-current").textContent = `${btn.dataset.current} ${btn.dataset.unit}`;
  dialog.querySelector("#issue-adjust-unit").textContent = btn.dataset.unit;
  dialog.querySelector('[name="departmentName"]').value = "";
  dialog.querySelector('[name="qty"]').value = "";
  dialog.showModal();
});

document.addEventListener("click", (e) => {
  if (e.target.matches(".js-close-dialog")) {
    e.target.closest("dialog").close();
  }
});
