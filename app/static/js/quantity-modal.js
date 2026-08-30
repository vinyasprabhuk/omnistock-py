// Wastage/Production quick-entry modal, backed by a native <dialog>.
//
// Markup contract: buttons with class "js-open-entry" and data-attributes
// data-meal, data-dish (empty string for "+ Other"), data-piece-counted
// ("1"/"") open dialog#entry-dialog, filling in its hidden/visible fields.
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".js-open-entry");
  if (!btn) return;

  const dialog = document.getElementById("entry-dialog");
  if (!dialog) return;

  const meal = btn.getAttribute("data-meal");
  const dish = btn.getAttribute("data-dish") || "";
  const pieceCounted = btn.getAttribute("data-piece-counted") === "1";

  dialog.querySelector('[name="mealPeriod"]').value = meal;
  dialog.querySelector('[name="dish"]').value = dish;
  dialog.querySelector(".entry-title").textContent = dish || "Other item";
  dialog.querySelector(".entry-meal-label").textContent = meal.charAt(0) + meal.slice(1).toLowerCase();

  const customField = dialog.querySelector(".js-custom-name-field");
  const customInput = customField.querySelector("input");
  if (dish) {
    customField.hidden = true;
    customInput.required = false;
  } else {
    customField.hidden = false;
    customInput.required = true;
    customInput.value = "";
  }

  const piecesField = dialog.querySelector(".js-pieces-field");
  const weightField = dialog.querySelector(".js-weight-field");
  const piecesInput = piecesField.querySelector("input");
  const weightInput = weightField.querySelector("input");
  if (pieceCounted) {
    piecesField.hidden = false;
    weightField.hidden = true;
    piecesInput.required = true;
    weightInput.required = false;
  } else {
    piecesField.hidden = true;
    weightField.hidden = false;
    piecesInput.required = false;
    weightInput.required = true;
  }

  if (window.resetEntryCamera) window.resetEntryCamera(dialog);
  dialog.showModal();
});

document.addEventListener("click", (e) => {
  if (e.target.matches(".js-close-dialog")) {
    e.target.closest("dialog").close();
  }
});
