// Any <img class="js-zoom-photo" data-full="..."> opens a full-size view
// in the shared #photo-zoom-dialog (native <dialog>, see base.html).
document.addEventListener("click", (e) => {
  const img = e.target.closest(".js-zoom-photo");
  if (img) {
    const dialog = document.getElementById("photo-zoom-dialog");
    if (!dialog) return;
    dialog.querySelector(".js-zoom-img").src = img.getAttribute("data-full");
    dialog.showModal();
    return;
  }

  const dialog = e.target.closest("#photo-zoom-dialog");
  if (dialog && e.target === dialog) {
    // click landed on the dialog's own backdrop area, not its content
    dialog.close();
  }
  if (e.target.matches(".js-zoom-close")) {
    e.target.closest("dialog").close();
  }
});
