// Opening Stock tile grid: tap a tile -> dialog with a big qty input ->
// AJAX save (updates the tile in place, no full reload) -- plus a voice
// button that transcribes speech client-side (Web Speech API, no audio
// ever leaves the browser) and sends only the resulting text to the
// server to fuzzy-match against Item Master (name + aliases), same
// matcher Excel imports use.
//
// Markup contract: .js-open-os-entry tiles carry data-item-id/-name/
// -unit/-qty; #os-entry-dialog has #os-entry-title, #os-entry-current,
// #os-entry-qty, #os-entry-error, and #os-entry-form posts via fetch to
// /opening-stock/<id>/save.
(function () {
  const dialog = document.getElementById("os-entry-dialog");
  const form = document.getElementById("os-entry-form");
  const titleEl = document.getElementById("os-entry-title");
  const currentEl = document.getElementById("os-entry-current");
  const qtyInput = document.getElementById("os-entry-qty");
  const errorEl = document.getElementById("os-entry-error");
  if (!dialog || !form) return;

  let activeTile = null;

  function openFor(tile) {
    activeTile = tile;
    const name = tile.dataset.itemName;
    const unit = tile.dataset.itemUnit;
    const qty = tile.dataset.itemQty;
    titleEl.textContent = name;
    currentEl.textContent = `Currently: ${qty} ${unit}`;
    qtyInput.value = qty;
    errorEl.hidden = true;
    form.dataset.itemId = tile.dataset.itemId;
    dialog.showModal();
    qtyInput.focus();
    qtyInput.select();
  }

  document.addEventListener("click", (e) => {
    const tile = e.target.closest(".js-open-os-entry");
    if (tile) openFor(tile);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const itemId = form.dataset.itemId;
    const csrf = form.querySelector('[name="_csrf_token"]').value;
    const branchId = form.querySelector('[name="branchId"]').value;
    const qty = qtyInput.value;

    const body = new URLSearchParams({ _csrf_token: csrf, branchId, qty });
    let resp;
    try {
      resp = await fetch(`/opening-stock/${itemId}/save`, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-Requested-With": "XMLHttpRequest",
        },
        body,
      });
    } catch (err) {
      errorEl.textContent = "Network error -- check your connection and try again.";
      errorEl.hidden = false;
      return;
    }

    const data = await resp.json().catch(() => null);
    if (!resp.ok || !data || !data.ok) {
      errorEl.textContent = (data && data.error) || "Couldn't save -- try again.";
      errorEl.hidden = false;
      return;
    }

    if (activeTile) {
      activeTile.dataset.itemQty = String(data.qty);
      const qtyLabel = activeTile.querySelector("span:last-child");
      if (qtyLabel) qtyLabel.textContent = `${data.qty} ${activeTile.dataset.itemUnit}`;
    }
    dialog.close();
  });

  // --- Voice-to-text item matching ---
  const voiceBtn = document.getElementById("os-voice-btn");
  const voiceStatus = document.getElementById("os-voice-status");
  if (!voiceBtn) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    voiceBtn.hidden = true;
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "en-IN";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  function setStatus(text) {
    voiceStatus.textContent = text;
    voiceStatus.hidden = !text;
  }

  voiceBtn.addEventListener("click", () => {
    setStatus("Listening... say an item name.");
    try {
      recognition.start();
    } catch (err) {
      // start() throws if already running (e.g. a stray double-click).
    }
  });

  recognition.addEventListener("result", async (e) => {
    const heard = e.results[0][0].transcript;
    setStatus(`Heard "${heard}" -- matching...`);

    const csrf = form.querySelector('[name="_csrf_token"]').value;
    let resp;
    try {
      resp = await fetch("/opening-stock/voice-match", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ text: heard }),
      });
    } catch (err) {
      setStatus(`Heard "${heard}" -- network error while matching.`);
      return;
    }
    const data = await resp.json().catch(() => null);

    if (!data || !data.matchedItemId) {
      setStatus(`Heard "${heard}" -- no matching item found. Try again or use search.`);
      return;
    }

    const tile = document.querySelector(`.js-open-os-entry[data-item-id="${data.matchedItemId}"]`);
    if (!tile) {
      setStatus(`Matched "${data.matchedItemName}" but couldn't find its tile on screen.`);
      return;
    }
    setStatus(`Matched "${data.matchedItemName}" (${data.confidence}% confidence).`);
    tile.scrollIntoView({ behavior: "smooth", block: "center" });
    openFor(tile);
  });

  recognition.addEventListener("error", (e) => {
    setStatus(`Couldn't hear you (${e.error}) -- check microphone permission and try again.`);
  });

  recognition.addEventListener("end", () => {
    // Leave the last status message visible rather than clearing it --
    // it either shows the match result or the error already.
  });
})();
