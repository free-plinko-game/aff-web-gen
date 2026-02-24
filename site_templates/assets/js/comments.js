/**
 * Comments widget — loads, renders, and posts threaded comments via API.
 */
(function () {
  'use strict';

  // Module state
  var apiBaseUrl = '';
  var siteId = '';
  var pageSlug = '';
  var listEl = null;
  var countEl = null;

  function timeAgo(isoString) {
    if (!isoString) return '';
    var diff = (Date.now() - new Date(isoString).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
    return new Date(isoString).toLocaleDateString();
  }

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text;
    return d.innerHTML;
  }

  var flaggedIds = [];
  try { flaggedIds = JSON.parse(localStorage.getItem('flagged_comments') || '[]'); } catch (ex) {}

  function renderComment(c, isReply) {
    var cls = 'comment' + (c.is_pinned ? ' comment--pinned' : '') + (isReply ? ' comment--reply' : '');
    var pinBadge = c.is_pinned ? '<span class="comment-pin">Pinned</span>' : '';
    var score = (c.upvotes || 0) - (c.downvotes || 0);
    var scoreClass = score > 0 ? 'comment-score--positive' : score < 0 ? 'comment-score--negative' : '';
    var alreadyFlagged = flaggedIds.indexOf(c.id) !== -1;
    // For replies, flatten parent_id to root so reply-to-reply goes to root
    var effectiveParentId = c.parent_id || c.id;

    var repliesHtml = '';
    if (c.replies && c.replies.length) {
      repliesHtml = '<div class="comment-replies">';
      for (var i = 0; i < c.replies.length; i++) {
        repliesHtml += renderComment(c.replies[i], true);
      }
      repliesHtml += '</div>';
    }

    return '<div class="' + cls + '" data-comment-id="' + c.id + '">' +
      '<div class="comment-header">' +
        '<img class="comment-avatar" src="' + escapeHtml(c.avatar_url) + '" alt="" width="36" height="36" loading="lazy">' +
        '<div class="comment-meta">' +
          '<span class="comment-username">' + escapeHtml(c.display_name || c.username) + '</span>' +
          '<span class="comment-time">' + timeAgo(c.created_at) + '</span>' +
          pinBadge +
        '</div>' +
        '<span class="comment-score ' + scoreClass + '">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 19V5M5 12l7-7 7 7"/></svg>' +
          ' ' + score +
        '</span>' +
      '</div>' +
      '<div class="comment-body">' + escapeHtml(c.body) + '</div>' +
      '<button class="comment-reply-btn" data-parent-id="' + effectiveParentId + '">Reply</button>' +
      '<button class="comment-flag-btn" data-comment-id="' + c.id + '"' +
        (alreadyFlagged ? ' disabled' : '') + '>' +
        (alreadyFlagged ? 'Reported' : 'Report') +
      '</button>' +
      '<div class="comment-reply-form-slot"></div>' +
      repliesHtml +
    '</div>';
  }

  function buildCommentForm(parentId) {
    var isReply = !!parentId;
    return '<form class="comment-form' + (isReply ? ' comment-form--reply' : '') +
      '" data-parent-id="' + (parentId || '') + '">' +
      '<div class="comment-form-fields">' +
        '<input type="text" name="name" placeholder="Your name" class="comment-input comment-input--name" required maxlength="50">' +
        '<input type="email" name="email" placeholder="Email (not displayed)" class="comment-input comment-input--email" required>' +
      '</div>' +
      '<textarea name="body" placeholder="' + (isReply ? 'Write a reply...' : 'Share your thoughts...') +
        '" class="comment-textarea" required maxlength="500" rows="' + (isReply ? '2' : '3') + '"></textarea>' +
      '<input type="text" name="website" class="comment-hp" tabindex="-1" autocomplete="off">' +
      '<div class="comment-form-actions">' +
        '<span class="comment-form-note">Email will not be published</span>' +
        (isReply ? '<button type="button" class="comment-cancel-btn">Cancel</button>' : '') +
        '<button type="submit" class="comment-submit-btn">' + (isReply ? 'Post Reply' : 'Post Comment') + '</button>' +
      '</div>' +
      '<div class="comment-form-msg"></div>' +
    '</form>';
  }

  function showMsg(el, text, isError) {
    el.textContent = text;
    el.className = 'comment-form-msg' + (isError ? ' comment-form-msg--error' : ' comment-form-msg--success');
    if (!isError) {
      setTimeout(function () { el.textContent = ''; el.className = 'comment-form-msg'; }, 3000);
    }
  }

  function prefillForm(form) {
    if (!form) return;
    try {
      var n = localStorage.getItem('comment_name');
      var e = localStorage.getItem('comment_email');
      if (n) form.querySelector('[name="name"]').value = n;
      if (e) form.querySelector('[name="email"]').value = e;
    } catch (ex) { /* localStorage unavailable */ }
  }

  function postComment(form) {
    var parentId = form.getAttribute('data-parent-id') || null;
    var nameInput = form.querySelector('[name="name"]');
    var emailInput = form.querySelector('[name="email"]');
    var bodyInput = form.querySelector('[name="body"]');
    var honeypot = form.querySelector('[name="website"]');
    var submitBtn = form.querySelector('.comment-submit-btn');
    var msgEl = form.querySelector('.comment-form-msg');

    var payload = {
      name: nameInput.value.trim(),
      email: emailInput.value.trim(),
      body: bodyInput.value.trim(),
      parent_id: parentId ? parseInt(parentId, 10) : null,
      website: honeypot.value
    };

    // Client-side checks
    if (payload.name.length < 2) { showMsg(msgEl, 'Name must be at least 2 characters.', true); return; }
    if (payload.body.length < 10) { showMsg(msgEl, 'Comment must be at least 10 characters.', true); return; }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Posting...';

    var url = apiBaseUrl.replace(/\/+$/, '') + '/comments-api/' + siteId + '/' + pageSlug;

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    .then(function (res) {
      return res.json().then(function (data) { return { status: res.status, data: data }; });
    })
    .then(function (result) {
      submitBtn.disabled = false;
      submitBtn.textContent = parentId ? 'Post Reply' : 'Post Comment';

      if (result.status === 201 && result.data.success) {
        showMsg(msgEl, 'Comment posted!', false);
        try {
          localStorage.setItem('comment_name', payload.name);
          localStorage.setItem('comment_email', payload.email);
        } catch (ex) { /* ignore */ }
        // Clear the body field
        bodyInput.value = '';
        // Re-fetch comments
        setTimeout(loadComments, 500);
      } else if (result.status === 429) {
        showMsg(msgEl, (result.data.errors && result.data.errors[0]) || 'Rate limited. Try again later.', true);
      } else {
        var errMsg = (result.data.errors && result.data.errors.length)
          ? result.data.errors.join(' ')
          : 'Something went wrong.';
        showMsg(msgEl, errMsg, true);
      }
    })
    .catch(function () {
      submitBtn.disabled = false;
      submitBtn.textContent = parentId ? 'Post Reply' : 'Post Comment';
      showMsg(msgEl, 'Network error. Please try again.', true);
    });
  }

  function loadComments() {
    var url = apiBaseUrl.replace(/\/+$/, '') + '/comments-api/' + siteId + '/' + pageSlug;

    fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.json();
      })
      .then(function (data) {
        var comments = data.comments || [];
        var count = data.count || 0;
        if (countEl) countEl.textContent = '(' + count + ')';

        if (!comments.length) {
          listEl.innerHTML = '<p class="comments-empty">No comments yet. Be the first!</p>';
          return;
        }
        var html = '';
        for (var i = 0; i < comments.length; i++) {
          html += renderComment(comments[i], false);
        }
        listEl.innerHTML = html;
      })
      .catch(function (err) {
        console.error('Comments load failed:', url, err);
        listEl.innerHTML = '<p class="comments-empty">Comments unavailable. <!-- ' + url + ' : ' + (err.message || err) + ' --></p>';
      });
  }

  function init() {
    var container = document.querySelector('.comments-section');
    if (!container) return;

    apiBaseUrl = container.getAttribute('data-api-url');
    siteId = container.getAttribute('data-site-id');
    pageSlug = container.getAttribute('data-page-slug');
    if (!apiBaseUrl || !siteId || !pageSlug) return;

    listEl = container.querySelector('.comments-list');
    countEl = container.querySelector('.comments-count');

    // Load existing comments
    loadComments();

    // Append main comment form below the list
    var formContainer = document.createElement('div');
    formContainer.className = 'comment-form-container';
    formContainer.innerHTML = buildCommentForm(null);
    container.appendChild(formContainer);
    prefillForm(formContainer.querySelector('form'));

    // Event delegation for reply buttons, cancel, and form submissions
    container.addEventListener('click', function (e) {
      var replyBtn = e.target.closest('.comment-reply-btn');
      if (replyBtn) {
        e.preventDefault();
        // Remove any existing inline reply form
        var existing = container.querySelector('.comment-form--reply');
        if (existing) existing.remove();

        var parentId = replyBtn.getAttribute('data-parent-id');
        var slot = replyBtn.nextElementSibling;
        if (slot && slot.classList.contains('comment-reply-form-slot')) {
          slot.innerHTML = buildCommentForm(parentId);
          prefillForm(slot.querySelector('form'));
          slot.querySelector('textarea').focus();
        }
        return;
      }

      var flagBtn = e.target.closest('.comment-flag-btn');
      if (flagBtn && !flagBtn.disabled) {
        e.preventDefault();
        var commentId = flagBtn.getAttribute('data-comment-id');
        flagBtn.disabled = true;
        flagBtn.textContent = 'Reported';

        var flagUrl = apiBaseUrl.replace(/\/+$/, '') + '/comments-api/' + siteId + '/' + pageSlug + '/flag/' + commentId;
        fetch(flagUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' } })
          .then(function () {})
          .catch(function () {});

        try {
          flaggedIds.push(parseInt(commentId, 10));
          localStorage.setItem('flagged_comments', JSON.stringify(flaggedIds));
        } catch (ex) {}
        return;
      }

      var cancelBtn = e.target.closest('.comment-cancel-btn');
      if (cancelBtn) {
        var form = cancelBtn.closest('.comment-form--reply');
        if (form) form.remove();
      }
    });

    container.addEventListener('submit', function (e) {
      var form = e.target.closest('.comment-form');
      if (form) {
        e.preventDefault();
        postComment(form);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
