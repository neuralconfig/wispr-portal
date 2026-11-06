// Progressive enhancement only: the form works without JavaScript.
// Shows a "connecting" state and stops double submits.
(function () {
  "use strict";
  var form = document.getElementById("accept-form");
  if (!form) { return; }
  var button = document.getElementById("accept-button");
  var status = document.getElementById("status");
  var label = button.querySelector(".button__label");
  var original = label.textContent;
  var sent = false;
  form.addEventListener("submit", function (ev) {
    if (sent) { ev.preventDefault(); return; }
    sent = true;
    button.setAttribute("aria-disabled", "true");
    button.classList.add("is-busy");
    button.querySelector(".button__label").textContent = "Connecting…";
    status.textContent = "Connecting your device to the guest Wi-Fi. This can take a few seconds.";
  });
  // If the guest comes back with the browser's Back button, reset the button.
  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) {
      sent = false;
      button.removeAttribute("aria-disabled");
      button.classList.remove("is-busy");
      label.textContent = original;
      status.textContent = "";
    }
  });
})();
