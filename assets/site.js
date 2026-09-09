/* cxpaper.com — reads the current build straight from the GitHub Releases API,
   so the download page can never go stale against the binary.

   The release notes written by tools/release.bat carry a line of the form
       SHA-256: <64 hex chars>
   which is what the hash below is read from. */

var CONFIG = {
  releasesOwner: "antigomer",
  releasesRepo: "cxpaper-releases",
  assetMatch: /^ConstructionPaper.*\.exe$/i
};

(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function setText(sel, value) {
    all(sel).forEach(function (el) { el.textContent = value; });
  }

  function bytes(n) {
    if (typeof n !== "number" || !isFinite(n)) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function day(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return "—";
    return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  }

  function markNav() {
    var here = location.pathname.replace(/index\.html$/, "").replace(/\/$/, "") || "/";
    all(".site-nav a").forEach(function (a) {
      var target = a.getAttribute("href").replace(/index\.html$/, "").replace(/\/$/, "") || "/";
      if (target === here) a.setAttribute("aria-current", "page");
    });
  }

  function fillRelease() {
    if (!all("[data-release]").length) return;

    var url = "https://api.github.com/repos/" +
      CONFIG.releasesOwner + "/" + CONFIG.releasesRepo + "/releases/latest";

    fetch(url, { headers: { Accept: "application/vnd.github+json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (rel) {
        var asset = (rel.assets || []).filter(function (a) {
          return CONFIG.assetMatch.test(a.name);
        })[0] || (rel.assets || [])[0];

        var hash = "—";
        var m = /SHA-?256\s*[:=]\s*([0-9a-f]{64})/i.exec(rel.body || "");
        if (m) hash = m[1].toLowerCase();

        setText("[data-release=version]", rel.tag_name || rel.name || "—");
        setText("[data-release=date]", day(rel.published_at || rel.created_at));
        setText("[data-release=size]", asset ? bytes(asset.size) : "—");
        setText("[data-release=hash]", hash);
        setText("[data-release=filename]", asset ? asset.name : "—");

        all("[data-release=link]").forEach(function (a) {
          if (asset) {
            a.setAttribute("href", asset.browser_download_url);
            a.removeAttribute("aria-disabled");
          } else {
            a.setAttribute("href", rel.html_url || "#");
          }
        });

        all("[data-release=notes]").forEach(function (el) {
          el.textContent = (rel.body || "").trim() || "No notes for this release.";
        });

        all("[data-release-state]").forEach(function (el) {
          el.setAttribute("data-release-state", "ready");
        });
      })
      .catch(function (err) {
        setText("[data-release=version]", "unavailable");
        setText("[data-release=date]", "—");
        setText("[data-release=size]", "—");
        setText("[data-release=hash]", "—");
        setText("[data-release=filename]", "—");
        all("[data-release=notes]").forEach(function (el) {
          el.textContent = "Could not reach the Releases API. Open the releases page for the current build.";
        });
        all("[data-release=link]").forEach(function (a) {
          a.setAttribute("href", "https://github.com/" + CONFIG.releasesOwner + "/" + CONFIG.releasesRepo + "/releases");
        });
        all("[data-release-state]").forEach(function (el) {
          el.setAttribute("data-release-state", "error");
        });
        if (window.console) console.warn("Releases API:", err);
      });
  }

  function fillStatus() {
    var host = $("[data-status]");
    if (!host) return;

    fetch("status.json", { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (doc) {
        var p = doc.payload || {};
        var revoked = p.revoked || [];
        setText("[data-status=format]", String(p.format != null ? p.format : "—"));
        setText("[data-status=updated]", p.updated ? new Date(p.updated * 1000).toISOString().replace("T", " ").replace(/\..+/, " UTC") : "—");
        setText("[data-status=count]", String(revoked.length));
        var chip = $("[data-status=chip]");
        if (chip) {
          chip.textContent = revoked.length === 0 ? "0 revoked" : revoked.length + " revoked";
          chip.className = "chip " + (revoked.length === 0 ? "ok" : "look");
        }
      })
      .catch(function () {
        setText("[data-status=format]", "—");
        setText("[data-status=updated]", "unreachable");
        setText("[data-status=count]", "—");
        var chip = $("[data-status=chip]");
        if (chip) { chip.textContent = "unreachable"; chip.className = "chip fail"; }
      });
  }

  function stampYear() { setText("[data-year]", String(new Date().getFullYear())); }

  markNav();
  stampYear();
  fillRelease();
  fillStatus();
})();
