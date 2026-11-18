// Pure renderers: run data in, DOM nodes out.
import { el, formatNumber } from "./dom.js";

export const STEPS = [
  { id: "researcher", name: "Researcher", doing: "Reading the website", done: "Profile built" },
  { id: "strategist", name: "Strategist", doing: "Drafting use cases", done: "Use cases drafted" },
  { id: "critic", name: "Critic", doing: "Reviewing the plan", done: "Plan approved" },
  { id: "dataset_scout", name: "Dataset scout", doing: "Searching Hugging Face and Kaggle", done: "Datasets matched" },
  { id: "reporter", name: "Reporter", doing: "Writing the report", done: "Report ready" },
];

const CHECK = "✓";
const CROSS = "✕";

/** State of each step for the tracker. Strategist/critic can repeat; show rounds. */
export function renderSteps(run) {
  const done = new Set(run.steps_done || []);
  const rounds = (run.scores || []).length;
  return STEPS.map((step) => {
    let state = done.has(step.id) ? "done" : "pending";
    if (run.status !== "succeeded" && run.step === step.id) state = run.status === "failed" ? "failed" : "active";
    let detail = state === "active" ? `${step.doing}…` : state === "done" ? step.done : "";
    if (step.id === "critic" && rounds) {
      const last = run.scores[rounds - 1];
      detail = state === "active" ? `Reviewing revision ${rounds + 1}…` : `Scored ${last}/10` + (rounds > 1 ? ` after ${rounds} rounds` : "");
    }
    if (step.id === "strategist" && rounds && state === "active") detail = `Revising after critic feedback (round ${rounds + 1})…`;
    if (state === "failed") detail = "Stopped here";
    const icon = state === "done" ? CHECK : state === "failed" ? CROSS : "";
    const label = { done: "completed", active: "in progress", failed: "failed", pending: "waiting" }[state];
    return el("li", { class: "step", dataset: { state } },
      el("span", { class: "step-icon", "aria-hidden": "true", text: icon }),
      el("div", {},
        el("p", { class: "step-name" }, step.name, el("span", { class: "visually-hidden", text: `, ${label}` })),
        detail ? el("p", { class: "step-detail", text: detail }) : null,
      ),
    );
  });
}

export function renderSkeleton() {
  return el("div", { class: "skeleton", "aria-hidden": "true" },
    el("div", { style: "width:40%" }), el("div", { style: "width:75%" }),
    el("div", { class: "tall" }), el("div", { class: "tall" }));
}

export function renderError(run, onRetry) {
  return el("div", { class: "error-panel", role: "alert" },
    el("h2", { text: "This run couldn't finish" }),
    el("p", { text: run.error || "Something went wrong." }),
    el("div", { class: "btn-row" }, el("button", { class: "btn", type: "button", onclick: onRetry, text: "Try again" })),
  );
}

function renderScore(run) {
  const scores = run.scores || [];
  if (!scores.length) return null;
  const last = scores[scores.length - 1];
  const c = run.critique || {};
  const rounds = scores.length > 1 ? `Improved over ${scores.length} rounds: ${scores.join(" → ")}` : "Approved on the first draft";
  return el("div", { class: "score" },
    el("span", { class: "score-value", text: `${last}/10` }),
    el("div", {}, el("p", { text: "Critic score" }), el("p", { class: "muted", text: rounds })),
    el("div", { class: "score-bar", role: "img", "aria-label": `Score ${last} out of 10` },
      el("span", { style: `width:${last * 10}%` })),
    (c.strengths?.length || c.problems?.length) ? el("details", {},
      el("summary", { text: "Critic's notes" }),
      c.strengths?.length ? el("ul", {}, c.strengths.map((s) => el("li", { text: s }))) : null,
      c.problems?.length ? el("ul", {}, c.problems.map((p) => el("li", { text: `To improve: ${p}` }))) : null,
    ) : null,
  );
}

function renderEvidence(ids, sourcesById, ucIndex) {
  if (!ids?.length) return el("p", { class: "evidence muted", text: "No direct citation from the site." });
  const excerpt = el("p", { class: "excerpt", hidden: true, id: `ex-${ucIndex}` });
  const chips = ids.map((id) => el("button", {
    class: "chip", type: "button", "aria-expanded": "false", "aria-controls": `ex-${ucIndex}`, text: id,
    onclick: (event) => {
      const btn = event.currentTarget;
      const open = btn.getAttribute("aria-expanded") === "true";
      btn.parentElement.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-expanded", "false"));
      excerpt.hidden = open;
      if (!open) {
        btn.setAttribute("aria-expanded", "true");
        const s = sourcesById.get(id);
        excerpt.textContent = s ? `${id}: “${cleanExcerpt(s.excerpt, 420)}”` : "Source not available.";
      }
    },
  }));
  return el("div", {}, el("div", { class: "evidence" }, el("span", { class: "muted", text: "Evidence:" }), chips), excerpt);
}

function renderDatasets(datasets) {
  if (!datasets?.length) {
    return el("p", { class: "empty-note", text: "No good public dataset found. Plan to start with the company's own data." });
  }
  return el("div", { class: "datasets" },
    el("h4", { text: "Datasets to prototype with" }),
    el("ul", {}, datasets.map((d) => el("li", {},
      el("div", { class: "ds-line" },
        el("a", { href: d.url, target: "_blank", rel: "noopener", text: d.name }),
        el("span", { class: "tag", text: d.source }),
        formatNumber(d.downloads) ? el("span", { class: "muted", text: `${formatNumber(d.downloads)} downloads` }) : null),
      el("p", { class: "reason", text: d.reason }),
    ))),
  );
}

function renderUseCase(result, i, sourcesById) {
  const uc = result.use_case;
  return el("li", { class: "usecase" },
    el("div", { class: "usecase-head" },
      el("h3", { text: uc.title }),
      el("div", { class: "usecase-meta" }, el("span", { class: "tag tag-accent", text: uc.department }))),
    el("dl", { class: "facts" },
      el("div", {}, el("dt", { text: "Objective" }), el("dd", { text: uc.objective })),
      el("div", {}, el("dt", { text: "AI approach" }), el("dd", { text: uc.ai_approach })),
      el("div", {}, el("dt", { text: "Business impact" }), el("dd", { text: uc.business_impact }))),
    renderEvidence(uc.evidence, sourcesById, i),
    renderDatasets(result.datasets),
  );
}

/** Chunks overlap, so an excerpt can start mid-sentence; start at the next sentence. */
function cleanExcerpt(text, max) {
  let t = text.replace(/\s+/g, " ").trim();
  if (/^[a-z]/.test(t)) {
    const cut = t.search(/[.!?]\s+[A-Z0-9]/);
    if (cut > -1 && cut < 120) t = t.slice(cut + 2);
  }
  return t.length > max ? `${t.slice(0, max).replace(/\s\S*$/, "")}…` : t;
}

const idNumber = (id) => Number(id.replace(/\D/g, "")) || 0;

function renderSources(sources, results) {
  const cited = new Set(results.flatMap((r) => r.use_case.evidence || []));
  const shown = sources.filter((s) => cited.has(s.id)).sort((a, b) => idNumber(a.id) - idNumber(b.id));
  if (!shown.length) return null;
  return el("section", { "aria-labelledby": "src-title" },
    el("div", { class: "section-head" }, el("h2", { id: "src-title", text: "Sources from the website" })),
    el("ol", { class: "sources" }, shown.map((s) => el("li", { id: `source-${s.id}` },
      el("span", { class: "sid", text: s.id }),
      el("p", { text: cleanExcerpt(s.excerpt, 280) })))),
  );
}

export function renderResults(run, actions) {
  const p = run.profile;
  const results = run.results || [];
  const sourcesById = new Map((run.sources || []).map((s) => [s.id, s]));
  return el("div", { class: "result-stack" },
    el("section", { class: "summary", "aria-labelledby": "co-name" },
      el("div", { class: "summary-top" },
        el("h2", { id: "co-name", text: p.name }),
        el("span", { class: "tag", text: p.industry })),
      el("a", { class: "source-url", href: run.url, target: "_blank", rel: "noopener", text: run.url }),
      el("p", { text: p.summary }),
      renderScore(run),
      el("div", { class: "btn-row" },
        el("button", { class: "btn btn-primary", type: "button", onclick: actions.downloadReport, text: "Download report (.md)" }),
        el("button", { class: "btn", type: "button", onclick: actions.downloadJson, text: "Download data (.json)" }),
        el("button", { class: "btn", type: "button", onclick: actions.copyLink, text: "Copy share link" })),
    ),
    el("section", { "aria-labelledby": "uc-title" },
      el("div", { class: "section-head" },
        el("h2", { id: "uc-title", text: `${results.length} use cases` }),
        el("span", { class: "muted", text: "Grounded in the company's own website" })),
      el("ol", { class: "usecases" }, results.map((r, i) => renderUseCase(r, i, sourcesById)))),
    renderSources(run.sources || [], results),
  );
}
