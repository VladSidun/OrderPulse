"use strict";

// Announce server validation and move keyboard users to the explanation.
const validationAlert = document.querySelector('[role="alert"]');
if (validationAlert) {
  validationAlert.tabIndex = -1;
  validationAlert.focus();
}

// Runs after form-level confirmation handlers; a cancelled action stays usable.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (event.defaultPrevented || form.method.toLowerCase() !== "post") return;
  if (form.dataset.submitting) {
    event.preventDefault();
    return;
  }
  form.dataset.submitting = "true";
  form.querySelectorAll('button[type="submit"]').forEach((button) => {
    button.dataset.submitting = "true";
    button.disabled = true;
  });
});

// Back/forward cache can restore disabled controls after successful navigation.
window.addEventListener("pageshow", () => {
  document.querySelectorAll("[data-submitting]").forEach((element) => {
    if (element.tagName === "BUTTON") element.disabled = false;
    delete element.dataset.submitting;
  });
});
