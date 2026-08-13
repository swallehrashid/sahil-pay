import { Link, useParams } from "react-router-dom";
import { ArrowLeft, BookOpen } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { useGetHelpArticleQuery, useGetHelpCategoriesQuery } from "./helpApiSlice";

// Help & Tutorials, reader side. One component serves every portal — the
// server already filters categories and articles to the caller's role, so
// there is nothing portal-specific to branch on here.
//
// `basePath` is the portal prefix (e.g. "/landlord/help") so article links stay
// inside whichever portal the reader is in.

function ArticleView({ slug, basePath }) {
  const { data, isLoading, isError } = useGetHelpArticleQuery(slug);

  if (isLoading) return <SkeletonForm fields={6} />;
  if (isError || !data) {
    return (
      <EmptyState
        title="Article not found"
        description="It may have been moved or is not published yet."
      />
    );
  }

  const article = data.data ?? data;

  return (
    <div className="space-y-4">
      <Link
        to={basePath}
        className="inline-flex items-center gap-1 text-sm text-white/50 hover:text-white"
      >
        <ArrowLeft size={14} /> All guides
      </Link>

      <PageHeader title={article.title} subtitle={article.category_name} />

      {/* body_html is rendered server-side by the same sanitising pipeline the
          admin preview uses, with raw HTML escaped — so the two can never
          disagree, and an authored article can't inject into the portal. */}
      <article
        className="prose prose-invert glass max-w-none p-6"
        dangerouslySetInnerHTML={{ __html: article.body_html }}
      />

      <p className="text-xs text-white/30">
        {article.footer}
        {article.updated_at && ` Last updated: ${article.updated_at.slice(0, 10)}.`}
      </p>
    </div>
  );
}

export default function HelpPage({ basePath }) {
  const { slug } = useParams();
  const { data, isLoading } = useGetHelpCategoriesQuery(undefined, { skip: !!slug });

  if (slug) return <ArticleView slug={slug} basePath={basePath} />;
  if (isLoading) return <SkeletonForm fields={5} />;

  const categories = (data?.data ?? data)?.categories ?? [];

  return (
    <div className="space-y-6">
      <PageHeader title="Help & Tutorials" subtitle="Step-by-step guides for your account" />

      {!categories.length ? (
        <EmptyState
          title="No guides yet"
          description="Guides will appear here as they are published."
        />
      ) : (
        categories.map((category) => (
          <div key={category.id} className="glass space-y-3 p-6">
            <div className="flex items-start gap-3">
              <BookOpen size={18} className="mt-0.5 shrink-0 text-secondary" />
              <div>
                <h3 className="text-base font-medium text-white">{category.name}</h3>
                {category.description && (
                  <p className="mt-1 text-sm text-white/50">{category.description}</p>
                )}
              </div>
            </div>

            <ul className="space-y-1 pl-8">
              {category.articles.map((article) => (
                <li key={article.id}>
                  <Link
                    to={`${basePath}/${article.slug}`}
                    className="block rounded px-2 py-2 text-sm text-white/80 transition-colors hover:bg-white/5 hover:text-white"
                  >
                    {article.title}
                    {article.summary && (
                      <span className="block text-xs text-white/40">{article.summary}</span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}
