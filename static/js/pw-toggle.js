/*
 * Show / hide control for every password box on the site, so a password can be checked while it is typed
 * (sign-up, change password, the clinic login and staff logins, ...). Boxes that already carry their own
 * data-pw-toggle button (the sign-in page) are left alone.
 */
(function () {
  var EYE = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  var EYE_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.9 10.9 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A9.1 9.1 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M14.12 14.12a3 3 0 1 1-4.24-4.24"/><path d="M1 1l22 22"/></svg>';

  function enhance(input) {
    if (input.dataset.pwReady || input.parentNode.querySelector('[data-pw-toggle]')) return;
    input.dataset.pwReady = '1';
    var wrap = document.createElement('span');
    wrap.style.cssText = 'position:relative;display:block;width:100%';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    input.style.paddingRight = '40px';
    var button = document.createElement('button');
    button.type = 'button';
    button.innerHTML = EYE;
    button.setAttribute('aria-label', 'Show password');
    button.title = 'Show password';
    button.style.cssText = 'position:absolute;right:6px;top:50%;transform:translateY(-50%);border:0;background:transparent;color:#6c8178;cursor:pointer;padding:6px;line-height:0;height:auto;width:auto;min-height:0';
    button.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      button.innerHTML = show ? EYE_OFF : EYE;
      button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      button.title = show ? 'Hide password' : 'Show password';
      input.focus();
    });
    wrap.appendChild(button);
  }

  function run() { document.querySelectorAll('input[type="password"]').forEach(enhance); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
})();
