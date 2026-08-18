async function readJson(response) {
  const text = await response.text();
  if (!text) {
    throw new Error(`Empty response (${response.status})`);
  }
  try {
    return JSON.parse(text);
  } catch {
    const snippet = text.replace(/\s+/g, " ").trim().slice(0, 180);
    throw new Error(snippet || `Request failed (${response.status})`);
  }
}

async function startCrawl(event) {
  event.preventDefault();
  const form = event.target;
  const error = document.getElementById("form-error");
  const button = form.querySelector("button[type=submit]");
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
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Crawling…";
  try {
    const response = await fetch("/api/crawls", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await readJson(response);
    if (!response.ok) {
      error.textContent = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      error.classList.remove("hidden");
      return;
    }
    sessionStorage.setItem(`crawl:${body.id}`, JSON.stringify(body));
    window.location.href = `/runs/${body.id}`;
  } catch (err) {
    error.textContent = err instanceof Error ? err.message : "Crawl failed.";
    error.classList.remove("hidden");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

const form = document.getElementById("crawl-form");
if (form) form.addEventListener("submit", startCrawl);
