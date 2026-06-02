/* app.js — backwards compat shim
   All actual logic is now in shared.js
   This file is kept so old references don't break. */
document.addEventListener('DOMContentLoaded', function() {
  // API client for page scripts that use BizAL.API
  if (window.BizAL && !window.BizAL.API) {
    window.BizAL.API = {
      get:      (ep) => {
        const {access} = window.BizAL.Auth.getTokens();
        const h = {'Content-Type':'application/json'};
        if (access) h['Authorization'] = 'Bearer ' + access;
        return fetch('/api' + ep, {headers: h});
      },
      post:     (ep, body) => {
        const {access} = window.BizAL.Auth.getTokens();
        const h = {'Content-Type':'application/json'};
        if (access) h['Authorization'] = 'Bearer ' + access;
        return fetch('/api' + ep, {method:'POST', headers:h, body:JSON.stringify(body)});
      },
      patch:    (ep, body) => {
        const {access} = window.BizAL.Auth.getTokens();
        const h = {'Content-Type':'application/json'};
        if (access) h['Authorization'] = 'Bearer ' + access;
        return fetch('/api' + ep, {method:'PATCH', headers:h, body:JSON.stringify(body)});
      },
      isLoggedIn: () => window.BizAL.Auth.isLoggedIn(),
      getTokens:  () => window.BizAL.Auth.getTokens(),
      saveTokens: (a,r) => window.BizAL.Auth.saveTokens(a,r),
      clearTokens: () => window.BizAL.Auth.clearTokens(),
    };
  }
});
