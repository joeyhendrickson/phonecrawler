async function startCrawl(event) {
  event.preventDefault();
  const form = event.target;
  const error = document.getElementById("form-error");
  error.classList.add("hidden");
  const data = Object.fromEntries(new FormData(form).entries());
  const payload = {
    start_url: data.start_url,
    country: data.country || "US",
    max_pages: Number(data.max_pages || 500),
    max_depth: Number(data.max_depth || 8),
    concurrency: Number(data.concurrency || 6),
    delay: Number(data.delay || 0.35),
    timeout: Number(data.timeout || 20),
    render_js: data.render_js || "auto",
    include_pdfs: Boolean(data.include_pdfs),
    respect_robots: Boolean(data.respect_robots),
    discover_sitemaps: Boolean(data.discover_sitemaps),
    allow_subdomains: Boolean(data.allow_subdomains),
  };
  const response = await fetch("/api/crawls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    error.textContent = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    error.classList.remove("hidden");
    return;
  }
  window.location.href = `/runs/${body.id}`;
}

const form = document.getElementById("crawl-form");
if (form) form.addEventListener("submit", startCrawl);
