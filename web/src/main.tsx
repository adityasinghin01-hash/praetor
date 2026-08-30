import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Self-hosted, not loaded from Google.
//
// The Content Security Policy is `default-src 'self'` with no font-src, so a stylesheet
// from fonts.googleapis.com is blocked in production — and the whole typographic
// direction silently fell back to system fonts. The dev server applies no such policy,
// so it looked right the entire time it was broken. Bundling the faces keeps the policy
// tight, removes a third-party request from the critical path, and means the app renders
// correctly with no internet at all.
// Latin only. The full packages carry Japanese, Cyrillic, Greek and Vietnamese subsets —
// seventy files for an English-language invoice queue, none of which any screen renders.
import "@fontsource/shippori-mincho-b1/latin-600.css";
import "@fontsource/shippori-mincho-b1/latin-800.css";
import "@fontsource/zen-kaku-gothic-new/latin-400.css";
import "@fontsource/zen-kaku-gothic-new/latin-500.css";
import "@fontsource/zen-kaku-gothic-new/latin-700.css";
import "./styles.css";

const root = document.getElementById("root");
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>);
