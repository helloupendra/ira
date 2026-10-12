// A copy button for code blocks marked data-copy. Without JavaScript, or
// without clipboard access, the block is still there to select by hand.
for (const block of document.querySelectorAll("[data-copy]")) {
  if (!navigator.clipboard) break;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "copy";
  button.textContent = "Copy";
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(block.querySelector("code").innerText.trim() + "\n");
      button.textContent = "Copied";
    } catch {
      button.textContent = "Select and copy";
    }
    setTimeout(() => {
      button.textContent = "Copy";
    }, 2000);
  });
  block.querySelector(".code-bar").append(button);
}
