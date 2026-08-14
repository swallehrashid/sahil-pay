"""
Help & Tutorials — the admin-authored article library.

The CMS shipped with the eTIMS/KRA round but arrived without tests. It is worth
pinning because two of its rules are not obvious from the endpoints:

  * an article's audience is INHERITED from its category unless the article
    overrides it, so a "landlords only" shelf silently narrows everything on it;
  * a body is authored as markdown by an admin and rendered to HTML that every
    portal injects with dangerouslySetInnerHTML — if raw HTML survived that
    pipeline, the CMS would be a stored-XSS vector into every signed-in session.

The reader side is also the only consumer of the tenant- and team-facing
articles the seed ships, so its role filtering is what decides whether those
are readable at all.
"""

import uuid

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from models import (
    Landlord, LandlordSettings, SystemAdmin, TutorialArticle, TutorialCategory,
    User,
)
from services import tutorial_service as tutorials


def _uniq():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def client(app):
    return app.test_client()


def _token(app, user, role, **claims):
    with app.app_context():
        return create_access_token(identity=str(user.id),
                                   additional_claims={"role": role, **claims})


@pytest.fixture()
def readers(app, db_session):
    """One landlord and one tenant-role user, each with a usable token."""
    s = db_session
    n = _uniq()

    landlord_user = User(
        email=f"help-ll-{n}@test.sahilpay", phone=f"2547{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="landlord", is_verified=True, is_active=True,
    )
    tenant_user = User(
        email=f"help-tn-{n}@test.sahilpay", phone=f"2548{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="tenant", is_verified=True, is_active=True,
    )
    s.add_all([landlord_user, tenant_user])
    s.flush()

    landlord = Landlord(user_id=landlord_user.id, company_name=f"Help {n}", currency="KES")
    s.add(landlord)
    s.flush()
    s.add(LandlordSettings(landlord_id=landlord.id))
    s.flush()

    return {
        "landlord_user": landlord_user,
        "tenant_user": tenant_user,
        "landlord_token": _token(app, landlord_user, "landlord", landlord_id=landlord.id),
        "tenant_token": _token(app, tenant_user, "tenant"),
    }


@pytest.fixture()
def admin(app, db_session):
    s = db_session
    n = _uniq()
    user = User(
        email=f"help-admin-{n}@test.sahilpay", phone=f"2549{n[:7]}",
        password_hash=generate_password_hash("Testpass1"),
        role="system_admin", is_verified=True, is_active=True,
        totp_enabled=True,          # admin routes are shut until 2FA is on
    )
    s.add(user)
    s.flush()
    s.add(SystemAdmin(user_id=user.id))
    s.flush()
    return {"user": user, "token": _token(app, user, "system_admin")}


def _category(s, **kw):
    defaults = dict(name=f"Cat {_uniq()}", slug=f"cat-{_uniq()}",
                    sort_order=0, is_published=True)
    defaults.update(kw)
    category = TutorialCategory(**defaults)
    s.add(category)
    s.flush()
    return category


def _article(s, category, **kw):
    defaults = dict(category_id=category.id, title=f"Art {_uniq()}",
                    slug=f"art-{_uniq()}", body_markdown="Hello.",
                    sort_order=0, is_published=True)
    defaults.update(kw)
    article = TutorialArticle(**defaults)
    s.add(article)
    s.flush()
    return article


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Rendering — the sanitisation boundary
# ---------------------------------------------------------------------------

def test_raw_html_in_a_body_is_escaped_not_executed(app):
    """
    Article HTML is injected with dangerouslySetInnerHTML in every portal, so a
    <script> surviving the renderer would run with the reader's session. An
    admin is trusted, but a compromised admin account must not become script
    execution in every landlord's and tenant's browser.
    """
    with app.app_context():
        html = tutorials.render_markdown(
            "Careful <script>alert('xss')</script> and "
            "<img src=x onerror=alert(1)> here."
        )

    # No live tag survives: everything is escaped into text, so the browser
    # renders it rather than executing it. (The literal string "onerror=" is
    # still present — as visible text inside "&lt;img …&gt;", which is exactly
    # the intended outcome, so assert on the tag delimiters instead.)
    assert "<script>" not in html
    assert "<img" not in html
    # Escaped, so the reader still sees what was typed.
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_markdown_still_renders_normally(app):
    with app.app_context():
        html = tutorials.render_markdown("# Title\n\nSome **bold** text.")
    assert "<h1>" in html
    assert "<strong>" in html


def test_empty_body_renders_empty(app):
    with app.app_context():
        assert tutorials.render_markdown(None) == ""
        assert tutorials.render_markdown("") == ""


# ---------------------------------------------------------------------------
# Audience resolution
# ---------------------------------------------------------------------------

def test_article_inherits_its_category_audience(db_session):
    """An article with no audience of its own takes the shelf's."""
    s = db_session
    category = _category(s, visible_to_roles=["landlord"])
    article = _article(s, category, visible_to_roles=None)

    assert tutorials.audience_of(article) == ["landlord"]
    assert tutorials.visible_to("landlord", ["landlord"]) is True
    assert tutorials.visible_to("tenant", ["landlord"]) is False


def test_article_audience_overrides_its_category(db_session):
    s = db_session
    category = _category(s, visible_to_roles=["landlord"])
    article = _article(s, category, visible_to_roles=["tenant"])

    assert tutorials.audience_of(article) == ["tenant"]


def test_no_audience_anywhere_means_everyone(db_session):
    s = db_session
    category = _category(s, visible_to_roles=None)
    article = _article(s, category, visible_to_roles=None)

    assert tutorials.audience_of(article) is None
    assert tutorials.visible_to("tenant", None) is True
    assert tutorials.visible_to("landlord", None) is True


def test_unknown_role_in_an_audience_is_rejected(app):
    from utils import ApiError

    with app.app_context():
        with pytest.raises(ApiError):
            tutorials.normalise_roles(["landlord", "not_a_role"])
        # Empty list normalises to None so "nobody" can't be expressed by
        # accident — that would silently hide an article from everyone.
        assert tutorials.normalise_roles([]) is None


# ---------------------------------------------------------------------------
# Reader side — /api/tutorials
# ---------------------------------------------------------------------------

def test_reader_only_sees_articles_for_their_role(client, db_session, readers):
    s = db_session
    category = _category(s, visible_to_roles=None)
    _article(s, category, title="For landlords", slug=f"ll-{_uniq()}",
             visible_to_roles=["landlord"])
    tenant_slug = f"tn-{_uniq()}"
    _article(s, category, title="For tenants", slug=tenant_slug,
             visible_to_roles=["tenant"])

    res = client.get("/api/tutorials", headers=_auth(readers["tenant_token"]))
    assert res.status_code == 200
    titles = [a["title"]
              for c in res.get_json()["data"]["categories"]
              for a in c["articles"]]
    assert "For tenants" in titles
    assert "For landlords" not in titles


def test_tenant_can_open_a_tenant_article(client, db_session, readers):
    """
    The seeded library ships tenant-facing material, so this is the path that
    decides whether a tenant can read anything at all.
    """
    s = db_session
    category = _category(s)
    slug = f"tenant-guide-{_uniq()}"
    _article(s, category, slug=slug, visible_to_roles=["tenant"],
             body_markdown="Your **receipt** explained.")

    res = client.get(f"/api/tutorials/{slug}", headers=_auth(readers["tenant_token"]))
    assert res.status_code == 200
    body = res.get_json()["data"]
    assert "<strong>receipt</strong>" in body["body_html"]
    assert body["footer"] == tutorials.ARTICLE_FOOTER


def test_wrong_audience_gets_404_not_403(client, db_session, readers):
    """
    A 403 would confirm the article exists. Whether the library holds a page a
    reader isn't entitled to is not something they get to learn.
    """
    s = db_session
    category = _category(s)
    slug = f"ll-only-{_uniq()}"
    _article(s, category, slug=slug, visible_to_roles=["landlord"])

    res = client.get(f"/api/tutorials/{slug}", headers=_auth(readers["tenant_token"]))
    assert res.status_code == 404


def test_unpublished_article_is_not_served(client, db_session, readers):
    s = db_session
    category = _category(s)
    slug = f"draft-{_uniq()}"
    _article(s, category, slug=slug, is_published=False)

    res = client.get(f"/api/tutorials/{slug}", headers=_auth(readers["landlord_token"]))
    assert res.status_code == 404


def test_article_under_an_unpublished_category_is_not_served(client, db_session, readers):
    """A published page on an unpublished shelf must not leak through."""
    s = db_session
    category = _category(s, is_published=False)
    slug = f"orphan-{_uniq()}"
    _article(s, category, slug=slug, is_published=True)

    res = client.get(f"/api/tutorials/{slug}", headers=_auth(readers["landlord_token"]))
    assert res.status_code == 404


def test_a_category_with_nothing_for_this_reader_is_hidden(client, db_session, readers):
    s = db_session
    category = _category(s, name=f"Landlord shelf {_uniq()}")
    _article(s, category, visible_to_roles=["landlord"])

    res = client.get("/api/tutorials", headers=_auth(readers["tenant_token"]))
    names = [c["name"] for c in res.get_json()["data"]["categories"]]
    assert category.name not in names


def test_reader_endpoints_require_a_token(client):
    assert client.get("/api/tutorials").status_code == 401
    assert client.get("/api/tutorials/anything").status_code == 401


# ---------------------------------------------------------------------------
# Slugs
# ---------------------------------------------------------------------------

def test_slugify_handles_punctuation_and_dashes(app):
    with app.app_context():
        assert tutorials.slugify("How rental taxes work in Kenya — the basics") == \
            "how-rental-taxes-work-in-kenya-the-basics"
        assert tutorials.slugify("   ") == "item"


def test_unique_slug_suffixes_on_collision(db_session):
    # No nested app_context here: db_session is already scoped to one, and
    # opening another would hand these queries a fresh session that cannot see
    # the row flushed above.
    s = db_session
    base = f"guide-{_uniq()}"
    category = _category(s, slug=base)

    assert tutorials.unique_slug(TutorialCategory, base) == f"{base}-2"
    # Excluding the row that owns it lets a rename keep its own slug.
    assert tutorials.unique_slug(TutorialCategory, base,
                                 exclude_id=category.id) == base


# ---------------------------------------------------------------------------
# Admin CMS guards
# ---------------------------------------------------------------------------

def test_cms_is_closed_to_non_admins(client, readers):
    res = client.get("/api/admin/tutorial-categories",
                     headers=_auth(readers["landlord_token"]))
    assert res.status_code in (401, 403)


def test_admin_can_create_and_publish_an_article(client, db_session, admin):
    created = client.post(
        "/api/admin/tutorial-categories",
        headers=_auth(admin["token"]),
        json={"name": f"Shelf {_uniq()}", "is_published": True},
    )
    assert created.status_code in (200, 201), created.get_data(as_text=True)
    category_id = created.get_json()["data"]["id"]

    article = client.post(
        "/api/admin/tutorial-articles",
        headers=_auth(admin["token"]),
        json={
            "category_id": category_id,
            "title": f"Filing your MRI {_uniq()}",
            "body_markdown": "File by the **20th**.",
            "is_published": True,
        },
    )
    assert article.status_code in (200, 201), article.get_data(as_text=True)
    data = article.get_json()["data"]
    assert data["slug"].startswith("filing-your-mri")


# ---------------------------------------------------------------------------
# Per-user preferences (/api/preferences) — also untested until now
# ---------------------------------------------------------------------------

def test_preferences_round_trip_per_user(client, db_session, readers):
    """A preference saved by one user must not surface for another."""
    saved = client.patch(
        "/api/preferences",
        headers=_auth(readers["landlord_token"]),
        json={"gross_basis": "rent_only"},
    )
    assert saved.status_code == 200, saved.get_data(as_text=True)

    mine = client.get("/api/preferences", headers=_auth(readers["landlord_token"]))
    assert mine.status_code == 200
    assert mine.get_json()["data"].get("gross_basis") == "rent_only"

    theirs = client.get("/api/preferences", headers=_auth(readers["tenant_token"]))
    assert theirs.status_code == 200
    assert theirs.get_json()["data"].get("gross_basis") is None


def test_preferences_require_a_token(client):
    assert client.get("/api/preferences").status_code == 401
