const $ = (selector) => document.querySelector(selector);
let activeRun = null;
let activeTab = "assets";
let pollTimer = null;

function toast(message) {
  const node = $("#toast"); node.textContent = message; node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || "Request failed");
  return payload;
}

$("#crawl-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#start-button").disabled = true;
  try {
    const run = await api("/api/runs", {method:"POST", body:JSON.stringify({
      url:$("#url").value, max_pages:Number($("#max-pages").value),
      max_depth:Number($("#max-depth").value), max_attempts:Number($("#max-attempts").value)
    })});
    $("#workspace").classList.remove("hidden");
    await watch(run.id);
  } catch (error) { toast(error.message); }
  finally { $("#start-button").disabled = false; }
});

async function watch(runId) {
  clearTimeout(pollTimer);
  try {
    activeRun = await api(`/api/runs/${runId}`); render(activeRun);
    if (["queued","running"].includes(activeRun.status) || ["queued","running"].includes((activeRun.qa || {}).status)) pollTimer = setTimeout(() => watch(runId), 900);
  } catch (error) { toast(error.message); }
}

function render(run) {
  const report = run.report || {}; const summary = run.summary;
  $("#target-label").textContent = run.config.target_url;
  $("#run-id").textContent = `Run ${run.id}${run.baseline_run_id ? ` · verifies ${run.baseline_run_id}` : ""}`;
  const pill = $("#status-pill"); pill.textContent = run.status; pill.className = `status-pill ${run.status === "completed" ? "complete" : run.status}`;
  $("#evidence-link").href = `/api/runs/${run.id}/evidence`;
  $("#metric-urls").textContent = summary.urls; $("#metric-terminal").textContent = summary.terminal_urls;
  $("#metric-assets").textContent = summary.assets; $("#metric-exceptions").textContent = summary.exceptions;
  $("#progress-bar").style.width = `${summary.urls ? Math.round(100 * summary.terminal_urls / summary.urls) : 0}%`;
  $("#robots-url").textContent = report.robots_url || "Waiting…"; $("#robots-status").textContent = report.robots_status ?? "—";
  $("#robots-hash").textContent = report.robots_sha256 || "—"; $("#budget-state").textContent = report.budget_exhausted ? "Yes — review required" : "No";
  $("#reconcile-state").textContent = report.ready_for_reconciliation ? "Yes" : "No"; $("#error-state").textContent = run.error || "None";
  $("#verify-button").disabled = run.status !== "completed" || Boolean(run.baseline_run_id);
  renderTable(run); renderConvergence(run); renderQa(run); renderGate(run);
  if (run.approval) renderApproval(run.approval);
}

function renderTable(run) {
  const report = run.report || {}; let rows = [];
  if (activeTab === "assets") {
    $("#table-head").innerHTML = "<tr><th>Asset</th><th>Type</th><th>MIME</th><th>Bytes / hash</th><th>Storage / provenance</th></tr>";
    rows = (report.assets || []).map(a => `<tr><td class="url"><strong>${escapeHtml(a.filename)}</strong><br>${escapeHtml(a.url)}</td><td><span class="badge">${escapeHtml(a.kind)}</span></td><td>${escapeHtml(a.detected_mime)}${a.declared_mime && a.declared_mime !== a.detected_mime ? `<br><span class="mono">declared: ${escapeHtml(a.declared_mime)}</span>` : ""}</td><td>${a.byte_size.toLocaleString()}<br><span class="mono">${a.sha256.slice(0,16)}…</span></td><td class="url"><span class="mono">${escapeHtml(a.storage_uri || "not persisted")}</span><br>${escapeHtml(a.discovered_by)} · ${escapeHtml(a.referring_url || "direct")}</td></tr>`);
  } else if (activeTab === "documents") {
    $("#table-head").innerHTML = "<tr><th>Document</th><th>Pages</th><th>Bytes</th><th>Integrity</th><th>Source page</th></tr>";
    rows = (report.documents || []).map(d => `<tr><td class="url"><strong>${escapeHtml(d.filename)}</strong><br>${escapeHtml(d.url)}</td><td>${d.page_count ?? "—"}</td><td>${d.byte_size.toLocaleString()}</td><td><span class="badge">${d.duplicate_of ? "exact duplicate" : d.valid_pdf ? "valid PDF" : "invalid"}</span><br><span class="mono">${d.sha256.slice(0,16)}…</span>${d.duplicate_of ? `<br>Matches: ${escapeHtml(d.duplicate_of)}` : ""}</td><td class="url">${escapeHtml(d.referring_url || "Direct discovery")}</td></tr>`);
  } else {
    const records = Object.values(report.urls || {});
    const exceptions = new Set(["downloaded_invalid","excluded_by_policy","not_found","access_denied","permanent_error","unresolved_after_retries"]);
    const chosen = activeTab === "exceptions" ? records.filter(r => exceptions.has(r.status)) : records;
    $("#table-head").innerHTML = "<tr><th>URL</th><th>Status</th><th>HTTP</th><th>Discovery</th><th>Reason / attempts</th></tr>";
    rows = chosen.map(r => `<tr><td class="url">${escapeHtml(r.url)}</td><td><span class="badge">${escapeHtml(r.status)}</span></td><td>${r.http_status ?? "—"}</td><td>${escapeHtml(r.discovery_method)} · depth ${r.depth}</td><td>${escapeHtml(r.reason || `${(r.attempts || []).length} attempt(s)`)}</td></tr>`);
  }
  $("#table-body").innerHTML = rows.join(""); $("#empty-table").classList.toggle("hidden", rows.length > 0);
}

function renderConvergence(run) {
  const node = $("#convergence");
  if (!run.baseline_run_id) { node.className="convergence pending"; node.innerHTML="<strong>Awaiting second run</strong><span>Approval remains locked.</span>"; return; }
  if (run.status !== "completed") { node.className="convergence pending"; node.innerHTML="<strong>Stability crawl in progress</strong><span>Comparing repeat crawler output.</span>"; return; }
  const c = run.convergence || {}; node.className = `convergence ${c.converged ? "pass" : "fail"}`;
  node.innerHTML = c.converged ? "<strong>Runs converged</strong><span>No new/missing URLs or new document hashes.</span>" : `<strong>Difference detected</strong><span>${(c.new_urls||[]).length} new · ${(c.missing_urls||[]).length} missing · ${(c.new_document_hashes||[]).length} new hashes</span>`;
}

function renderQa(run) {
  const qa = run.qa || {status:"not_started"}; const node = $("#qa-verdict");
  const canStart = Boolean(run.baseline_run_id) && run.status === "completed" && Boolean((run.convergence || {}).converged) && qa.status === "not_started";
  $("#qa-button").disabled = !canStart;
  if (["queued","running"].includes(qa.status)) { node.className="convergence pending"; node.innerHTML="<strong>QA critic is running</strong><span>Read-only browser challenge in progress.</span>"; return; }
  if (qa.status === "failed") { node.className="convergence fail"; node.innerHTML=`<strong>QA execution failed</strong><span>${escapeHtml(qa.error || "Unknown error")}</span>`; return; }
  const report = qa.report;
  if (!report) { node.className="convergence pending"; node.innerHTML="<strong>QA not started</strong><span>Approval remains locked.</span>"; $("#qa-findings").innerHTML=""; return; }
  node.className=`convergence ${report.verdict === "pass" ? "pass" : "fail"}`;
  node.innerHTML=`<strong>QA verdict: ${escapeHtml(report.verdict)}</strong><span>${report.probes.length} independent probe(s)</span>`;
  $("#qa-findings").innerHTML=(report.findings || []).map(f=>`<article class="finding ${escapeHtml(f.severity)}"><span class="badge">${escapeHtml(f.severity)}</span><strong>${escapeHtml(f.code)}</strong><p>${escapeHtml(f.message)}</p>${(f.urls||[]).length ? `<details><summary>${f.urls.length} URL(s)</summary>${f.urls.map(u=>`<div class="mono wrap">${escapeHtml(u)}</div>`).join("")}</details>` : ""}</article>`).join("");
}

function renderGate(run) {
  const gate = run.approval_gate; const state = $("#gate-state");
  state.textContent = gate.eligible ? "Ready for review" : "Locked"; state.className = `status-pill ${gate.eligible ? "complete" : "locked"}`;
  $("#blockers").innerHTML = gate.blockers.length ? `<strong>Automatic blockers</strong><ul>${gate.blockers.map(item=>`<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<strong>Automated checks passed.</strong> Complete your manual review below.";
  $("#approve-button").disabled = !gate.eligible || Boolean(run.approval);
}

$("#verify-button").addEventListener("click", async () => {
  try { const run = await api(`/api/runs/${activeRun.id}/verification`, {method:"POST"}); toast("Stability crawl started"); await watch(run.id); }
  catch (error) { toast(error.message); }
});

$("#qa-button").addEventListener("click", async () => {
  try { const run = await api(`/api/runs/${activeRun.id}/qa`, {method:"POST"}); toast("Adversarial QA started"); await watch(run.id); }
  catch (error) { toast(error.message); }
});

document.querySelectorAll(".tab").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(item=>item.classList.remove("active")); button.classList.add("active"); activeTab=button.dataset.tab; renderTable(activeRun);
}));

$("#approval-form").addEventListener("submit", async event => {
  event.preventDefault(); const form = new FormData(event.target);
  const payload = {reviewer:$("#reviewer").value};
  ["inventory_reviewed","exceptions_reviewed","robots_reviewed","archive_coverage_reviewed","qa_findings_reviewed"].forEach(key=>payload[key]=form.get(key)==="on");
  try { const approval = await api(`/api/runs/${activeRun.id}/approval`, {method:"POST",body:JSON.stringify(payload)}); renderApproval(approval); toast("Corpus approved and frozen"); }
  catch (error) { toast(error.message); }
});

function renderApproval(approval) {
  const node=$("#approval-result"); node.classList.remove("hidden");
  node.innerHTML=`<strong>Approved corpus: ${escapeHtml(approval.id)}</strong><br>Reviewer: ${escapeHtml(approval.reviewer)} · Evidence hash: <span class="mono">${approval.report_sha256}</span>`;
  $("#approve-button").disabled=true;
}

function escapeHtml(value) { const div=document.createElement("div"); div.textContent=String(value); return div.innerHTML; }
