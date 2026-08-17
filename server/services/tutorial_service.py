"""
services/tutorial_service.py — the admin-authored Help Content library.

Not to be confused with client/src/features/landlord/tutorials/, which is the
hardcoded first-run product TOUR. This is the CMS: markdown articles the system
admin writes and publishes, filtered by role, rendered read-only everywhere else.

Two rules drive the whole module:

  1. UNPUBLISHED IS INVISIBLE. Draft content must never leak to a non-admin,
     and that is enforced in the query, not the template — a role filter applied
     after fetching is a filter someone will forget.

  2. MARKDOWN IS UNTRUSTED. Bodies are authored by a human and rendered into
     every portal, so raw HTML is escaped rather than passed through. mistune's
     default `escape=True` does exactly that, which is why rendering happens
     here on the server and the client only ever receives finished, safe HTML.
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import mistune

from extensions import db
from utils import ApiError

# Every audience label an article can be addressed to. Affiliates have their own
# portal and no help library, so they are deliberately absent.
#
# The last four are team-member PRESETS, not user roles — a caretaker and an
# accountant both sign in as `team_member`. They are audience labels because
# "how to record a meter reading" is written for caretakers and is noise for an
# accountant. effective_roles() is what maps a signed-in team member onto their
# preset label; without it these would address nobody.
VALID_ROLES = (
    "tenant", "landlord", "property_manager", "team_member",
    "caretaker", "accountant", "secretary", "owner",
)

# Tutorial pages are read on Kenyan mobile data, so an uploaded screenshot is
# downscaled and recompressed rather than served at whatever size it arrived.
MAX_IMAGE_WIDTH = 1200
TARGET_IMAGE_BYTES = 250 * 1024

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Rendered under every article, from the CMS rather than stored per article, so
# it can never be edited away or forgotten on a new page.
ARTICLE_FOOTER = (
    "Educational guidance only — not tax advice. Confirm specifics with KRA or "
    "a tax professional."
)

_renderer = mistune.create_markdown(
    escape=True,                       # raw HTML in a body is shown, never executed
    plugins=["table", "strikethrough", "url"],
)


def render_markdown(body: str | None) -> str:
    """Markdown → sanitised HTML. The only place a body becomes HTML."""
    if not body:
        return ""
    return _renderer(body)


def slugify(text: str, fallback: str = "item") -> str:
    slug = _SLUG_STRIP.sub("-", (text or "").strip().lower()).strip("-")
    return slug or fallback


def unique_slug(model, desired: str, exclude_id: int | None = None) -> str:
    """A slug free on *model*, suffixed -2, -3… on collision."""
    base = slugify(desired)
    candidate, counter = base, 1
    while True:
        query = db.session.query(model.id).filter(model.slug == candidate)
        if exclude_id is not None:
            query = query.filter(model.id != exclude_id)
        if query.first() is None:
            return candidate
        counter += 1
        candidate = f"{base}-{counter}"


def normalise_roles(value) -> list[str] | None:
    """
    A role audience. None means "inherit" (article) or "everyone" (category);
    an empty list is normalised to None so the two can't drift apart.
    """
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ApiError("visible_to_roles must be a list of roles.", status=422)
    roles = [str(r).strip() for r in value if str(r).strip()]
    unknown = [r for r in roles if r not in VALID_ROLES]
    if unknown:
        raise ApiError(f"Unknown role(s): {', '.join(unknown)}.", status=422,
                       errors={"visible_to_roles": unknown})
    return roles or None


def audience_of(article) -> list[str] | None:
    """The effective audience: the article's own, else its category's."""
    if article.visible_to_roles:
        return list(article.visible_to_roles)
    category = article.category
    if category is not None and category.visible_to_roles:
        return list(category.visible_to_roles)
    return None


def reachability(article) -> dict:
    """
    Whether *article* actually reaches a reader, and why not when it doesn't.

    Publishing an article inside a category that is still a draft hides it
    completely — `published_categories()` never returns the shelf, so the
    article on it cannot be found either. From the CMS that looks identical to
    a successful publish, which is precisely how content gets written, marked
    published, and then reaches nobody. The admin list renders this so the gap
    is visible at the point the mistake is made rather than discovered later.
    """
    if not article.is_published:
        return {"is_reachable": False, "blocked_reason": "article_draft",
                "blocked_hint": "This article is a draft. Publish it to make it visible."}

    category = article.category
    if category is None or not category.is_published:
        name = category.name if category is not None else "its category"
        return {"is_reachable": False, "blocked_reason": "category_draft",
                "blocked_hint": (f"Published, but nobody can see it: the category "
                                 f"“{name}” is still a draft. Publish the category too.")}

    return {"is_reachable": True, "blocked_reason": None, "blocked_hint": None}


def effective_roles(role: str | None, preset: str | None = None) -> frozenset[str]:
    """
    Every audience label *role* matches — which is not always just itself.

    Two mismatches used to make published content unreachable:

      1. "caretaker" is an audience the admin CMS offers, but it is NOT a user
         role: a caretaker signs in as `team_member` carrying preset
         "caretaker". Matching on the JWT role alone meant an article aimed at
         caretakers was visible to literally nobody. A team member therefore
         matches their preset's label as well as "team_member".

      2. A system_admin matched no audience at all, so the person who WRITES
         the content could not see their own published article anywhere except
         the untargeted ones — the reported "I published it and it appeared to
         no one". An admin matches every audience, so the reader view doubles
         as a preview of what everyone else gets.
    """
    if role == "system_admin":
        return frozenset(VALID_ROLES)
    if not role:
        return frozenset()
    labels = {role}
    if role == "team_member" and preset:
        labels.add(preset)
    return frozenset(labels)


def visible_to(role, roles: list[str] | None) -> bool:
    """
    Does this reader match *roles*? None / empty audience means everyone.

    *role* is either a single role string or an already-resolved set of labels
    from effective_roles() — callers that only have a bare role (tests, admin
    tooling) keep working unchanged.
    """
    if not roles:
        return True
    reader = role if isinstance(role, (set, frozenset)) else effective_roles(role)
    return bool(reader & set(roles))


# ---------------------------------------------------------------------------
# Reads for the user side — published only, role-filtered in the query
# ---------------------------------------------------------------------------

def published_categories(role) -> list[dict]:
    from models import TutorialArticle, TutorialCategory

    categories = (
        db.session.query(TutorialCategory)
        .filter(TutorialCategory.is_published.is_(True))
        .order_by(TutorialCategory.sort_order.asc(), TutorialCategory.name.asc())
        .all()
    )

    out = []
    for category in categories:
        if not visible_to(role, category.visible_to_roles):
            continue
        articles = [
            a for a in category.articles
            if a.is_published and visible_to(role, audience_of(a))
        ]
        if not articles:
            # A shelf with nothing on it for this reader is not shown at all,
            # rather than shown empty.
            continue
        data = category.to_dict(article_count=len(articles))
        data["articles"] = [{
            "id": a.id, "title": a.title, "slug": a.slug, "summary": a.summary,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        } for a in articles]
        out.append(data)
    return out


def published_article(slug: str, role) -> dict:
    from models import TutorialArticle

    article = (
        db.session.query(TutorialArticle)
        .filter(TutorialArticle.slug == slug,
                TutorialArticle.is_published.is_(True))
        .first()
    )
    if article is None or not visible_to(role, audience_of(article)):
        # Same 404 either way: whether an unpublished article exists is not
        # something a reader gets to learn.
        raise ApiError("Article not found.", status=404)
    if article.category is None or not article.category.is_published:
        raise ApiError("Article not found.", status=404)

    data = article.to_dict()
    data["body_html"] = render_markdown(article.body_markdown)
    data["footer"] = ARTICLE_FOOTER
    return data


# ---------------------------------------------------------------------------
# Image handling
# ---------------------------------------------------------------------------

def uploads_dir() -> Path:
    """
    Where tutorial images live on disk: server/uploads/tutorials/, the same
    local-disk fallback the branding (logo/signature) uploads use, served by
    app.py's /uploads/<path> route. In production that path is
    /var/www/sahilpay/app/uploads/tutorials/ and belongs to the `sahilpay` user.
    """
    from flask import current_app

    path = Path(current_app.root_path) / "uploads" / "tutorials"
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_url(filename: str) -> str:
    """The URL an article's markdown embeds. Stable across a Replace."""
    return f"/uploads/tutorials/{filename}"


def process_image(file_storage, destination: Path) -> None:
    """
    Downscale to MAX_IMAGE_WIDTH and recompress toward TARGET_IMAGE_BYTES.

    Writes to *destination* — which on a Replace is the EXISTING path, so every
    article already embedding that URL updates without being edited.
    """
    from PIL import Image

    try:
        image = Image.open(file_storage.stream)
    except Exception:
        raise ApiError("That file isn't a readable image.", status=422,
                       errors={"file": "invalid_image"})

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if image.width > MAX_IMAGE_WIDTH:
        height = round(image.height * MAX_IMAGE_WIDTH / image.width)
        image = image.resize((MAX_IMAGE_WIDTH, height), Image.LANCZOS)

    # Step the quality down until it fits, then keep the best that did.
    for quality in (85, 75, 65, 55, 45):
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        if buffer.tell() <= TARGET_IMAGE_BYTES or quality == 45:
            destination.write_bytes(buffer.getvalue())
            return
