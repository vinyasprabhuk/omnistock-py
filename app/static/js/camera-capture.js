// Live camera capture for the Wastage/Production entry dialog -- no file
// picker, no gallery. Opens the device camera via getUserMedia, and on
// capture stamps the frame with the logged-in user's name, a timestamp,
// and geolocation (if granted) directly onto the image before handing it
// to the existing hidden <input type="file"> the form already submits.
//
// Markup contract (see wastage/index.html): dialog#entry-dialog carries
// data-username, and contains .js-photo-input (hidden file input),
// .js-camera-idle/.js-camera-live/.js-camera-captured (three UI states),
// .js-camera-video, .js-camera-canvas, .js-camera-preview, plus buttons
// .js-camera-open/.js-camera-capture/.js-camera-retake.
(function () {
  let stream = null;
  let geoPosition = null;
  let geoStatus = "pending";
  let tokenRefreshed = false;

  function requestGeo() {
    geoStatus = "pending";
    geoPosition = null;
    if (!("geolocation" in navigator)) {
      geoStatus = "unavailable";
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        geoPosition = { lat: pos.coords.latitude, lon: pos.coords.longitude };
        geoStatus = "ok";
      },
      () => { geoStatus = "denied"; },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  }

  function stopStream() {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
  }

  async function openCamera(dialog) {
    const statusEl = dialog.querySelector(".js-camera-status");
    statusEl.textContent = "";
    requestGeo();
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    } catch (err) {
      statusEl.textContent = "Couldn't open the camera -- check camera permission for this site and try again.";
      return;
    }
    const video = dialog.querySelector(".js-camera-video");
    video.srcObject = stream;
    dialog.querySelector(".js-camera-idle").hidden = true;
    dialog.querySelector(".js-camera-live").hidden = false;
    dialog.querySelector(".js-camera-captured").hidden = true;
  }

  function locationLine() {
    if (geoStatus === "ok" && geoPosition) return `${geoPosition.lat.toFixed(5)}, ${geoPosition.lon.toFixed(5)}`;
    if (geoStatus === "denied") return "Location permission denied";
    if (geoStatus === "unavailable") return "Location unavailable";
    return "Location pending…";
  }

  function capture(dialog) {
    const video = dialog.querySelector(".js-camera-video");
    const canvas = dialog.querySelector(".js-camera-canvas");
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 720;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    const username = dialog.getAttribute("data-username") || "";
    const lines = [username, new Date().toLocaleString(), locationLine()].filter(Boolean);
    const fontSize = Math.max(14, Math.round(canvas.width / 32));
    const padding = Math.round(fontSize * 0.6);
    const lineHeight = Math.round(fontSize * 1.4);
    const barHeight = padding * 2 + lineHeight * lines.length;

    ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
    ctx.fillRect(0, canvas.height - barHeight, canvas.width, barHeight);
    ctx.fillStyle = "#ffffff";
    ctx.font = `${fontSize}px sans-serif`;
    ctx.textBaseline = "top";
    lines.forEach((line, i) => {
      ctx.fillText(line, padding, canvas.height - barHeight + padding + i * lineHeight);
    });

    stopStream();
    dialog.querySelector(".js-camera-live").hidden = true;

    canvas.toBlob((blob) => {
      if (!blob) return;
      const file = new File([blob], `entry-${Date.now()}.jpg`, { type: "image/jpeg" });
      const dt = new DataTransfer();
      dt.items.add(file);
      dialog.querySelector(".js-photo-input").files = dt.files;

      dialog.querySelector(".js-camera-preview").src = canvas.toDataURL("image/jpeg", 0.9);
      dialog.querySelector(".js-camera-captured").hidden = false;
    }, "image/jpeg", 0.9);
  }

  function resetCamera(dialog) {
    stopStream();
    geoPosition = null;
    geoStatus = "pending";
    tokenRefreshed = false;
    dialog.querySelector(".js-photo-input").value = "";
    dialog.querySelector(".js-camera-idle").hidden = false;
    dialog.querySelector(".js-camera-live").hidden = true;
    dialog.querySelector(".js-camera-captured").hidden = true;
    dialog.querySelector(".js-camera-status").textContent = "";
  }
  window.resetEntryCamera = resetCamera;

  document.addEventListener("click", (e) => {
    const dialog = document.getElementById("entry-dialog");
    if (!dialog) return;
    if (e.target.closest(".js-camera-open")) {
      openCamera(dialog);
    } else if (e.target.closest(".js-camera-capture")) {
      capture(dialog);
    } else if (e.target.closest(".js-camera-retake")) {
      dialog.querySelector(".js-camera-captured").hidden = true;
      openCamera(dialog);
    }
  });

  document.addEventListener("DOMContentLoaded", () => {
    const dialog = document.getElementById("entry-dialog");
    if (!dialog) return;
    dialog.addEventListener("close", () => resetCamera(dialog));

    const form = dialog.querySelector("form");
    form.addEventListener("submit", (e) => {
      const input = dialog.querySelector(".js-photo-input");
      if (!input.files || input.files.length === 0) {
        e.preventDefault();
        const statusEl = dialog.querySelector(".js-camera-status");
        statusEl.textContent = "Take a photo first -- it's required for every entry.";
        statusEl.style.color = "var(--danger)";
        return;
      }

      // The dialog can sit open a minute or more while camera/location
      // permissions are granted -- long enough for the CSRF token embedded
      // at page-load time to go stale on some mobile browsers. Fetch a
      // token current as of right now before actually submitting.
      if (tokenRefreshed) return; // already refreshed, let this submit through
      e.preventDefault();
      const csrfInput = form.querySelector('input[name="_csrf_token"]');
      const submitBtn = form.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      fetch("/api/csrf-token", { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (data && data.csrfToken) csrfInput.value = data.csrfToken;
        })
        .catch(() => {})
        .finally(() => {
          tokenRefreshed = true;
          if (submitBtn) submitBtn.disabled = false;
          form.requestSubmit ? form.requestSubmit(submitBtn) : form.submit();
        });
    });
  });
})();
