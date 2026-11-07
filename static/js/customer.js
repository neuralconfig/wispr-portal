// Progressive enhancement only: the form works without JavaScript.
// Shows a "connecting" state and stops double submits; ticks the success-page countdown.
(function () {
  "use strict";
  // Success page: the redirect itself is the <meta refresh>; this only updates the text.
  // No aria-live, so screen readers are not interrupted every second.
  var countdown = document.getElementById("countdown");
  if (!countdown) { return; }
  var left = parseInt(countdown.getAttribute("data-seconds"), 10);
  if (!(left > 0)) { return; }
  var timer = window.setInterval(function () {
    left -= 1;
    if (left <= 0) { window.clearInterval(timer); left = 0; }
    countdown.textContent = left + (left === 1 ? " second" : " seconds");
  }, 1000);
})();

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
