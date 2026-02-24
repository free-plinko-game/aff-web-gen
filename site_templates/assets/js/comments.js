/**
 * Comments widget — loads and renders threaded comments from the API.
 * Read-only in Phase 1+2 (no posting UI).
 */
(function () {
  'use strict';

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

  function renderComment(c, isReply) {
    var cls = 'comment' + (c.is_pinned ? ' comment--pinned' : '') + (isReply ? ' comment--reply' : '');
    var pinBadge = c.is_pinned ? '<span class="comment-pin">Pinned</span>' : '';
    var score = (c.upvotes || 0) - (c.downvotes || 0);
    var scoreClass = score > 0 ? 'comment-score--positive' : score < 0 ? 'comment-score--negative' : '';

    var repliesHtml = '';
    if (c.replies && c.replies.length) {
      repliesHtml = '<div class="comment-replies">';
      for (var i = 0; i < c.replies.length; i++) {
        repliesHtml += renderComment(c.replies[i], true);
      }
      repliesHtml += '</div>';
    }

    return '<div class="' + cls + '">' +
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
      repliesHtml +
    '</div>';
  }

  function init() {
    var container = document.querySelector('.comments-section');
    if (!container) return;

    var apiUrl = container.getAttribute('data-api-url');
    var siteId = container.getAttribute('data-site-id');
    var pageSlug = container.getAttribute('data-page-slug');
    if (!apiUrl || !siteId || !pageSlug) return;

    var listEl = container.querySelector('.comments-list');
    var countEl = container.querySelector('.comments-count');
    var url = apiUrl.replace(/\/+$/, '') + '/comments-api/' + siteId + '/' + pageSlug;

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
          listEl.innerHTML = '<p class="comments-empty">No comments yet. Check back later!</p>';
          return;
        }

        var html = '';
        for (var i = 0; i < comments.length; i++) {
          html += renderComment(comments[i], false);
        }
        listEl.innerHTML = html;
      })
      .catch(function () {
        listEl.innerHTML = '<p class="comments-empty">Comments unavailable.</p>';
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
