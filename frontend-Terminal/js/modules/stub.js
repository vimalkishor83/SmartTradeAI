import { pageHeaderHtml } from "../components/pageHeader.js";
import { comingSoonHtml } from "../components/comingSoon.js";

export function renderStub(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label)}
    ${comingSoonHtml(mod)}
  `;
}
