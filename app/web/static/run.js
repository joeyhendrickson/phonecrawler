function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const runId = window.PHONE_CRAWLER_RUN_ID;
let activeTab = "inventory";
let cache = { inventory: null, occurrences: null, coverage: null, errors: null };

const metricKeys = [
  ["Unique phone numbers", "Unique phones"],
  ["Total phone occurrences", "Occurrences"],
  ["URLs crawled", "URLs crawled"],
  ["Valid phone numbers", "Valid"],
  ["Possible phone numbers", "Possible"],
  ["Failed URLs", "Failed"],
  ["JavaScript-rendered pages", "JS pages"],
  ["PDFs processed", "PDFs"],
];

function statusClass(status) {
  if (status === "complete") return "text-tide-dark";
  if (status === "running" || status === "queued") return "text-rust";
  if (status === "error") return "text-red-700";
  return "text-ink-muted";
}

function renderMetrics(summary) {
  const root = document.getElementById("metrics");
  root.innerHTML = metricKeys
    .map(([key, label]) => {
      const value = summary[key] ?? summary[label] ?? "—";
      return `<article class="rounded-2xl border border-paper-rule bg-paper-card p-4 shadow-card">
        <p class="text-xs uppercase tracking-[0.16em] text-ink-faint">${label}</p>
        <p class="mt-1 font-display text-2xl">${value}</p>
      </article>`;
    })
    .join("");
}

function renderTable(rows) {
  const filter = (document.getElementById("filter").value || "").toLowerCase();
  const filtered = (rows || []).filter((row) => JSON.stringify(row).toLowerCase().includes(filter));
  const slice = filtered.slice(0, 250);
  if (!slice.length) {
    document.getElementById("table-wrap").innerHTML =
      '<p class="p-6 text-sm text-ink-muted">No rows yet. Logs will appear while the crawl runs.</p>';
    return;
  }
  const cols = Object.keys(slice[0]).slice(0, 10);
  const head = cols.map((col) => `<th class="px-3 py-2 text-left font-medium">${col}</th>`).join("");
  const body = slice
    .map((row) => {
      const cells = cols
        .map((col) => {
          const value = row[col] ?? "";
          const safe = escapeHtml(text);
          if (String(value).startsWith("http")) {
            return `<td class="px-3 py-2"><a class="text-tide underline" href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${safe}</a></td>`;
          }
          return `<td class="px-3 py-2">${safe}</td>`;
        })
        .join("");
      return `<tr class="border-t border-paper-rule">${cells}</tr>`;
    })
    .join("");
  document.getElementById("table-wrap").innerHTML = `
    <p class="mb-2 text-xs text-ink-faint">${filtered.length} matching rows</p>
    <table class="min-w-full text-sm">
      <thead class="bg-paper text-ink-muted">${head}</thead>
      <tbody>${body}</tbody>
    </table>`;
}

async function loadTab(name, force = false) {
  if (name === "logs") return;
  if (!force && cache[name]) {
    renderTable(cache[name]);
    return;
  }
  const response = await fetch(`/api/crawls/${runId}/${name}`);
  if (!response.ok) {
    renderTable([]);
    return;
  }
  const data = await response.json();
  cache[name] = data.rows || [];
  renderTable(cache[name]);
}

function renderLogs(logs) {
  const lines = (logs || []).slice(-200).join("\n") || "Waiting for crawl output…";
  document.getElementById("table-wrap").innerHTML =
    `<pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap font-mono text-xs leading-5 text-ink">${lines.replace(/</g, "&lt;")}</pre>`;
}

function renderDownloads() {
  const files = [
    ["phone_inventory.csv", "Inventory CSV"],
    ["phone_occurrences.csv", "Occurrences"],
    ["url_inventory.csv", "URL inventory"],
    ["crawl_report.csv", "Coverage report"],
    ["phone_inventory.xlsx", "Excel workbook"],
  ];
  document.getElementById("downloads").innerHTML = files
    .map(
      ([file, label]) =>
        `<a class="rounded-full border border-paper-rule bg-paper-card px-3 py-1.5 text-xs hover:border-tide" href="/api/crawls/${runId}/files/${file}">${label}</a>`
    )
    .join("");
}

async function refresh() {
  const response = await fetch(`/api/crawls/${runId}`);
  if (!response.ok) return;
  const job = await response.json();
  document.getElementById("run-title").textContent = job.start_url || runId;
  document.getElementById("run-status").className = `mt-1 font-mono text-sm ${statusClass(job.status)}`;
  document.getElementById("run-status").textContent = `${job.status} · ${job.output_dir || ""}`;
  renderMetrics(job.summary || {});
  renderDownloads();
  if (activeTab === "logs") renderLogs(job.logs);
  else await loadTab(activeTab, job.status === "running");
  if (job.status === "running" || job.status === "queued") {
    setTimeout(refresh, 1500);
  }
}

document.getElementById("tabs").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-tab]");
  if (!button) return;
  activeTab = button.dataset.tab;
  document.querySelectorAll(".tab-btn").forEach((node) => {
    node.className =
      node === button
        ? "tab-btn rounded-full bg-ink px-4 py-1.5 text-sm text-paper-card"
        : "tab-btn rounded-full border border-paper-rule bg-paper-card px-4 py-1.5 text-sm";
  });
  if (activeTab === "logs") {
    const response = await fetch(`/api/crawls/${runId}`);
    const job = await response.json();
    renderLogs(job.logs);
  } else {
    await loadTab(activeTab, true);
  }
});

document.getElementById("filter").addEventListener("input", () => {
  if (activeTab !== "logs") renderTable(cache[activeTab] || []);
});

refresh();
