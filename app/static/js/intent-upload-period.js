// Intent page's "Upload sale reports" period picker (Day/Week/Month) is
// purely a labeling aid -- every file is still exactly one day's report
// internally (see intent.upload_sales / load_dish_sales_file), this just
// swaps the hint text so the user knows how many files to select.
document.addEventListener("change", (e) => {
  if (e.target.name !== "uploadPeriodChoice") return;
  const hint = document.querySelector(".js-upload-period-hint");
  if (!hint) return;
  hint.textContent = hint.dataset[`hint${e.target.value.charAt(0).toUpperCase()}${e.target.value.slice(1)}`];
});
