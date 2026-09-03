// Every write route in this app redirects back to (approximately) the same
// page the form was submitted from -- so a full page reload after a form
// submit resets the browser's scroll to the top, forcing the user to
// scroll back down to continue a long list of edits (Item Master, Kitchen
// Review, Tracker, Wastage...). This remembers the scroll position across
// that submit -> redirect -> reload cycle, then forgets it.
//
// Opt out on a specific form with class "js-no-scroll-restore" (e.g. login,
// where landing at the top of a new page is correct).
const SCROLL_KEY = "omnistock:scrollY";

document.addEventListener("submit", (e) => {
  if (e.target.classList.contains("js-no-scroll-restore")) return;
  sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
});

window.addEventListener("DOMContentLoaded", () => {
  const saved = sessionStorage.getItem(SCROLL_KEY);
  if (saved === null) return;
  sessionStorage.removeItem(SCROLL_KEY);
  const y = parseInt(saved, 10) || 0;
  if (y > 0) window.scrollTo(0, y);
});
