// The theme before the first paint, so a light choice never flashes dark: what the person
// chose in Settings (Light, Dark or System), dark until they choose. System leaves it to the
// device's own setting, which tokens.css follows. app.js changes it from the menu.
(() => {
  let choice = "dark";
  try {
    choice = localStorage.getItem("ira.theme") || "dark";
  } catch {
    /* storage can be unavailable in private windows */
  }
  const root = document.documentElement;
  if (choice === "light" || choice === "dark") root.dataset.theme = choice;
  else if (choice === "system") delete root.dataset.theme;
})();
