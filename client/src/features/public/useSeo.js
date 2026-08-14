import { useEffect } from "react";

/**
 * Per-page SEO tags for the public marketing pages.
 *
 * The app is a single-page React build, so every route shares one index.html
 * and — until this hook runs — one title and one meta description. That is the
 * single biggest thing holding back search visibility: Google indexes /pricing
 * and /faq under the same generic title, and neither can rank for what it is
 * actually about.
 *
 * Deliberately dependency-free (no react-helmet): the whole job is setting a
 * handful of DOM nodes, and Google's crawler executes JavaScript before
 * indexing, so a hook is enough. It also means the prerender step (which walks
 * the built site with a headless browser and saves the resulting HTML) captures
 * these tags without any extra wiring.
 *
 * Usage:
 *   useSeo({
 *     title: "Pricing — Sahil Pay",
 *     description: "...",
 *     path: "/pricing",
 *     jsonLd: { ... },
 *   });
 */

const SITE_URL = "https://sahilpay.co.ke";
const SITE_NAME = "Sahil Pay";
const DEFAULT_IMAGE = `${SITE_URL}/favicon.svg`;

/** Create-or-update a <meta> tag, keyed by name or property. */
function setMeta(attr, key, content) {
  if (!content) return;
  let tag = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (!tag) {
    tag = document.createElement("meta");
    tag.setAttribute(attr, key);
    document.head.appendChild(tag);
  }
  tag.setAttribute("content", content);
}

function setCanonical(url) {
  let link = document.head.querySelector('link[rel="canonical"]');
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("rel", "canonical");
    document.head.appendChild(link);
  }
  link.setAttribute("href", url);
}

/**
 * Structured data. Each block is tagged with a data-seo id so a route change
 * removes only the blocks it added — otherwise navigating between pages would
 * stack a FAQPage schema onto the pricing page and confuse the crawler.
 */
function setJsonLd(id, data) {
  const selector = `script[type="application/ld+json"][data-seo="${id}"]`;
  document.head.querySelectorAll(selector).forEach((n) => n.remove());
  if (!data) return;
  const script = document.createElement("script");
  script.type = "application/ld+json";
  script.setAttribute("data-seo", id);
  script.textContent = JSON.stringify(data);
  document.head.appendChild(script);
}

export function useSeo({ title, description, path = "/", image, jsonLd, jsonLdId = "page" }) {
  useEffect(() => {
    const url = `${SITE_URL}${path === "/" ? "" : path}`;
    const img = image || DEFAULT_IMAGE;

    if (title) document.title = title;
    setMeta("name", "description", description);
    setCanonical(url);

    // Open Graph — what WhatsApp, Facebook and LinkedIn show when the link is
    // shared, which in this market is how most of the traffic actually arrives.
    setMeta("property", "og:title", title);
    setMeta("property", "og:description", description);
    setMeta("property", "og:url", url);
    setMeta("property", "og:type", "website");
    setMeta("property", "og:site_name", SITE_NAME);
    setMeta("property", "og:image", img);
    setMeta("property", "og:locale", "en_KE");

    setMeta("name", "twitter:card", "summary_large_image");
    setMeta("name", "twitter:title", title);
    setMeta("name", "twitter:description", description);
    setMeta("name", "twitter:image", img);

    setJsonLd(jsonLdId, jsonLd);

    return () => setJsonLd(jsonLdId, null);
  }, [title, description, path, image, jsonLd, jsonLdId]);
}

/** The sitewide publisher identity — rendered once, from the layout. */
export const ORGANIZATION_JSON_LD = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: SITE_NAME,
  url: SITE_URL,
  logo: DEFAULT_IMAGE,
  description:
    "Smart rent collection and property management software for Kenyan landlords and property managers.",
  areaServed: { "@type": "Country", name: "Kenya" },
  contactPoint: {
    "@type": "ContactPoint",
    contactType: "customer support",
    email: "sahilpayke@gmail.com",
    areaServed: "KE",
    availableLanguage: ["en", "sw"],
  },
};

/** The product schema — drives rich results on the pricing page. */
export function softwareApplicationJsonLd(packages = []) {
  const offers = packages
    .filter((p) => p.price_per_unit || p.flat_price)
    .map((p) => ({
      "@type": "Offer",
      name: p.name,
      price: String(p.flat_price ?? p.price_per_unit ?? ""),
      priceCurrency: "KES",
      description:
        p.public_description ||
        (p.flat_price
          ? `${p.name} — flat monthly price`
          : `${p.name} — per unit, per month`),
    }));

  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE_NAME,
    applicationCategory: "BusinessApplication",
    operatingSystem: "Web browser",
    url: `${SITE_URL}/pricing`,
    description:
      "Rental and property management software for Kenya: M-Pesa rent collection, automated invoicing, tenant portal, utility billing and financial reports.",
    ...(offers.length ? { offers } : {}),
  };
}

/** FAQ schema — the block most likely to win an expanded search result. */
export function faqJsonLd(questions = []) {
  if (!questions.length) return null;
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: questions.map((item) => ({
      "@type": "Question",
      name: item.q,
      acceptedAnswer: { "@type": "Answer", text: item.a },
    })),
  };
}

export { SITE_URL, SITE_NAME };
