// On the Kitchen "edit an approved requirement" screen, reveals a
// required reason field for any item row whose qty has been changed from
// its original committed value -- unchanged rows need no reason.
//
// Markup contract:
//   <div class="js-edit-row">
//     <input class="js-edit-qty" data-original-qty="4" value="4">
//     <div class="js-edit-reason-field" hidden><input name="reason"></div>
//   </div>
document.addEventListener("input", (e) => {
  if (!e.target.classList.contains("js-edit-qty")) return;
  const row = e.target.closest(".js-edit-row");
  if (!row) return;
  const reasonField = row.querySelector(".js-edit-reason-field");
  if (!reasonField) return;

  const original = parseFloat(e.target.getAttribute("data-original-qty")) || 0;
  const current = parseFloat(e.target.value) || 0;
  const changed = Math.abs(current - original) > 1e-9;

  reasonField.hidden = !changed;
  const reasonInput = reasonField.querySelector("input");
  if (reasonInput) reasonInput.required = changed;
});
