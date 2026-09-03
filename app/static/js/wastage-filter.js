// Filters the Wastage/Production entry list by item name, hiding any
// meal-period group that ends up with zero visible rows, and shows a
// running "N of M entries" count.
//
// Markup contract:
//   <input class="js-wastage-filter" data-target="wastage-entries">
//   <span class="js-wastage-count"></span>
//   <div id="wastage-entries">
//     <div class="js-entry-group">
//       <div class="js-entry-row" data-search="lowercased description">...</div>
//       ...
//     </div>
//   </div>
document.addEventListener("input", (e) => {
  if (!e.target.classList.contains("js-wastage-filter")) return;
  const container = document.getElementById(e.target.getAttribute("data-target"));
  if (!container) return;
  const query = e.target.value.trim().toLowerCase();

  let visible = 0;
  const total = container.querySelectorAll(".js-entry-row").length;
  container.querySelectorAll(".js-entry-group").forEach((group) => {
    let groupVisible = 0;
    group.querySelectorAll(".js-entry-row").forEach((row) => {
      const match = row.getAttribute("data-search").includes(query);
      row.hidden = !match;
      if (match) { groupVisible++; visible++; }
    });
    group.hidden = groupVisible === 0;
  });

  const countEl = document.querySelector(".js-wastage-count");
  if (countEl) {
    countEl.textContent = query ? `${visible} of ${total} entr${total === 1 ? "y" : "ies"}` : "";
  }
});
