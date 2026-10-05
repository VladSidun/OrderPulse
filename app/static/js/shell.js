"use strict";
// Inline native disclosure: navigation is available without JavaScript.
const menu = document.querySelector(".app-menu");
if (menu) {
  const trigger = menu.querySelector("summary");
  const mobile = window.matchMedia("(max-width: 900px)");
  const sync = () => trigger.setAttribute("aria-expanded", String(menu.open));
  const resize = () => {
    menu.open = !mobile.matches;
    sync();
  };
  resize();
  mobile.addEventListener("change", resize);
  menu.addEventListener("toggle", sync);
  menu.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches && menu.open) {
      menu.open = false;
      trigger.focus();
    }
  });
  menu.querySelectorAll("a").forEach((link) =>
    link.addEventListener("click", () => {
      if (mobile.matches) menu.open = false;
    }),
  );
}
