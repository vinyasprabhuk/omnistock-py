// Safety net for the Request Regular/Extra Items qty-entry screen: typed
// quantities are cached to localStorage as the user types, and restored if
// the page reloads (accidental refresh, tab closed and reopened, etc.)
// before they click "Save Department". Save Department itself still writes
// straight to the server as always -- this only protects unsaved typing,
// and the cached draft is cleared the moment a save is actually submitted.
//
// Markup contract:
//   <form class="js-qty-draft" data-draft-key="...">
//     <input class="js-qty-input" data-item-id="..." type="number">
//   </form>
document.querySelectorAll(".js-qty-draft").forEach((form) => {
  const key = form.dataset.draftKey;
  if (!key) return;

  let draft = {};
  try {
    draft = JSON.parse(localStorage.getItem(key) || "{}");
  } catch (e) {
    draft = {};
  }

  form.querySelectorAll(".js-qty-input").forEach((input) => {
    const itemId = input.dataset.itemId;
    if (itemId && draft[itemId] !== undefined && !input.value) {
      input.value = draft[itemId];
    }
  });

  form.addEventListener("input", (e) => {
    if (!e.target.classList.contains("js-qty-input")) return;
    const itemId = e.target.dataset.itemId;
    if (!itemId) return;
    if (e.target.value === "") {
      delete draft[itemId];
    } else {
      draft[itemId] = e.target.value;
    }
    try {
      localStorage.setItem(key, JSON.stringify(draft));
    } catch (e) {
      // Storage full or unavailable (private mode) -- the draft just
      // won't survive a reload; the actual Save Department submit is
      // unaffected either way.
    }
  });

  form.addEventListener("submit", () => {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      // Nothing to clean up if storage isn't available.
    }
  });
});
