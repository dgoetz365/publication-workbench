"use strict";

const $ = (id) => document.getElementById(id);
let state = null;
let draft = null;
let selection = { collection: "program", id: null };
let dirty = false;
let busy = false;
let previewed = null;
let searchSequence = 0;

const labels = { title: "Title", intro: "Introduction", name: "Name", time: "Program time", performer_id: "Performer", venue_id: "Venue", description: "Program description", discipline: "Discipline", bio: "Profile", access: "Access & arrival" };
const longFields = new Set(["intro", "description", "bio", "access"]);

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function message(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
}

async function request(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The request failed. Try again.");
  return result;
}

function controls() {
  if (!state) return;
  $("save").disabled = busy || !dirty;
  $("reload").disabled = busy;
  $("review").disabled = busy || dirty || state.issues.length > 0 || previewed !== state.version || state.reviewed_version === state.version;
  $("publish").disabled = busy || dirty || state.reviewed_version !== state.version || state.published?.version === state.version;
  $("draft-status").textContent = dirty ? `Revision ${state.version} · unsaved edits` : `Saved revision ${state.version}`;
  $("editor-form").setAttribute("aria-busy", String(busy));
  $("contents").querySelectorAll("button").forEach((button) => { button.disabled = busy; });
}

function editField(record, field) {
  const wrapper = element("div");
  const label = element("label", labels[field]);
  const id = `field-${field}`;
  label.htmlFor = id;
  let input;
  if (field === "performer_id" || field === "venue_id") {
    input = element("select");
    const candidates = draft[field === "performer_id" ? "performers" : "venues"];
    const empty = element("option", "Choose a linked record");
    empty.value = "";
    input.append(empty);
    if (record[field] && !candidates.some((candidate) => candidate.id === record[field])) {
      const missing = element("option", `Missing record: ${record[field]}`);
      missing.value = record[field];
      input.append(missing);
    }
    for (const candidate of candidates) {
      const option = element("option", candidate.name || "Untitled record");
      option.value = candidate.id;
      input.append(option);
    }
  } else {
    input = element(longFields.has(field) ? "textarea" : "input");
    input.maxLength = longFields.has(field) ? 4000 : 200;
  }
  input.id = id;
  input.name = field;
  input.value = record[field];
  input.addEventListener("input", () => {
    record[field] = input.value;
    dirty = true;
    controls();
  });
  wrapper.append(label, input);
  return wrapper;
}

function renderEditor() {
  let record = selection.collection === "program" ? draft : draft[selection.collection].find((item) => item.id === selection.id);
  if (!record) {
    selection = { collection: "program", id: null };
    record = draft;
  }
  const fields = selection.collection === "program" ? ["title", "intro"] : Object.keys(record).filter((key) => key !== "id");
  $("editor-title").textContent = selection.collection === "program" ? "Program details" : record.title || record.name || "Untitled record";
  $("fields").replaceChildren(...fields.map((field) => editField(record, field)));
  if (record.id) $("fields").prepend(element("p", `Record: ${record.id}`, "field-note"));
  renderContents();
}

function renderContents() {
  const nodes = [];
  function choose(title, collection, id = null) {
    const button = element("button", title);
    button.type = "button";
    button.disabled = busy;
    button.setAttribute("aria-current", String(selection.collection === collection && selection.id === id));
    button.addEventListener("click", () => {
      selection = { collection, id };
      renderEditor();
    });
    return button;
  }
  nodes.push(choose("Program details", "program"));
  for (const [collection, title] of [["entries", "Program entries"], ["performers", "Performer profiles"], ["venues", "Venues"]]) {
    nodes.push(element("h3", title));
    for (const record of draft[collection]) nodes.push(choose(record.title || record.name || "Untitled record", collection, record.id));
  }
  $("contents").replaceChildren(...nodes);
}

function renderState() {
  renderEditor();
  $("validation-summary").textContent = state.issues.length ? `${state.issues.length} issue(s) in saved revision ${state.version}. Edit and save to check again.` : `Revision ${state.version}: required fields and entity links are valid.`;
  $("issues").replaceChildren(...state.issues.map((issue) => element("li", `${issue.path}: ${issue.message}`)));
  $("review-status").textContent = state.reviewed_version === state.version ? `Revision ${state.version} is marked reviewed.` : `Preview saved revision ${state.version}, then mark it reviewed. Saving changes resets review.`;
  $("preview").href = `/preview?version=${state.version}`;
  const published = state.published;
  $("publish-status").textContent = published ? `Edition ${published.edition} contains revision ${published.version}. ${published.version === state.version ? "It matches the saved draft." : "Your current draft is separate."}` : "No edition has been published. Only reviewed revisions can be published.";
  for (const [id, route] of [["program-link", "/program"], ["export-link", "/export"]]) {
    $(id).hidden = !published;
    if (published) $(id).href = `${route}?edition=${published.edition}`;
  }
  $("search-status").textContent = published ? `Search edition ${published.edition}. Results open the matching section.` : "Publish an edition to make it searchable.";
  $("query").disabled = !published;
  $("search-form").querySelector("button").disabled = !published;
  searchSequence += 1;
  $("search-results").replaceChildren();
  $("history").replaceChildren(...state.history.map((revision) => {
    const item = element("li");
    const link = element("a", `Revision ${revision.version}`);
    link.href = `/preview?version=${revision.version}`;
    link.target = "_blank";
    link.rel = "noopener";
    const timestamp = element("time", new Date(revision.saved_at).toLocaleString());
    timestamp.dateTime = revision.saved_at;
    item.append(link, element("strong", revision.note), timestamp);
    return item;
  }));
  controls();
}

async function load() {
  busy = true;
  controls();
  try {
    state = await request("/api/state");
    draft = structuredClone(state.content);
    dirty = false;
    previewed = null;
    $("revision-note").value = "";
    renderState();
    message(`Saved revision ${state.version} is ready to edit.`);
  } catch (error) { message(error.message, true); }
  finally { busy = false; controls(); }
}

async function mutate(route, payload, success) {
  busy = true;
  controls();
  message("Saving the editorial state…");
  // Inputs are disabled while saving so a response cannot replace newer local edits.
  const inputs = [...$("editor-form").querySelectorAll("input, textarea, select")];
  inputs.forEach((input) => { input.disabled = true; });
  try {
    state = await request(route, payload);
    draft = structuredClone(state.content);
    dirty = false;
    $("revision-note").value = "";
    renderState();
    message(success);
  } catch (error) { message(`${error.message} Your unsaved edits remain here.`, true); }
  finally { busy = false; inputs.forEach((input) => { input.disabled = false; }); controls(); }
}

$("editor-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy || !dirty) return;
  mutate("/api/draft", { version: state.version, content: draft, note: $("revision-note").value }, "Revision saved. Preview and review this revision before publishing.");
});
$("reload").addEventListener("click", () => {
  if (!dirty || window.confirm("Discard unsaved edits and reload the saved draft?")) load();
});
$("preview").addEventListener("click", () => { previewed = state.version; controls(); });
$("review").addEventListener("click", () => mutate("/api/review", { version: state.version }, "This saved revision is marked reviewed and ready to publish."));
$("publish").addEventListener("click", () => mutate("/api/publish", { version: state.version }, "Published. The program, search results, and HTML export now share this edition."));
$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state?.published) return;
  const sequence = ++searchSequence;
  const query = $("query").value.trim();
  $("search-results").replaceChildren();
  if (!query) { $("search-status").textContent = "Enter a name, venue, or phrase to search."; return; }
  $("search-status").textContent = "Searching the published edition…";
  try {
    const result = await request(`/api/search?edition=${state.published.edition}&q=${encodeURIComponent(query)}`);
    if (sequence !== searchSequence) return;
    $("search-status").textContent = result.results.length ? `${result.results.length} result(s) in edition ${result.edition}.` : "No matches. Try a performer name, venue, or shorter phrase.";
    $("search-results").replaceChildren(...result.results.map((match) => {
      const item = element("li");
      const link = element("a", match.title);
      link.href = match.href;
      link.target = "_blank";
      link.rel = "noopener";
      item.append(link, element("small", match.kind));
      return item;
    }));
  } catch (error) { if (sequence === searchSequence) $("search-status").textContent = error.message; }
});
window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
load();
