// Generic client-side search filter, shared by every searchable table on the
// dashboard (Spend/Usage by Ingredient, Period Comparison, Low Stock).
//
// Markup contract:
//   <input class="js-search-input" data-target="some-id" placeholder="Search item...">
//   <div id="some-id">
//     <tr class="js-search-row" data-search="lowercased item name">...</tr>
//     ...
//     <tr class="js-search-empty" hidden>No items match "...".</tr>
//   </div>
document.addEventListener("input", (e) => {
  if (!e.target.classList.contains("js-search-input")) return;
  const targetId = e.target.getAttribute("data-target");
  const container = document.getElementById(targetId);
  if (!container) return;
  const query = e.target.value.trim().toLowerCase();

  let visibleCount = 0;
  container.querySelectorAll(".js-search-row").forEach((row) => {
    const matches = row.getAttribute("data-search").includes(query);
    row.hidden = !matches;
    if (matches) visibleCount++;
  });

  const emptyRow = container.querySelector(".js-search-empty");
  if (emptyRow) {
    emptyRow.hidden = visibleCount > 0;
    const span = emptyRow.querySelector(".js-search-query");
    if (span) span.textContent = query;
  }
});
