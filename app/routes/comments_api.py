"""Public comments API — served to static sites via CORS."""

from datetime import datetime, timezone

from flask import Blueprint, jsonify
from flask_cors import cross_origin

from ..models import db, Comment, CommentUser, CommentVote

bp = Blueprint('comments_api', __name__, url_prefix='/comments-api')


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
