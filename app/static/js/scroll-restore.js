// Every write route in this app redirects back to (approximately) the same
// page the form was submitted from -- so a full page reload after a form
// submit resets the browser's scroll to the top, forcing the user to
// scroll back down to continue a long list of edits (Item Master, Kitchen
// Review, Tracker, Wastage...). This remembers the scroll position across
// that submit -> redirect -> reload cycle, then forgets it.
//
// Same idea for a plain link click that just changes query params on the
// SAME page (filter/date-range/tab links, e.g. the Dashboard's chart date
// pickers) -- those are also "approximately the same page", just re-scoped,
// so losing scroll position there is the same bug. A link to a genuinely
// different page (main nav, etc.) should still land at the top, so this
// only fires when the clicked link's pathname matches the current page's.
//
// Opt out on a specific form/link with class "js-no-scroll-restore" (e.g.
// login, where landing at the top of a new page is correct).
const SCROLL_KEY = "omnistock:scrollY";

function saveScroll() {
  sessionStorage.setItem(SCROLL_KEY, String(window.scrollY));
}

document.addEventListener("submit", (e) => {
  if (e.target.classList.contains("js-no-scroll-restore")) return;
  saveScroll();
});

document.addEventListener("click", (e) => {
  if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  const link = e.target.closest("a[href]");
  if (!link || link.closest(".js-no-scroll-restore")) return;
  if (link.target === "_blank" || link.hasAttribute("download")) return;
  const href = link.getAttribute("href");
  if (!href || href.startsWith("#") || href.startsWith("javascript:") ||
      href.startsWith("mailto:") || href.startsWith("tel:")) return;
  let url;
  try { url = new URL(href, window.location.href); } catch { return; }
  if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) return;
  saveScroll();
});

window.addEventListener("DOMContentLoaded", () => {
  const saved = sessionStorage.getItem(SCROLL_KEY);
  if (saved === null) return;
  sessionStorage.removeItem(SCROLL_KEY);
  const y = parseInt(saved, 10) || 0;
  if (y > 0) window.scrollTo(0, y);
});
