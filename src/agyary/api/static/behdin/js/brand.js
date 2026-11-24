"use strict";

// The app's name, read from the page (the server writes it into index.html from APP_NAME in
// routes/behdin.py, the one place it is set), so renaming the app never touches a script.
const tag = typeof document !== "undefined" && document.querySelector('meta[name="application-name"]');
export const APP_NAME = (tag && tag.content && !tag.content.includes("{{")) ? tag.content : "Parsi";
