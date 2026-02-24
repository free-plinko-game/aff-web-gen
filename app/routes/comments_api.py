"""Public comments API — served to static sites via CORS."""

import hashlib
import re
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from ..models import db, Comment, CommentUser, CommentVote, Site

bp = Blueprint('comments_api', __name__, url_prefix='/comments-api')

# --- Rate limiter (in-memory, per-worker) ---
_rate_limit_store = {}
_RATE_LIMIT_MAX = 3
_RATE_LIMIT_WINDOW = 600  # 10 minutes


def _is_rate_limited(ip):
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW
    timestamps = _rate_limit_store.get(ip, [])
    timestamps = [t for t in timestamps if t > cutoff]
    _rate_limit_store[ip] = timestamps
    return len(timestamps) >= _RATE_LIMIT_MAX


def _record_request(ip):
    _rate_limit_store.setdefault(ip, []).append(time.time())


# --- Validation ---
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _validate_comment_input(data):
    """Validate guest comment. Returns ('honeypot', {}) or (errors_list, cleaned_dict)."""
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    body = (data.get('body') or '').strip()
    honeypot = (data.get('website') or '').strip()
    parent_id = data.get('parent_id')

    if honeypot:
        return 'honeypot', {}

    errors = []
    if len(name) < 2 or len(name) > 50:
        errors.append('Name must be 2-50 characters.')
    if not _EMAIL_RE.match(email):
        errors.append('Please enter a valid email address.')
    if len(body) < 10 or len(body) > 500:
        errors.append('Comment must be 10-500 characters.')
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            errors.append('Invalid parent comment.')

    return errors, {'name': name, 'email': email, 'body': body, 'parent_id': parent_id}


def _avatar_url(style, seed):
    """Build a DiceBear avatar URL."""
    style = style or 'bottts'
    seed = seed or 'default'
    return f'https://api.dicebear.com/9.x/{style}/svg?seed={seed}'


def _serialize_comment(comment, user):
    """Serialize a comment + user into a JSON-safe dict."""
    return {
        'id': comment.id,
        'username': user.username,
        'display_name': user.display_name or user.username,
        'avatar_url': _avatar_url(user.avatar_style, user.avatar_seed),
        'body': comment.body,
        'upvotes': comment.upvotes,
        'downvotes': comment.downvotes,
        'score': comment.upvotes - comment.downvotes,
        'is_pinned': comment.is_pinned,
        'created_at': comment.created_at.isoformat() if comment.created_at else None,
        'parent_id': comment.parent_id,
        'replies': [],
    }


@bp.route('/<int:site_id>/<path:page_slug>', methods=['GET'])
@cross_origin()
def get_comments(site_id, page_slug):
    """Return threaded comments for a page."""
    comments = (
        Comment.query
        .filter_by(site_id=site_id, page_slug=page_slug)
        .order_by(Comment.created_at.asc())
        .all()
    )

    # Load users in one query
    user_ids = {c.user_id for c in comments}
    users = {u.id: u for u in CommentUser.query.filter(CommentUser.id.in_(user_ids)).all()} if user_ids else {}

    # Build tree: top-level + replies
    top_level = []
    reply_map = {}  # parent_id -> list of serialized replies

    for c in comments:
        user = users.get(c.user_id)
        if not user:
            continue
        serialized = _serialize_comment(c, user)
        if c.parent_id:
            reply_map.setdefault(c.parent_id, []).append(serialized)
        else:
            top_level.append(serialized)

    # Attach replies and sort
    for item in top_level:
        item['replies'] = sorted(
            reply_map.get(item['id'], []),
            key=lambda r: r['created_at'] or '',
        )

    # Sort: pinned first, then by score descending
    top_level.sort(key=lambda c: (-int(c['is_pinned']), -c['score']))

    total = len(comments)
    return jsonify({'comments': top_level, 'count': total})


@bp.route('/<int:site_id>/<path:page_slug>/count', methods=['GET'])
@cross_origin()
def get_comment_count(site_id, page_slug):
    """Return comment count for a page (lightweight)."""
    count = Comment.query.filter_by(site_id=site_id, page_slug=page_slug).count()
    return jsonify({'count': count})


@bp.route('/<int:site_id>/<path:page_slug>', methods=['POST'])
@cross_origin()
def post_comment(site_id, page_slug):
    """Create a guest comment."""
    data = request.get_json(silent=True) or {}

    result, cleaned = _validate_comment_input(data)
    if result == 'honeypot':
        return jsonify({'success': True, 'comment_id': 0}), 201
    if result:
        return jsonify({'errors': result}), 422

    # Rate limit by real client IP
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip:
        ip = ip.split(',')[0].strip()
    if _is_rate_limited(ip):
        return jsonify({'errors': ['Too many comments. Please wait a few minutes.']}), 429

    site = db.session.get(Site, site_id)
    if not site or not getattr(site, 'comments_enabled', False):
        return jsonify({'errors': ['Comments are not enabled.']}), 404

    # Flatten replies-to-replies to single-level threading
    if cleaned['parent_id']:
        parent = Comment.query.filter_by(
            id=cleaned['parent_id'], site_id=site_id, page_slug=page_slug
        ).first()
        if not parent:
            return jsonify({'errors': ['Parent comment not found.']}), 404
        if parent.parent_id is not None:
            cleaned['parent_id'] = parent.parent_id

    # Find or create guest CommentUser by email hash
    email_hash = hashlib.md5(cleaned['email'].encode()).hexdigest()
    username = f'guest_{email_hash[:8]}'

    user = CommentUser.query.filter_by(site_id=site_id, username=username).first()
    if not user:
        user = CommentUser(
            site_id=site_id,
            username=username,
            display_name=cleaned['name'],
            avatar_style='thumbs',
            avatar_seed=email_hash,
            email=cleaned['email'],
            is_bot=False,
        )
        db.session.add(user)
        db.session.flush()
    else:
        if user.display_name != cleaned['name']:
            user.display_name = cleaned['name']

    comment = Comment(
        site_id=site_id,
        page_slug=page_slug,
        user_id=user.id,
        parent_id=cleaned['parent_id'],
        body=cleaned['body'],
    )
    db.session.add(comment)
    db.session.commit()

    _record_request(ip)
    return jsonify({'success': True, 'comment_id': comment.id}), 201


# --- Internal helpers (used by comment_seeder, not HTTP-exposed) ---

def seed_comment(site_id, page_slug, user_id, body, parent_id=None, created_at=None):
    """Create a Comment record. Returns the new comment."""
    comment = Comment(
        site_id=site_id,
        page_slug=page_slug,
        user_id=user_id,
        parent_id=parent_id,
        body=body,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.session.add(comment)
    db.session.flush()
    return comment


def seed_votes(comment, upvotes, downvotes, bot_users):
    """Seed vote records and update comment counters.

    Args:
        comment: Comment instance
        upvotes: number of upvotes to add
        downvotes: number of downvotes to add
        bot_users: list of CommentUser instances to pick voters from
    """
    import random
    voters = [u for u in bot_users if u.id != comment.user_id]
    random.shuffle(voters)

    vote_count = 0
    for i in range(min(upvotes, len(voters))):
        db.session.add(CommentVote(
            comment_id=comment.id,
            user_id=voters[i].id,
            value=1,
        ))
        vote_count += 1

    remaining = voters[upvotes:]
    for i in range(min(downvotes, len(remaining))):
        db.session.add(CommentVote(
            comment_id=comment.id,
            user_id=remaining[i].id,
            value=-1,
        ))

    comment.upvotes = upvotes
    comment.downvotes = downvotes
