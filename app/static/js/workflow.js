document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
    form.querySelector('button[type="submit"]').disabled = true;
  });
});
