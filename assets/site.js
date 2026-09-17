/* cxpaper.com — reads the current build straight from the GitHub Releases API,
   so the download page can never go stale against the binary.

   The release notes written by tools/release.bat carry a line of the form
       SHA-256: <64 hex chars>
   which is what the hash below is read from. */

var CONFIG = {
  releasesOwner: "antigomer",
  releasesRepo: "cxpaper-releases",
  assetMatch: /^ConstructionPaper.*\.exe$/i,

  // Where a license request is sent. GitHub Pages serves files and nothing
  // else - it cannot receive a form - so this is the one address on the site
  // that is not GitHub. Empty until the endpoint exists, and while it is
  // empty the form says so and hands the visitor the email instead of
  // pretending to send. Fill it in and nothing else here changes.
  licenseApi: "https://cxpaper-license.chris-73e.workers.dev/request",
  supportEmail: "chris@chrisputnam.me"
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
            // The button now points straight at the exe, so say so: a label
            // that still reads "on GitHub" promises a page and delivers a
            // 30 MB download. It is the SECOND button now - requesting a
            // license comes first - so it names who it is for, because the
            // file is useless to anybody without a key.
            a.textContent = "Already have a key? Download " + asset.name +
              " (" + bytes(asset.size) + ")";
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

  // The storybook is a 20 s loop that never stops. Off screen it is still
  // costing paint time and battery on a phone, so it is parked (paused, not
  // reset) while it is scrolled out of view and resumes where it left off.
  function parkStorybook() {
    // Was one storybook, is now one per tab of the program. Each gets its own
    // observer entry; a panel that is hidden is not animating at all, so this
    // only ever has real work to do for the tab on show.
    var scopes = document.querySelectorAll(".cps-scope, .gst-scope, .mpo-scope");
    if (!scopes.length || !("IntersectionObserver" in window)) return;
    var io = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        entries[i].target.classList.toggle("is-parked", !entries[i].isIntersecting);
      }
    }, { threshold: 0 });
    for (var i = 0; i < scopes.length; i++) io.observe(scopes[i]);
  }


  // ---- the storybook tabs -------------------------------------------------
  // Switching hides the other panel outright rather than stacking them, so the
  // animation that is not on screen is not running: display:none stops CSS
  // animation dead, which is the cheapest pause there is.
  function storybookTabs() {
    var bar = $(".tabshow-bar");
    if (!bar) return;
    var tabs = bar.querySelectorAll('[role="tab"]');
    if (!tabs.length) return;

    function show(tab) {
      for (var i = 0; i < tabs.length; i++) {
        var on = tabs[i] === tab;
        tabs[i].setAttribute("aria-selected", on ? "true" : "false");
        tabs[i].tabIndex = on ? 0 : -1;
        var panel = document.getElementById(tabs[i].getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      }
    }

    // Hover switches tabs, per Chris. The small delay is not hesitation: the
    // tabs sit side by side, so reaching the fourth one drags the pointer
    // across the three before it, and without this each one would be shown and
    // torn down in turn - restarting a 20 s animation three times for tabs
    // nobody asked to see. 70 ms is under what reads as lag and is longer than
    // a sweep spends on a tab it is only passing over.
    var pending = null;
    function later(tab) {
      if (pending) clearTimeout(pending);
      if (tab.getAttribute("aria-selected") === "true") return;
      pending = setTimeout(function () { pending = null; show(tab); }, 70);
    }
    function cancel() { if (pending) { clearTimeout(pending); pending = null; } }

    for (var i = 0; i < tabs.length; i++) {
      // Click still works, and has to: a phone has no hover, and a tap that
      // did nothing would look broken.
      tabs[i].addEventListener("click", function () { cancel(); show(this); });
      tabs[i].addEventListener("mouseenter", function () { later(this); });
      tabs[i].addEventListener("mouseleave", cancel);
      // Tabbing to one with the keyboard shows it too, so the focus ring is
      // never sitting on a tab whose panel is not the one underneath.
      tabs[i].addEventListener("focus", function () { cancel(); show(this); });
    }
    bar.addEventListener("mouseleave", cancel);

    // Left/right arrows move between tabs, which is what a tablist is expected
    // to do and what a keyboard user will try.
    bar.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var list = [], k;
      for (k = 0; k < tabs.length; k++) list.push(tabs[k]);
      var at = list.indexOf(document.activeElement);
      if (at < 0) return;
      var next = list[(at + (e.key === "ArrowRight" ? 1 : list.length - 1)) % list.length];
      show(next);
      next.focus();
      e.preventDefault();
    });
  }


  // ---- the license request form -----------------------------------------
  // Four answers, sent to CONFIG.licenseApi, which hands back a key from the
  // batch. Nothing emails it: the key is shown on the page, once, and the
  // panel says so. Any wording about an email arriving is a promise nothing
  // in this system keeps.
  // Everything that can go wrong ends with the visitor holding an address to
  // write to: a form that fails silently is a customer who never asks twice.

  function fieldOf(input) { return input.closest ? input.closest(".field") : null; }

  function complain(input, why) {
    var field = fieldOf(input);
    if (!field) return;
    field.classList.add("bad");
    var note = field.querySelector(".why");
    if (!note) {
      note = document.createElement("p");
      note.className = "why";
      note.id = input.id + "-why";
      field.appendChild(note);
    }
    note.textContent = why;
    // Said out loud, not only shown. Without these, somebody using a screen
    // reader lands back on the box and hears "Phone" - never the reason.
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", note.id);
  }

  function clearComplaint(input) {
    var field = fieldOf(input);
    if (!field) return;
    field.classList.remove("bad");
    var note = field.querySelector(".why");
    if (note) note.remove();
    input.removeAttribute("aria-invalid");
    input.removeAttribute("aria-describedby");
  }

  function looksLikeEmail(v) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);
  }

  function looksLikePhone(v) {
    // Ten digits or more, however they were typed. Country codes, spaces,
    // brackets and dashes are all somebody's normal way of writing it.
    return (v.match(/\d/g) || []).length >= 10;
  }

  function checkForm(fields) {
    var firstBad = null;
    Object.keys(fields).forEach(function (key) {
      var input = fields[key];
      var v = input.value.trim();
      clearComplaint(input);
      var why = "";
      if (!v) {
        why = "Needed.";
      } else if (key === "email" && !looksLikeEmail(v)) {
        why = "That address is missing something - the key is sent to it.";
      } else if (key === "phone" && !looksLikePhone(v)) {
        why = "That looks short for a phone number.";
      }
      if (why) {
        complain(input, why);
        if (!firstBad) firstBad = input;
      }
    });
    return firstBad;
  }

  function wireRequestForm() {
    var form = $("#license-request");
    if (!form) return;

    var state = $("[data-request=state]", form);
    var button = $("[data-request=submit]", form);
    var sent = $("[data-request=sent]");
    var fields = {
      name: $("#rq-name"), email: $("#rq-email"),
      phone: $("#rq-phone"), project: $("#rq-project")
    };
    var trap = $("#rq-note-2");
    var copyBtn = sent ? $("[data-request=copy]", sent) : null;
    var copied = sent ? $("[data-request=copied]", sent) : null;

    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var box = $("[data-request=key]", sent);
        if (!box) return;
        box.focus();
        box.select();
        var done = false;
        try { done = document.execCommand("copy"); } catch (e) { done = false; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(box.value).then(function () {
            if (copied) copied.textContent = "Copied.";
          }, function () {
            // A blocked clipboard is not a dead end: the text is selected, so
            // say the thing they can still do rather than "failed".
            if (copied) copied.textContent = done ? "Copied." : "Press Ctrl+C now.";
          });
        } else if (copied) {
          copied.textContent = done ? "Copied." : "Press Ctrl+C now.";
        }
      });
    }

    Object.keys(fields).forEach(function (key) {
      fields[key].addEventListener("input", function () { clearComplaint(fields[key]); });
    });

    function say(message, bad) {
      state.textContent = message || "";
      state.className = "form-state" + (bad ? " bad" : "");
    }

    function mailtoFallback() {
      var body = "Name: "    + fields.name.value    + "\n" +
                 "Phone: "   + fields.phone.value   + "\n" +
                 "Email: "   + fields.email.value   + "\n" +
                 "Project: " + fields.project.value + "\n";
      return "mailto:" + CONFIG.supportEmail +
             "?subject=" + encodeURIComponent("Construction Paper license request") +
             "&body=" + encodeURIComponent(body);
    }

    function failOver(message) {
      say("", false);
      var row = button.parentNode;
      var link = row.querySelector("[data-request=mailto]");
      if (!link) {
        link = document.createElement("a");
        link.className = "btn ghost";
        link.setAttribute("data-request", "mailto");
        row.insertBefore(link, state);
      }
      link.setAttribute("href", mailtoFallback());
      link.textContent = "Send it as an email instead";
      say(message, true);
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var firstBad = checkForm(fields);
      if (firstBad) {
        say("Fix the marked answers and send again.", true);
        firstBad.focus();
        return;
      }
      if (trap && trap.value) {          // a person never fills this in
        say("Thanks - that has been sent.", false);
        return;
      }
      if (!CONFIG.licenseApi) {
        failOver("Requests are not switched on yet. Email it and you will get the same answer.");
        return;
      }

      button.disabled = true;
      say("Sending...", false);

      fetch(CONFIG.licenseApi, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fields.name.value.trim(),
          email: fields.email.value.trim(),
          phone: fields.phone.value.trim(),
          project: fields.project.value.trim()
        })
      })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (doc) {
            if (!r.ok) throw new Error(doc.error || ("HTTP " + r.status));
            return doc;
          });
        })
        .then(function (doc) {
          // The key is IN this reply and the pool has already been debited for
          // it. Dropping it on the floor here means a key spent, a customer
          // recorded as served, and nothing in their hands.
          form.hidden = true;
          if (sent) {
            var box = $("[data-request=key]", sent);
            if (box) box.value = doc.key || "";
            sent.hidden = false;
            sent.scrollIntoView({ block: "nearest" });
            if (box) { box.focus(); box.select(); }
          }
        })
        .catch(function (err) {
          button.disabled = false;
          // The worker's own sentences are already in Chris's voice and say
          // something true and specific ("no keys in stock this minute, email
          // him and you will get one today"). Replacing them with a house
          // generic throws that away and reads like the visitor's fault.
          failOver((err && err.message) ||
                   "That did not go through. Nothing was lost - send it as an email.");
          if (window.console) console.warn("license request:", err);
        });
    });
  }

  markNav();
  stampYear();
  fillRelease();
  fillStatus();
  parkStorybook();
  storybookTabs();
  wireRequestForm();
})();
