/* Compass — the decision-card client.
 *
 * Three things this file deliberately does not do:
 *   1. It never decides anything about urgency. The rule tag and the "why you
 *      are seeing this" line come verbatim from the gate, which is Python.
 *   2. It never renders model output as HTML. Everything a model wrote goes
 *      through textContent, so a regulation that happens to contain an angle
 *      bracket cannot become markup.
 *   3. It never hides a silence. The things Compass decided *not* to raise are
 *      on the page with their reason, because that is the whole claim.
 */

const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

let sweeping = false;

/* ---------------------------------------------------------------- helpers */

const ruleTag = (reason) => (reason.match(/^(R\d)/) || [, ""])[1];

const dayWord = (n) => {
  if (n === null || n === undefined) return "—";
  if (n < 0) return `${Math.abs(n)} day(s) ago`;
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  return `in ${n} days`;
};

function logLine(text) {
  const row = el("div");
  const now = new Date().toLocaleTimeString("en-GB", { hour12: false });
  row.append(el("span", "t", now), document.createTextNode(text));
  $("log").append(row);
  $("log").scrollTop = $("log").scrollHeight;
}

/* ------------------------------------------------------------------ state */

async function loadState() {
  const s = await (await fetch("/api/state")).json();
  const st = s.student;
  $("sub").innerHTML = "";
  $("sub").append(
    document.createTextNode("Watching "),
    el("b", null, st.name),
    document.createTextNode(
      ` · ${st.programme} · Stage ${st.stage} · ${st.credits_earned} ECTS earned · ${s.today}`
    )
  );
  if (!s.swept && !sweeping) {
    $("status-big").textContent = "Watching.";
    $("status-small").textContent =
      "Press “Run a sweep” and Compass will read the rules against this record.";
  }
  return s;
}

function setStatus(kind, big, small) {
  $("dot").className = "dot" + (kind ? " " + kind : "");
  $("status").className = "status" + (kind === "alert" ? " alert" : "");
  $("status-big").textContent = big;
  $("status-small").textContent = small;
}

/* ------------------------------------------------------------- rendering */

function field(label, text, dim) {
  const wrap = el("div", "field");
  const dl = el("dl");
  dl.style.margin = "0";
  dl.append(el("dt", null, label), el("dd", dim ? "dim" : null, text));
  wrap.append(dl);
  return wrap;
}

function renderCard(card) {
  const f = card.finding;
  const node = el("article", "card");

  node.append(el("div", "tag", `${f.severity} · needs you`));
  node.append(el("h2", null, f.title));
  node.append(field("What happened", f.what_happened));
  node.append(field("If you ignore it", f.consequence_if_ignored));

  const facts = el("table", "facts");
  const rows = [
    ["Last safe day", f.deadline ? `${f.deadline} (${dayWord(f.days_until_last_safe_action)})` : "—"],
    ["Can it be undone after that?", f.irreversible_after_deadline ? "No" : "Yes"],
    ["Is the choice yours to make?", f.needs_human_choice ? "Yes" : "No"],
    ["Compass's confidence", f.confidence.toFixed(2)],
  ];
  for (const [k, v] of rows) {
    const tr = el("tr");
    tr.append(el("td", null, k), el("td", null, v));
    facts.append(tr);
  }
  node.append(facts);

  node.append(field("Why you are seeing this", card.reason, true));

  const options = el("div", "options");
  for (const o of f.options) {
    const btn = el("button", "option" + (o.recommended ? " pick" : ""));
    const label = el("div", "label");
    label.append(document.createTextNode(o.label));
    if (o.recommended) label.append(el("span", "badge", "Compass suggests"));
    btn.append(label, el("div", "consequence", o.consequence));
    btn.onclick = () => choose(f.id, o.id, btn);
    options.append(btn);
  }
  node.append(options);

  if (f.evidence && f.evidence.length) {
    const det = el("details");
    det.append(el("summary", null, `Evidence (${f.evidence.length})`));
    const ul = el("ul");
    for (const e of f.evidence) ul.append(el("li", null, e));
    det.append(ul);
    node.append(det);
  }
  return node;
}

function renderSilence(cards) {
  const host = $("silence");
  host.innerHTML = "";
  if (!cards.length) return;

  host.append(el("h3", null, `Checked and deliberately passed over (${cards.length})`));
  for (const c of cards) {
    const f = c.finding;
    const row = el("div", "row");
    const head = el("div");
    head.append(
      el("span", "rule", `${ruleTag(c.reason)} `),
      el("span", "title", f.title)
    );
    row.append(head);
    // The reason after the rule tag is the whole point of showing these: the
    // student can read the judgement that kept Compass quiet.
    row.append(el("div", "why", c.reason.replace(/^R\d[^.]*\.\s*/, "")));
    host.append(row);
  }
}

function receiptNode(r) {
  const node = el("div", "receipt");
  const body = el("div", "body");
  body.append(el("b", null, r.summary));
  const bits = [];
  if (r.detail && r.detail.confirmation) bits.push(`confirmation ${r.detail.confirmation}`);
  if (r.reversible === false) bits.push("not reversible");
  if (bits.length) body.append(document.createTextNode(bits.join(" · ")));
  node.append(el("div", "num", r.action), body);
  return node;
}

async function render() {
  const data = await (await fetch("/api/decisions")).json();
  const cards = data.cards || [];

  const surfaced = cards.filter((c) => c.verdict === "surface");
  const silent = cards.filter((c) => c.verdict === "silent");

  const host = $("cards");
  host.innerHTML = "";
  surfaced.forEach((c) => host.append(renderCard(c)));
  renderSilence(silent);

  const receipts = $("receipts");
  receipts.innerHTML = "";
  if (data.receipts.length) {
    receipts.append(el("h3", null, "Done without asking (receipts)"));
    data.receipts.forEach((r) => receipts.append(receiptNode(r)));
  }

  if (!sweeping) {
    if (surfaced.length) {
      setStatus(
        "alert",
        `${surfaced.length} thing${surfaced.length > 1 ? "s" : ""} need you.`,
        `${cards.length} checked. The rest can wait, and Compass says why below.`
      );
    } else if (cards.length) {
      setStatus(
        "ok",
        "Watching. Nothing needs you.",
        `${silent.length} thing${silent.length === 1 ? "" : "s"} checked and passed over.`
      );
    }
  }
}

/* ---------------------------------------------------------------- actions */

async function choose(findingId, optionId, button) {
  const original = button.querySelector(".consequence").textContent;
  button.disabled = true;
  button.querySelector(".consequence").textContent = "Working…";

  const res = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ finding_id: findingId, option_id: optionId }),
  });
  const data = await res.json();

  if (!data.ok) {
    // A refusal is information, not a crash — show which rule of the
    // registrar's the tools would not let this past.
    button.disabled = false;
    const c = button.querySelector(".consequence");
    c.textContent = original;
    c.className = "consequence err";
    c.textContent = `Refused: ${data.error}`;
    return;
  }
  for (const r of data.receipts) logLine(`executed ${r.action} — ${r.detail.confirmation || ""}`);
  await render();
}

async function sweep() {
  if (sweeping) return;
  const started = await (await fetch("/api/sweep", { method: "POST" })).json();
  if (!started.started) return;
  $("log").innerHTML = "";
  logLine("sweep requested");
}

async function reset() {
  $("log").innerHTML = "";
  $("cards").innerHTML = "";
  $("silence").innerHTML = "";
  $("receipts").innerHTML = "";
  $("answer-slot").innerHTML = "";
  await fetch("/api/reset", { method: "POST" });
  logLine("dataset regenerated");
  await loadState();
}

/* --------------------------------------------------------------- streaming */

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = async (msg) => {
    const e = JSON.parse(msg.data);
    switch (e.stage) {
      case "sweep_start":
        sweeping = true;
        $("sweep").disabled = true;
        setStatus("busy", "Reading the rules…", `Simulated today is ${e.today}.`);
        logLine("sweep started");
        break;
      case "sentinel_start":
        logLine("sentinel: reading announcements, calendar, record and plan");
        break;
      case "sentinel_done":
        logLine(`sentinel: ${e.findings} finding(s) reported`);
        break;
      case "gate_done":
        logLine(
          `gate: ${e.surfaced} surfaced, ${e.auto_acted} handled without asking, ${e.silent} passed over`
        );
        break;
      case "auto_acted":
        logLine(`gate authorised ${e.receipts.map((r) => r.action).join(" then ")}`);
        break;
      case "auto_act_refused":
        logLine(`action refused: ${e.error}`);
        break;
      case "sweep_done":
        sweeping = false;
        $("sweep").disabled = false;
        logLine(e.summary);
        break;
      case "executed":
        // already logged by the click handler
        break;
      case "error":
        sweeping = false;
        $("sweep").disabled = false;
        setStatus("alert", "The sweep failed.", e.error);
        logLine(e.error);
        break;
      case "reset":
        sweeping = false;
        $("sweep").disabled = false;
        break;
      case "ready":
        sweeping = false;
        $("sweep").disabled = false;
        await render();
        break;
    }
  };
  es.onerror = () => {
    /* EventSource retries on its own; the server sends a keep-alive every 20s. */
  };
}

/* -------------------------------------------------------------------- ask */

$("ask-form").onsubmit = async (ev) => {
  ev.preventDefault();
  const question = $("ask-input").value.trim();
  if (!question) return;
  $("ask-input").value = "";
  $("ask-send").disabled = true;

  const slot = $("answer-slot");
  const box = el("div", "answer");
  box.append(el("div", "q", question), el("p", null, "Reading the record…"));
  slot.prepend(box);

  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    box.innerHTML = "";
    box.append(el("div", "q", question));
    for (const para of (data.answer || data.detail || "No answer.").split(/\n{2,}/)) {
      box.append(el("p", null, para));
    }
  } catch (err) {
    box.innerHTML = "";
    box.append(el("p", "err", String(err)));
  } finally {
    $("ask-send").disabled = false;
  }
};

$("sweep").onclick = sweep;
$("reset").onclick = reset;

loadState().then(render);
connect();
