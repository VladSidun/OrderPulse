"use strict";

const form = document.querySelector("[data-order-form]");
if (form) {
  const items = form.querySelector("[data-items]");
  const add = form.querySelector("[data-add-item]");
  const template = form.querySelector("[data-item-template]");
  const renumber = () => {
    const rows = [...items.querySelectorAll("[data-item]")];
    rows.forEach((row, index) => {
      row.querySelector("[data-item-number]").textContent = index + 1;
      row.querySelectorAll("[data-field]").forEach(input => {
        const label = row.querySelector(`label[for="${input.id}"]`);
        const error = document.getElementById(input.getAttribute("aria-describedby"));
        input.id = input.name = `items.${index}.${input.dataset.field}`;
        label.htmlFor = input.id;
        if (error) {
          error.id = `${input.id}-error`;
          input.setAttribute("aria-describedby", error.id);
        }
      });
      const remove = row.querySelector("[data-remove-item]");
      remove.hidden = false;
      remove.disabled = rows.length <= 1;
      remove.setAttribute("aria-label", `Вилучити позицію ${index + 1}`);
    });
    add.disabled = rows.length >= 100;
  };
  add.hidden = false;
  add.addEventListener("click", () => {
    if (items.children.length >= 100) return;
    items.append(template.content.cloneNode(true));
    renumber();
    items.lastElementChild.querySelector("input").focus();
  });
  items.addEventListener("click", event => {
    const button = event.target.closest("[data-remove-item]");
    if (!button || items.children.length <= 1) return;
    button.closest("[data-item]").remove();
    renumber();
    add.focus();
  });
  if (!items.children.length) items.append(template.content.cloneNode(true));
  renumber();
}
