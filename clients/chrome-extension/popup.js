"use strict";

chrome.runtime.sendMessage({ type: "status" }, (status) => {
  const state = document.getElementById("state");
  if (!status || !status.connected) {
    state.textContent = "Not connected. Install the Ira companion for Mac, then restart Chrome.";
  } else if (!status.ready) {
    state.textContent = "Waiting for the Ira companion on this Mac to start.";
  } else {
    state.textContent = "Connected. Ask Ira about a tab.";
  }
});
