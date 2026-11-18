// UseCaseForge front end: form handling, polling, and wiring the renderers to the page.
import { api, ApiError } from "./js/api.js";
import { download, el, toast } from "./js/dom.js";
import { renderError, renderResults, renderSkeleton, renderSteps } from "./js/render.js";

const $ = (id) => document.getElementById(id);
const form = $("run-form");
const urlInput = $("url");
const urlError = $("url-error");
const submitBtn = $("submit");
const results = $("results");
const intro = $("intro");

let pollTimer = null;
let currentRunId = null;
let startedAt = null;

// --- status / quota -----------------------------------------------------------

async function loadStatus() {
  try {
    const s = await api.status();
    const quota = $("quota");
    if (!s.shared_key) {
      quota.textContent = "This demo needs your own Gemini key (free).";
      $("key-details").open = true;
    } else if (s.runs_left_today === 0) {
      quota.textContent = "The shared demo key is used up for today. Add your own free Gemini key to run now.";
      $("key-details").open = true;
    } else {
      quota.textContent = `Shared demo key: ${s.runs_left_today} of ${s.daily_limit} runs left today.`;
    }
    if (!s.own_key_supported) $("key-details").hidden = true;
  } catch (err) {
    $("quota").textContent = err.message;
  }
}

// --- form ---------------------------------------------------------------------

function showFieldError(message) {
  urlError.textContent = message;
  urlError.hidden = !message;
  urlInput.setAttribute("aria-invalid", message ? "true" : "false");
}

document.querySelectorAll("[data-example]").forEach((btn) =>
  btn.addEventListener("click", () => {
    urlInput.value = btn.dataset.example;
    showFieldError("");
    urlInput.focus();
  }),
);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();
  if (!url) {
    showFieldError("Enter a company website, for example https://www.zomato.com.");
    urlInput.focus();
    return;
  }
  showFieldError("");
  const payload = {
    url,
    extra_urls: $("extra").value.split("\n").map((s) => s.trim()).filter(Boolean),
    api_key: $("api-key").value.trim() || null,
  };
  submitBtn.disabled = true;
  submitBtn.textContent = "Starting…";
  try {
    const { id } = await api.createRun(payload);
    history.pushState({ id }, "", `?run=${id}`);
    startRun(id);
  } catch (err) {
    showFieldError(err.message);
    (err.status === 429 || err.status === 400) && /key/i.test(err.message) && ($("key-details").open = true);
    resetButton();
  }
});

function resetButton() {
  submitBtn.disabled = false;
  submitBtn.textContent = "Generate use cases";
}

// --- run lifecycle ------------------------------------------------------------

function startRun(id) {
  clearTimeout(pollTimer);
  currentRunId = id;
  startedAt = Date.now();
  $("progress").hidden = false;
  intro.hidden = true;
  results.setAttribute("aria-busy", "true");
  results.replaceChildren(renderSkeleton());
  poll();
}

async function poll() {
  const id = currentRunId;
  try {
    const run = await api.getRun(id);
    if (id !== currentRunId) return; // a newer run replaced this one
    update(run);
    if (run.status === "succeeded" || run.status === "failed") return finish(run);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      results.replaceChildren(renderError({ error: "This run no longer exists. Start a new one." }, retry));
      return finish(null);
    }
    $("notice").hidden = false;
    $("notice").textContent = `${err.message} Retrying…`;
  }
  const elapsed = Date.now() - startedAt;
  pollTimer = setTimeout(poll, elapsed < 60_000 ? 2500 : 5000);
}

function update(run) {
  $("steps").replaceChildren(...renderSteps(run));
  const notice = $("notice");
  notice.hidden = !run.notice;
  notice.textContent = run.notice || "";
  if (run.created_at) {
    const secs = Math.max(0, Math.round((Date.now() - Date.parse(run.created_at)) / 1000));
    $("elapsed").textContent = run.status === "succeeded" || run.status === "failed" ? "" : `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  }
  if (run.url && !urlInput.value) urlInput.value = run.url;
  submitBtn.disabled = true;
  submitBtn.textContent = "Agents are working…";
}

function finish(run) {
  results.setAttribute("aria-busy", "false");
  resetButton();
  if (!run) return;
  $("elapsed").textContent = "";
  if (run.status === "failed") {
    results.replaceChildren(renderError(run, retry));
  } else {
    results.replaceChildren(renderResults(run, actionsFor(run)));
    results.querySelector("h2")?.setAttribute("tabindex", "-1");
    results.querySelector("h2")?.focus({ preventScroll: false });
  }
  loadStatus();
}

function retry() {
  form.requestSubmit();
}

function actionsFor(run) {
  const slug = (run.profile?.name || "company").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return {
    downloadReport: () => download(`${slug}-ai-use-cases.md`, run.report || "", "text/markdown"),
    downloadJson: () => {
      const { profile, scores, critique, results: res, sources, url } = run;
      download(`${slug}-ai-use-cases.json`, JSON.stringify({ url, profile, scores, critique, results: res, sources }, null, 2), "application/json");
    },
    copyLink: async () => {
      try {
        await navigator.clipboard.writeText(location.href);
        toast("Link copied");
      } catch {
        toast("Copy failed. Use the address bar instead.");
      }
    },
  };
}

// --- boot -----------------------------------------------------------------------

window.addEventListener("popstate", () => location.reload());
loadStatus();
const existing = new URLSearchParams(location.search).get("run");
if (existing && /^[0-9a-f]{32}$/.test(existing)) startRun(existing);
