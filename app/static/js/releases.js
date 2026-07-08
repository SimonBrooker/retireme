// Version & releases page. Fetches the repo's GitHub releases client-side (CSP
// already allows api.github.com) and renders them. Release notes are markdown;
// we HTML-escape first, then apply a small, safe subset of formatting — never
// inject unescaped API text.
(function () {
  const root = document.getElementById("releases");
  if (!root) return;
  const repo = root.dataset.repo;
  const current = root.dataset.current;
  const statusEl = document.getElementById("version-status");

  function esc(s) {
    return (s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Inline formatting on already-escaped text: **bold** and `code`.
  function inline(s) {
    return s
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function renderBody(md) {
    const lines = (md || "").split(/\r?\n/);
    let html = "";
    let inCode = false;
    let code = [];
    let inList = false;
    let para = [];  // buffer of consecutive plain lines that form one paragraph
    const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
    // A blank line, or any block-level element, ends the current paragraph. Soft
    // (single) line breaks within it are reflowed into one flowing paragraph.
    const flushPara = () => {
      if (para.length) { html += "<p>" + inline(esc(para.join(" "))) + "</p>"; para = []; }
    };
    for (const raw of lines) {
      if (raw.trim().startsWith("```")) {
        if (inCode) { html += '<pre class="rel-code">' + esc(code.join("\n")) + "</pre>"; code = []; inCode = false; }
        else { flushPara(); closeList(); inCode = true; }
        continue;
      }
      if (inCode) { code.push(raw); continue; }
      const h = raw.match(/^(#{1,4})\s+(.*)$/);
      if (h) { flushPara(); closeList(); html += '<div class="rel-h">' + inline(esc(h[2])) + "</div>"; continue; }
      const li = raw.match(/^\s*[-*]\s+(.*)$/);
      if (li) { flushPara(); if (!inList) { html += '<ul class="rel-ul">'; inList = true; } html += "<li>" + inline(esc(li[1])) + "</li>"; continue; }
      if (raw.trim() === "") { flushPara(); closeList(); continue; }
      para.push(raw.trim());
    }
    flushPara();
    closeList();
    if (inCode) html += '<pre class="rel-code">' + esc(code.join("\n")) + "</pre>";
    return html || '<p class="dim">No notes.</p>';
  }

  function fmtDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  const releasesUrl = "https://github.com/" + repo + "/releases";

  fetch("https://api.github.com/repos/" + repo + "/releases?per_page=30", {
    headers: { Accept: "application/vnd.github+json" },
  })
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((data) => {
      if (!Array.isArray(data) || data.length === 0) {
        root.innerHTML = '<div class="empty-note">No releases found. <a href="' + releasesUrl + '" target="_blank" rel="noopener">View on GitHub ↗</a></div>';
        if (statusEl) statusEl.textContent = "";
        return;
      }

      // "Up to date" is measured against the newest stable (non-prerelease).
      const latestStable = data.find((r) => !r.prerelease && !r.draft);
      if (statusEl) {
        if (latestStable) {
          const tag = latestStable.tag_name.replace(/^v/, "");
          if (tag === current) {
            statusEl.innerHTML = '<span style="color: var(--positive);">● You\'re on the latest release.</span>';
          } else {
            statusEl.innerHTML = '<span style="color: var(--warning);">● v' + esc(tag) + ' is available</span> — see below or <a href="' + esc(latestStable.html_url) + '" target="_blank" rel="noopener">GitHub ↗</a>.';
          }
        } else {
          statusEl.textContent = "";
        }
      }

      root.innerHTML = data.map(function (r) {
        const tag = esc(r.tag_name);
        const running = r.tag_name.replace(/^v/, "") === current;
        const ghLink = /^https:\/\//.test(r.html_url)
          ? '<a href="' + esc(r.html_url) + '" target="_blank" rel="noopener" class="dim" style="font-size:0.85rem;">View on GitHub ↗</a>'
          : "";
        return (
          '<div class="chart-card rel-card">' +
            '<div class="rel-head">' +
              '<span class="rel-ver">' + tag + "</span>" +
              (running ? '<span class="badge badge-moss">Running</span>' : "") +
              (r.prerelease ? '<span class="badge badge-brass">Beta</span>' : "") +
              '<span class="dim rel-date">' + fmtDate(r.published_at) + "</span>" +
            "</div>" +
            '<div class="rel-body">' + renderBody(r.body) + "</div>" +
            ghLink +
          "</div>"
        );
      }).join("");
    })
    .catch(function () {
      root.innerHTML = '<div class="empty-note">Couldn\'t load releases (no connection or GitHub rate limit). <a href="' + releasesUrl + '" target="_blank" rel="noopener">View on GitHub ↗</a></div>';
      if (statusEl) statusEl.textContent = "";
    });
})();
