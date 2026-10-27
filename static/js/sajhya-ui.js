/*
 * Shared behaviour for the professional workspace (loaded by accounts/pro_base.html).
 *
 *   SajhyaUI.openModal(id) / closeModal(id)
 *   SajhyaUI.initModals(root)      wires [data-open="<modalId>"], [data-close], backdrop click and Esc
 *   SajhyaUI.picker(input, opts)   type-ahead dropdown against a JSON endpoint
 *   SajhyaUI.patientPicker(input, hidden, opts)   the patient search used by booking, billing, packages, exercises
 *   SajhyaUI.fetchJSON(url, opts)  fetch with the session cookie and CSRF header
 *
 * Keep page-specific behaviour in the page; put anything used by two or more pages here.
 */
(function () {
  'use strict';
  var UI = window.SajhyaUI = window.SajhyaUI || {};

  function $(id) { return document.getElementById(id); }
  function esc(text) { var d = document.createElement('div'); d.textContent = text == null ? '' : text; return d.innerHTML; }
  UI.esc = esc;

  // small exercise picture (same look as the {% exercise_thumb %} tag): the image, or a letter tile when there is none
  UI.thumb = function (name, cover) {
    if (cover) return '<img class="ex-thumb" src="' + esc(cover) + '" alt="' + esc(name) + '" loading="lazy">';
    return '<span class="ex-thumb ex-thumb-blank">' + esc(((name || '?').trim().charAt(0) || '?').toUpperCase()) + '</span>';
  };

  UI.csrfToken = function () {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var field = document.querySelector('input[name=csrfmiddlewaretoken]');
    return field ? field.value : '';
  };

  UI.fetchJSON = function (url, options) {
    options = options || {};
    options.credentials = 'same-origin';
    options.headers = Object.assign({ 'X-Requested-With': 'XMLHttpRequest' }, options.headers || {});
    if (options.method && options.method !== 'GET') options.headers['X-CSRFToken'] = UI.csrfToken();
    return fetch(url, options).then(function (r) { return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; }); });
  };

  // ---------- modals ----------
  UI.openModal = function (id) { var m = $(id); if (m) m.classList.add('open'); };
  UI.closeModal = function (id) { var m = $(id); if (m) m.classList.remove('open'); };

  var modalsReady = false;
  UI.initModals = function (root) {
    root = root || document;
    root.querySelectorAll('[data-open]').forEach(function (button) {
      if (button.dataset.uiBound) return;
      button.dataset.uiBound = '1';
      button.addEventListener('click', function () { UI.openModal(button.dataset.open); });
    });
    root.querySelectorAll('.modal-backdrop').forEach(function (modal) {
      if (modal.dataset.uiBound) return;
      modal.dataset.uiBound = '1';
      modal.addEventListener('click', function (e) {
        if (e.target === modal || (e.target.closest && e.target.closest('[data-close]'))) modal.classList.remove('open');
      });
    });
    if (!modalsReady) {
      modalsReady = true;
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') document.querySelectorAll('.modal-backdrop.open').forEach(function (m) { m.classList.remove('open'); });
      });
    }
  };

  // ---------- type-ahead ----------
  /*
   * opts.url        endpoint returning {results: [...]}
   * opts.params     optional function returning extra query params (object)
   * opts.minChars   default 2 (use 0 to also search on focus with an empty box)
   * opts.render     function(item) -> HTML for one row (defaults to item.name)
   * opts.onPick     function(item)
   * opts.onType     function() called when the user edits the text (e.g. to clear a hidden id)
   * returns { close }
   */
  // A Viber link cannot carry a message, so the link carries it in data-copy and it is copied when the link is clicked (then paste in Viber).
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-copy]');
    if (a && navigator.clipboard) navigator.clipboard.writeText(a.dataset.copy).catch(function () {});
  });

  UI.picker = function (input, opts) {
    var minChars = opts.minChars == null ? 2 : opts.minChars;
    var box = null, timer = null, items = [], idx = -1;
    function close() { if (box) { box.remove(); box = null; } items = []; idx = -1; }
    function highlight() { items.forEach(function (it, i) { it.el.style.background = i === idx ? '#ecfdf5' : ''; }); }
    function render(results) {
      close();
      box = document.createElement('ul');
      box.className = 'icd-list';
      if (!results.length) {
        box.innerHTML = '<li style="cursor:default;color:#7c9186">' + esc(opts.emptyText || 'No matches') + '</li>';
      }
      results.forEach(function (item) {
        var li = document.createElement('li');
        li.innerHTML = opts.render ? opts.render(item) : esc(item.name);
        li.addEventListener('mousedown', function (e) { e.preventDefault(); close(); opts.onPick(item); });
        box.appendChild(li);
        items.push({ el: li, item: item });
      });
      input.parentNode.style.position = 'relative';
      input.parentNode.appendChild(box);
    }
    function search() {
      clearTimeout(timer);
      var q = input.value.trim();
      if (q.length < minChars) { close(); return; }
      timer = setTimeout(function () {
        var params = Object.assign({ q: q }, opts.params ? opts.params() : {});
        var query = Object.keys(params).map(function (k) { return k + '=' + encodeURIComponent(params[k]); }).join('&');
        UI.fetchJSON(opts.url + '?' + query).then(function (res) {
          if (input.value.trim() === q && res.data && res.data.results) render(res.data.results);
        }).catch(close);
      }, 180);
    }
    input.setAttribute('autocomplete', 'off');
    input.addEventListener('input', function () { if (opts.onType) opts.onType(); search(); });
    if (minChars === 0) input.addEventListener('focus', search);
    input.addEventListener('blur', function () { setTimeout(close, 150); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { close(); return; }
      if (!items.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        idx = (idx + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        highlight();
      } else if (e.key === 'Enter' && idx >= 0) {
        e.preventDefault();
        var picked = items[idx].item; close(); opts.onPick(picked);
      }
    });
    return { close: close };
  };

  /*
   * Patient search used wherever a form needs to pick one of the professional's patients.
   * input   the visible search box
   * hidden  the <input type=hidden> that receives the patient id
   * opts    { url, hint (element showing the chosen code), onPick(patient), preset: {id,name,code} }
   * Also blocks the form submit until a patient was picked.
   */
  UI.patientPicker = function (input, hidden, opts) {
    opts = opts || {};
    function set(p) {
      hidden.value = p.id; input.value = p.name;
      if (opts.hint) opts.hint.textContent = p.code + (p.phone ? ' · ' + p.phone : '');
      if (opts.onPick) opts.onPick(p);
    }
    UI.picker(input, {
      url: opts.url, minChars: opts.minChars == null ? 0 : opts.minChars, emptyText: 'No matching patients',
      render: function (p) { return '<b>' + esc(p.name) + '</b> <span style="color:#7c9186">' + esc(p.code) + (p.phone ? ' · ' + esc(p.phone) : '') + '</span>'; },
      onPick: set,
      onType: function () { hidden.value = ''; if (opts.hint) opts.hint.textContent = ''; },
    });
    if (opts.preset) set(opts.preset);
    if (input.form) {
      input.form.addEventListener('submit', function (e) {
        if (hidden.value) return;
        e.preventDefault(); input.focus();
        input.setCustomValidity('Pick a patient from the list'); input.reportValidity(); input.setCustomValidity('');
      });
    }
    return { set: set };
  };

  document.addEventListener('DOMContentLoaded', function () { UI.initModals(); });
})();
