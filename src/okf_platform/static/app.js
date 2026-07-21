const $ = (selector) => document.querySelector(selector);
let activeRun = null;
let activeTab = "assets";
let pollTimer = null;
let activeCorpusId = null;
let okfReady = false;
let ragReady = false;

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

async function loadRagRuntime() {
  try {
    const config = await api("/api/rag/config");
    const retrieval = config.retrieval || {};
    const pill = $("#rag-runtime-pill");
    pill.textContent = config.mode === "production"
      ? (config.ready ? "Production hybrid" : "Setup required")
      : "Local baseline";
    pill.className = `status-pill ${config.ready ? "complete" : "locked"}`;
    $("#rag-runtime").innerHTML = [
      ["Vector database", config.vector_backend],
      ["Embedding", `${config.embedding_model} · ${config.embedding_dimensions}D`],
      ["Lexical + fusion", `${retrieval.sparse} + dense · RRF`],
      ["Reranker", config.reranker_model],
    ].map(([label,value])=>`<article><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
    if ((config.missing_dependencies || []).length) {
      $("#rag-runtime").insertAdjacentHTML("beforeend", `<article><span>Missing packages</span><strong>${escapeHtml(config.missing_dependencies.join(", "))}</strong></article>`);
    }
  } catch (error) {
    $("#rag-runtime-pill").textContent = "Unavailable";
    $("#rag-runtime-pill").className = "status-pill locked";
    $("#rag-runtime").textContent = error.message;
  }
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
  if (!report) { node.className="convergence pending"; node.innerHTML="<strong>QA not started</strong><span>Approval remains locked.</span>"; $("#qa-findings").innerHTML=""; $("#exception-controls").innerHTML=""; return; }
  node.className=`convergence ${report.verdict === "pass" ? "pass" : "fail"}`;
  node.innerHTML=`<strong>QA verdict: ${escapeHtml(report.verdict)}</strong><span>${report.probes.length} independent probe(s)</span>`;
  $("#qa-findings").innerHTML=(report.findings || []).map(f=>`<article class="finding ${escapeHtml(f.severity)}"><span class="badge">${escapeHtml(f.severity)}</span><strong>${escapeHtml(f.code)}</strong><p>${escapeHtml(f.message)}</p>${f.waivable ? '<p><em>This coverage gap may be accepted by the human reviewer with a recorded reason and residual risk.</em></p>' : ''}${(f.urls||[]).length ? `<details><summary>${f.urls.length} URL(s)</summary>${f.urls.map(u=>`<div class="mono wrap">${escapeHtml(u)}</div>`).join("")}</details>` : ""}</article>`).join("");
  $("#exception-controls").innerHTML=(report.findings || []).filter(f=>f.waivable).map(f=>`<article class="exception-card" data-fingerprint="${escapeHtml(f.fingerprint)}"><label class="check"><input class="exception-accepted" type="checkbox" /> Accept ${escapeHtml(f.code)} for this corpus snapshot</label><label>Acceptance rationale<textarea class="exception-reason" placeholder="Why is this specific gap acceptable for the intended use?"></textarea></label><label>Residual risk<textarea class="exception-risk" placeholder="What can still be missing or wrong downstream?"></textarea></label></article>`).join("");
}

function renderGate(run) {
  const gate = run.approval_gate; const state = $("#gate-state");
  const conditionallyReady = gate.eligible_with_exceptions;
  state.textContent = gate.eligible ? "Ready for review" : conditionallyReady ? "Exception review" : "Locked"; state.className = `status-pill ${gate.eligible || conditionallyReady ? "complete" : "locked"}`;
  $("#blockers").innerHTML = gate.blockers.length ? `<strong>${conditionallyReady ? "Coverage gaps need your decision" : "Automatic blockers"}</strong><ul>${gate.blockers.map(item=>`<li>${escapeHtml(item)}</li>`).join("")}</ul>${conditionallyReady ? '<p>You may approve only after explicitly accepting each displayed QA gap. Integrity, tool and storage failures cannot be bypassed.</p>' : ''}` : "<strong>Automated checks passed.</strong> Complete your manual review below.";
  $("#approve-button").disabled = !(gate.eligible || conditionallyReady) || Boolean(run.approval);
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
  payload.qa_exceptions=[...document.querySelectorAll(".exception-card")].filter(card=>card.querySelector(".exception-accepted").checked).map(card=>({finding_fingerprint:card.dataset.fingerprint,accepted:true,reason:card.querySelector(".exception-reason").value,residual_risk:card.querySelector(".exception-risk").value}));
  try { const approval = await api(`/api/runs/${activeRun.id}/approval`, {method:"POST",body:JSON.stringify(payload)}); renderApproval(approval); toast("Corpus approved and frozen"); }
  catch (error) { toast(error.message); }
});

function renderApproval(approval) {
  activeCorpusId=approval.id;
  const node=$("#approval-result"); node.classList.remove("hidden");
  node.innerHTML=`<strong>Approved corpus: ${escapeHtml(approval.id)}</strong><br>Reviewer: ${escapeHtml(approval.reviewer)} · Effective QA: ${escapeHtml(approval.qa_effective_verdict)} · Accepted gaps: ${(approval.accepted_qa_exceptions||[]).length}<br>Frozen objects: ${approval.corpus_snapshot.object_count} · Snapshot hash: <span class="mono">${approval.corpus_snapshot.manifest_sha256}</span>`;
  $("#approve-button").disabled=true;
  $("#stage2-panel").classList.remove("hidden"); $("#stage2-button").disabled=false; $("#stage2-button").dataset.corpusId=approval.id;
}

$("#stage2-button").addEventListener("click", async () => {
  const button=$("#stage2-button"); button.disabled=true; $("#stage2-result").innerHTML="<strong>Stage 2 extraction is running</strong><span>Reading the immutable snapshot.</span>";
  try { const result=await api(`/api/corpora/${button.dataset.corpusId}/stage2/extraction`, {method:"POST"}); const counts=Object.entries(result.status_counts||{}).map(([key,value])=>`${key}: ${value}`).join(" · "); $("#stage2-result").className="convergence pass"; $("#stage2-result").innerHTML=`<strong>Extraction complete · ${result.text_unit_count} text unit(s)</strong><span>${escapeHtml(counts)} · Records hash ${escapeHtml(result.records_sha256.slice(0,16))}…</span>`; $("#knowledge-panel").classList.remove("hidden"); $("#okf-build-button").disabled=false; $("#rag-build-button").disabled=false; }
  catch(error) { $("#stage2-result").className="convergence fail"; $("#stage2-result").innerHTML=`<strong>Extraction failed</strong><span>${escapeHtml(error.message)}</span>`; button.disabled=false; }
});

function refreshCompareGate() { $("#compare-button").disabled=!(okfReady&&ragReady); }

$("#okf-build-button").addEventListener("click", async () => {
  const button=$("#okf-build-button"); button.disabled=true; $("#okf-build-result").textContent="Building and validating evidence-linked records…";
  try { const result=await api(`/api/corpora/${activeCorpusId}/okf/build`, {method:"POST"}); okfReady=true; const counts=result.counts||{}; $("#okf-build-result").textContent=`Ready · critic ${result.critic.verdict} · ${counts.claims||0} claims · ${counts.entities||0} entities · ${counts.relationships||0} relationships · ${counts.conflicts||0} potential conflicts`; refreshCompareGate(); }
  catch(error) { $("#okf-build-result").textContent=`Failed: ${error.message}`; button.disabled=false; }
});

$("#rag-build-button").addEventListener("click", async () => {
  const button=$("#rag-build-button"); button.disabled=true; $("#rag-build-result").textContent="Building hybrid parent–child index…";
  try { const result=await api(`/api/corpora/${activeCorpusId}/rag/build`, {method:"POST"}); ragReady=true; $("#rag-build-result").textContent=`Ready · critic ${result.critic.verdict} · ${result.chunk_count} child chunks · ${result.parent_count} parents · ${result.embedding_version} · ${result.embedding_dimensions}D · ${result.vector_backend}`; refreshCompareGate(); }
  catch(error) { $("#rag-build-result").textContent=`Failed: ${error.message}`; button.disabled=false; }
});

function renderKnowledgeResult(result) {
  const status=`<span class="badge">${escapeHtml(result.status)}</span> · ${Number(result.latency_ms||0).toFixed(1)} ms`;
  const answer=result.answer ? `<h3>${escapeHtml(result.answer)}</h3>` : `<h3>Abstained</h3><p>${escapeHtml(result.reason||"No grounded answer")}</p>`;
  const citations=(result.citations||[]).map(item=>`<div class="citation"><strong>${escapeHtml(item.source_url||"Stored source")}</strong><br>${escapeHtml(item.quote)}<br><span class="mono">${escapeHtml(item.unit_id)} · score ${escapeHtml(item.score)}</span></div>`).join("");
  return `${status}${answer}<div class="citation-list">${citations}</div>`;
}

$("#compare-button").addEventListener("click", async () => {
  const question=$("#knowledge-question").value.trim();
  if (!question) { toast("Enter a question to compare"); return; }
  const button=$("#compare-button"); button.disabled=true;
  const kind=$("#knowledge-kind").value; const filters=kind?{kind}:{};
  try { const result=await api(`/api/corpora/${activeCorpusId}/compare`, {method:"POST",body:JSON.stringify({question,filters})}); $("#comparison-results").classList.remove("hidden"); $("#okf-answer").innerHTML=renderKnowledgeResult(result.okf); $("#rag-answer").innerHTML=renderKnowledgeResult(result.rag); }
  catch(error) { toast(error.message); }
  finally { refreshCompareGate(); }
});

function escapeHtml(value) { const div=document.createElement("div"); div.textContent=String(value); return div.innerHTML; }

loadRagRuntime();
