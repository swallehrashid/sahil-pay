"""
routes/admin_tutorial_routes.py — Help Content CMS (System Admin only)
Blueprint: admin_tutorial_bp  |  Prefix: /api/admin

Where Swalleh writes and publishes the help library: categories, markdown
articles with a live preview, and the screenshots inside them.

Every route is behind require_system_admin(), which also demands an active
second factor — help content renders inside every portal, so write access to it
is effectively write access to what a thousand tenants read.
"""

import uuid
from pathlib import Path

from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from extensions import db
from decorators import require_system_admin
from models import TutorialArticle, TutorialCategory, TutorialImage
from services import tutorial_service as tutorials
from services.audit_service import record_audit
from utils import ApiError, get_jwt_user, success

admin_tutorial_bp = Blueprint("admin_tutorials", __name__, url_prefix="/api/admin")


def _admin():
    require_system_admin()
    return get_jwt_user()


# ===========================================================================
# Categories
# ===========================================================================

@admin_tutorial_bp.route("/tutorial-categories", methods=["GET"])
@jwt_required()
def list_categories():
    _admin()
    categories = (
        TutorialCategory.query
        .order_by(TutorialCategory.sort_order.asc(), TutorialCategory.name.asc())
        .all()
    )
    return success([
        {**c.to_dict(article_count=len(c.articles)),
         "published_article_count": sum(1 for a in c.articles if a.is_published)}
        for c in categories
    ])


@admin_tutorial_bp.route("/tutorial-categories", methods=["POST"])
@jwt_required()
def create_category():
    admin = _admin()
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError("A category name is required.", status=422,
                       errors={"name": "required"})

    category = TutorialCategory(
        name             = name,
        slug             = tutorials.unique_slug(TutorialCategory,
                                                 data.get("slug") or name),
        icon             = (data.get("icon") or "").strip() or None,
        description      = data.get("description"),
        sort_order       = int(data.get("sort_order") or 0),
        visible_to_roles = tutorials.normalise_roles(data.get("visible_to_roles")),
        is_published     = bool(data.get("is_published")),
    )
    db.session.add(category)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_category_create", entity_type="tutorial",
                 entity_id=category.id, description=f"Created help category '{name}'.")
    return success(category.to_dict(), message="Category created.", status=201)


@admin_tutorial_bp.route("/tutorial-categories/<int:category_id>", methods=["PATCH"])
@jwt_required()
def update_category(category_id: int):
    admin = _admin()
    category = db.session.get(TutorialCategory, category_id)
    if category is None:
        raise ApiError("Category not found.", status=404)

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ApiError("A category name is required.", status=422,
                           errors={"name": "required"})
        category.name = name
    if "slug" in data and data["slug"]:
        category.slug = tutorials.unique_slug(TutorialCategory, data["slug"],
                                              exclude_id=category.id)
    if "icon" in data:
        category.icon = (data["icon"] or "").strip() or None
    if "description" in data:
        category.description = data["description"]
    if "sort_order" in data:
        category.sort_order = int(data["sort_order"] or 0)
    if "visible_to_roles" in data:
        category.visible_to_roles = tutorials.normalise_roles(data["visible_to_roles"])
    if "is_published" in data:
        category.is_published = bool(data["is_published"])

    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_category_update", entity_type="tutorial",
                 entity_id=category.id, description=f"Updated help category '{category.name}'.")
    return success(category.to_dict(), message="Saved.")


@admin_tutorial_bp.route("/tutorial-categories/reorder", methods=["POST"])
@jwt_required()
def reorder_categories():
    """Persist a drag-reorder: {"order": [id, id, ...]}."""
    admin = _admin()
    order = (request.get_json(silent=True) or {}).get("order") or []
    for position, category_id in enumerate(order):
        category = db.session.get(TutorialCategory, category_id)
        if category is not None:
            category.sort_order = position
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_category_reorder", entity_type="tutorial",
                 entity_id=None, description="Reordered help categories.")
    return success(message="Order saved.")


@admin_tutorial_bp.route("/tutorial-categories/<int:category_id>", methods=["DELETE"])
@jwt_required()
def delete_category(category_id: int):
    """
    Delete a category. Refused while it still holds PUBLISHED articles —
    deleting one would silently 404 links that are already out in the world, so
    the admin has to unpublish deliberately first.
    """
    admin = _admin()
    category = db.session.get(TutorialCategory, category_id)
    if category is None:
        raise ApiError("Category not found.", status=404)

    published = [a for a in category.articles if a.is_published]
    if published:
        raise ApiError(
            f"Unpublish this category's {len(published)} published "
            f"{'article' if len(published) == 1 else 'articles'} before deleting it.",
            status=409, code="has_published_articles",
        )

    name = category.name
    db.session.delete(category)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_category_delete", entity_type="tutorial",
                 entity_id=category_id, description=f"Deleted help category '{name}'.")
    return success(message="Category deleted.")


# ===========================================================================
# Articles
# ===========================================================================

@admin_tutorial_bp.route("/tutorial-articles", methods=["GET"])
@jwt_required()
def list_articles():
    _admin()
    query = TutorialArticle.query
    category_id = request.args.get("category_id")
    if category_id and category_id.isdigit():
        query = query.filter(TutorialArticle.category_id == int(category_id))
    articles = query.order_by(TutorialArticle.category_id.asc(),
                              TutorialArticle.sort_order.asc()).all()
    return success([
        {**a.to_dict(include_body=False), **tutorials.reachability(a)}
        for a in articles
    ])


@admin_tutorial_bp.route("/tutorial-articles/<int:article_id>", methods=["GET"])
@jwt_required()
def get_article(article_id: int):
    """The editor's payload: body, its rendered preview, and the image list."""
    _admin()
    article = db.session.get(TutorialArticle, article_id)
    if article is None:
        raise ApiError("Article not found.", status=404)

    data = article.to_dict()
    data.update(tutorials.reachability(article))
    # Rendered by the SAME function the reader side uses, so the preview cannot
    # drift from what a landlord actually sees.
    data["body_html"] = tutorials.render_markdown(article.body_markdown)
    data["footer"] = tutorials.ARTICLE_FOOTER
    data["images"] = [i.to_dict() for i in article.images]
    data["updated_by"] = (article.updated_by.email
                          if article.updated_by else None)
    return success(data)


@admin_tutorial_bp.route("/tutorial-articles", methods=["POST"])
@jwt_required()
def create_article():
    admin = _admin()
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    if not title:
        raise ApiError("A title is required.", status=422, errors={"title": "required"})

    category_id = data.get("category_id")
    if db.session.get(TutorialCategory, category_id) is None:
        raise ApiError("Choose a category.", status=422,
                       errors={"category_id": "required"})

    article = TutorialArticle(
        category_id        = category_id,
        title              = title,
        slug               = tutorials.unique_slug(TutorialArticle,
                                                   data.get("slug") or title),
        summary            = (data.get("summary") or "").strip() or None,
        body_markdown      = data.get("body_markdown") or "",
        sort_order         = int(data.get("sort_order") or 0),
        visible_to_roles   = tutorials.normalise_roles(data.get("visible_to_roles")),
        is_published       = bool(data.get("is_published")),
        updated_by_user_id = admin.id,
    )
    db.session.add(article)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_article_create", entity_type="tutorial",
                 entity_id=article.id, description=f"Created help article '{title}'.")
    return success(article.to_dict(), message="Article created.", status=201)


@admin_tutorial_bp.route("/tutorial-articles/<int:article_id>", methods=["PATCH"])
@jwt_required()
def update_article(article_id: int):
    admin = _admin()
    article = db.session.get(TutorialArticle, article_id)
    if article is None:
        raise ApiError("Article not found.", status=404)

    data = request.get_json(silent=True) or {}
    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            raise ApiError("A title is required.", status=422,
                           errors={"title": "required"})
        article.title = title
    if "slug" in data and data["slug"]:
        # Slugs are the stable link target used by dashboard nudges and
        # settings links, so changing one is deliberate, never automatic on a
        # title edit.
        article.slug = tutorials.unique_slug(TutorialArticle, data["slug"],
                                             exclude_id=article.id)
    if "category_id" in data:
        if db.session.get(TutorialCategory, data["category_id"]) is None:
            raise ApiError("Category not found.", status=422,
                           errors={"category_id": "invalid"})
        article.category_id = data["category_id"]
    if "summary" in data:
        article.summary = (data["summary"] or "").strip() or None
    if "body_markdown" in data:
        article.body_markdown = data["body_markdown"] or ""
    if "sort_order" in data:
        article.sort_order = int(data["sort_order"] or 0)
    if "visible_to_roles" in data:
        article.visible_to_roles = tutorials.normalise_roles(data["visible_to_roles"])
    if "is_published" in data:
        article.is_published = bool(data["is_published"])
    article.updated_by_user_id = admin.id

    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_article_update", entity_type="tutorial",
                 entity_id=article.id, description=f"Updated help article '{article.title}'.")

    payload = article.to_dict()
    payload["body_html"] = tutorials.render_markdown(article.body_markdown)
    return success(payload, message="Saved.")


@admin_tutorial_bp.route("/tutorial-articles/<int:article_id>", methods=["DELETE"])
@jwt_required()
def delete_article(article_id: int):
    admin = _admin()
    article = db.session.get(TutorialArticle, article_id)
    if article is None:
        raise ApiError("Article not found.", status=404)
    title = article.title
    db.session.delete(article)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_article_delete", entity_type="tutorial",
                 entity_id=article_id, description=f"Deleted help article '{title}'.")
    return success(message="Article deleted.")


@admin_tutorial_bp.route("/tutorial-articles/preview", methods=["POST"])
@jwt_required()
def preview_article():
    """Live side-by-side preview while typing — same renderer as the reader side."""
    _admin()
    body = (request.get_json(silent=True) or {}).get("body_markdown") or ""
    return success({"body_html": tutorials.render_markdown(body),
                    "footer": tutorials.ARTICLE_FOOTER})


# ===========================================================================
# Images
# ===========================================================================

@admin_tutorial_bp.route("/tutorial-images", methods=["GET"])
@jwt_required()
def list_images():
    """An article's images, or the shared library when article_id is absent."""
    _admin()
    article_id = request.args.get("article_id")
    query = TutorialImage.query
    if article_id and article_id.isdigit():
        query = query.filter(TutorialImage.article_id == int(article_id))
    elif article_id == "null":
        query = query.filter(TutorialImage.article_id.is_(None))
    images = query.order_by(TutorialImage.sort_order.asc(),
                            TutorialImage.id.asc()).all()
    return success([i.to_dict() for i in images])


@admin_tutorial_bp.route("/tutorial-images", methods=["POST"])
@jwt_required()
def upload_image():
    """
    Multipart upload. Returns the stored row including a ready-to-paste
    markdown snippet, which the editor inserts at the cursor.
    """
    admin = _admin()
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("Choose an image to upload.", status=422,
                       errors={"file": "required"})

    article_id = request.form.get("article_id")
    article_id = int(article_id) if article_id and article_id.isdigit() else None
    if article_id is not None and db.session.get(TutorialArticle, article_id) is None:
        raise ApiError("Article not found.", status=404)

    filename = f"{uuid.uuid4().hex}.jpg"
    tutorials.process_image(upload, tutorials.uploads_dir() / filename)

    image = TutorialImage(
        article_id          = article_id,
        file_path           = tutorials.public_url(filename),
        caption             = (request.form.get("caption") or "").strip() or None,
        alt_text            = (request.form.get("alt_text") or "").strip() or None,
        sort_order          = int(request.form.get("sort_order") or 0),
        uploaded_by_user_id = admin.id,
    )
    db.session.add(image)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_image_upload", entity_type="tutorial",
                 entity_id=image.id, description="Uploaded a help image.")
    return success(image.to_dict(), message="Image uploaded.", status=201)


@admin_tutorial_bp.route("/tutorial-images/<int:image_id>/replace", methods=["POST"])
@jwt_required()
def replace_image(image_id: int):
    """
    Swap the file behind an existing image, KEEPING the same URL — so every
    article already embedding it updates instantly, with no edit and no
    re-publish.
    """
    admin = _admin()
    image = db.session.get(TutorialImage, image_id)
    if image is None:
        raise ApiError("Image not found.", status=404)

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("Choose a replacement image.", status=422,
                       errors={"file": "required"})

    filename = Path(image.file_path).name
    tutorials.process_image(upload, tutorials.uploads_dir() / filename)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_image_replace", entity_type="tutorial",
                 entity_id=image.id, description="Replaced a help image in place.")
    return success(image.to_dict(), message="Image replaced.")


@admin_tutorial_bp.route("/tutorial-images/<int:image_id>", methods=["PATCH"])
@jwt_required()
def update_image(image_id: int):
    _admin()
    image = db.session.get(TutorialImage, image_id)
    if image is None:
        raise ApiError("Image not found.", status=404)

    data = request.get_json(silent=True) or {}
    if "caption" in data:
        image.caption = (data["caption"] or "").strip() or None
    if "alt_text" in data:
        image.alt_text = (data["alt_text"] or "").strip() or None
    if "sort_order" in data:
        image.sort_order = int(data["sort_order"] or 0)
    if "article_id" in data:
        article_id = data["article_id"]
        image.article_id = int(article_id) if article_id else None
    db.session.commit()
    return success(image.to_dict(), message="Saved.")


@admin_tutorial_bp.route("/tutorial-images/<int:image_id>", methods=["DELETE"])
@jwt_required()
def delete_image(image_id: int):
    admin = _admin()
    image = db.session.get(TutorialImage, image_id)
    if image is None:
        raise ApiError("Image not found.", status=404)

    # The file itself is left on disk on purpose: an article body may still
    # reference the URL, and a broken image in published help is worse than an
    # orphaned 40KB file.
    db.session.delete(image)
    db.session.commit()
    record_audit(actor_user_id=admin.id, landlord_id=None,
                 action="tutorial_image_delete", entity_type="tutorial",
                 entity_id=image_id, description="Deleted a help image record.")
    return success(message="Image deleted.")
