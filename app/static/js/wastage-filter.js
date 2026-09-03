// Filters the Wastage/Production entry list to one selected item, hiding
// any meal-period group that ends up with zero visible rows, and shows
// that item's total (Produced or Wasted, depending on the page's mode) --
// summed from each visible row's data-kg/data-pieces.
//
// Markup contract:
//   <select class="js-wastage-filter" data-target="wastage-entries" data-mode-label="Produced">
//     <option value="">All items</option>
//     <option value="Exact Item Name">Exact Item Name</option>
//   </select>
//   <span class="js-wastage-count"></span>
//   <div id="wastage-entries">
//     <div class="js-entry-group">
//       <div class="js-entry-row" data-item="Exact Item Name" data-kg="1.5" data-pieces="">...</div>
//       ...
//     </div>
//   </div>
document.addEventListener("change", (e) => {
  if (!e.target.classList.contains("js-wastage-filter")) return;
  const select = e.target;
  const container = document.getElementById(select.getAttribute("data-target"));
  if (!container) return;
  const selected = select.value;
  const countEl = document.querySelector(".js-wastage-count");

  if (!selected) {
    container.querySelectorAll(".js-entry-row").forEach((row) => { row.hidden = false; });
    container.querySelectorAll(".js-entry-group").forEach((group) => { group.hidden = false; });
    if (countEl) countEl.textContent = "";
    return;
  }

  let totalKg = 0;
  let totalPieces = 0;
  let hasKg = false;
  let hasPieces = false;

  container.querySelectorAll(".js-entry-group").forEach((group) => {
    let groupVisible = 0;
    group.querySelectorAll(".js-entry-row").forEach((row) => {
      const match = row.getAttribute("data-item") === selected;
      row.hidden = !match;
      if (!match) return;
      groupVisible++;
      const kg = row.getAttribute("data-kg");
      const pieces = row.getAttribute("data-pieces");
      if (kg) { totalKg += parseFloat(kg) || 0; hasKg = true; }
      if (pieces) { totalPieces += parseInt(pieces, 10) || 0; hasPieces = true; }
    });
    group.hidden = groupVisible === 0;
  });

  if (countEl) {
    const label = select.getAttribute("data-mode-label") || "Total";
    const parts = [];
    if (hasKg) parts.push(`${totalKg.toFixed(2)} KG`);
    if (hasPieces) parts.push(`${totalPieces} pcs`);
    countEl.textContent = `Total ${label}: ${parts.length ? parts.join(" + ") : "0"}`;
  }
});
