# Sahil Pay — Logo, Signature, Layout and Colour Requirements

Everything a landlord or property manager needs to know to get their own
identity onto their receipts, statements and reports — and the reasons behind
each number, because most of them are a property of what the code actually does
to the file rather than house style.

---

## 0. If your logo did not appear before: it was not your file

There was a bug, and it was ours. The settings page sent the chosen file inside
a JSON body, and a browser `File` has no JSON representation —
`JSON.stringify({logo: file})` produces `{"logo":{}}`. So the request
succeeded, the page said **"Settings saved"**, and the file never left the
browser. No dimension, format or size would have made any difference.

Fixed in `client/src/utils/toFormData.js` (the file is now sent as multipart)
and `routes/settings_routes.py` (which now reads it). The same bug affected the
signature on the Account page.

Two things also changed so this cannot hide again:

* The Logo and Signature fields now **show what is actually stored on the
  server**, on a checkerboard background — so a white logo that flattened to
  invisible is visible as a problem, and an upload that did not happen is
  obvious immediately.
* The toast says **"Settings saved — logo uploaded."** only when a file was
  genuinely sent.

---

## 1. Logo

### Requirements

| | |
|---|---|
| **Formats** | PNG, JPG, WebP |
| **Maximum file size** | 5 MB |
| **Minimum width** | 300 px |
| **Ideal width** | 600–1200 px |
| **Shape** | **Wide, not tall** — between 2:1 and 4:1 |
| **Background** | Any, but see the transparency warning below |
| **Colour** | Dark or full-colour. **Not white or pale.** |

### Why those numbers

**Wide, not tall.** The renderers box the logo: reports draw it into a
**160 × 56 px** slot (`services/report_builder.py`), receipts at about **22–24 mm
tall** (adjustable in Settings → Receipts & colours → Letterhead size;
`services/receipt_layout.py::page_css`). A square or portrait logo is fitted to
that box by its *height*, so it ends up a fraction of the available width and
looks tiny. A wide lockup fills the slot.

**300 px minimum, 600–1200 px ideal.** The server downscales every brand image
to **600 px wide** and squeezes it to about **80 KB**
(`storage_service.IMAGE_RULES["brand"]`). Anything wider than 1200 px is simply
discarded, so a 4000 px file buys nothing and only slows the upload. Below
300 px there is nothing to work with and it prints soft.

**Transparency is flattened onto WHITE.** Every brand image is re-encoded to
JPEG, and transparency is composited onto white first
(`storage_service.optimise_image`). A white logo on a transparent background
becomes white on white — uploaded perfectly, invisible on every document. This
is the most likely reason a logo appears to "not work" once the upload bug is
out of the way. **Upload the dark version of your logo, not the reversed one.**

**Trim the margin.** Whitespace baked into the image file is drawn as part of
the logo, so it eats the 160 × 56 box and shrinks the visible mark. Crop tight.

### The fastest thing that works
A **1000 × 300 px PNG**, dark logo, cropped tight to the mark, under 500 KB.

---

## 2. Signature

### Requirements

| | |
|---|---|
| **Formats** | PNG, JPG, WebP |
| **Maximum file size** | 5 MB |
| **Minimum width** | 300 px |
| **Ideal width** | 600–1200 px |
| **Shape** | A wide strip — between 3:1 and 5:1 |
| **Ink** | Dark. **Not white or very light.** |

### Why

It is drawn at up to **60 px tall** (`report_builder`), and proportionally
smaller on a band or a slip. A photo of a whole A4 page with a signature in the
middle reduces the signature itself to a few pixels — **crop tight to the ink**.

The same white-flattening rule applies: light ink disappears.

Shadows and page ruling survive the upload, so photograph it **flat, in even
light**, or scan it. A phone photo at an angle produces a grey wedge behind the
signature on every document you issue.

### The fastest thing that works
Sign on plain white paper with a **black or dark blue pen**, photograph it flat,
crop to just the signature, upload. Roughly **900 × 250 px**.

### Where it goes
`Settings → Account → Signature`. It is an **account-level** asset — it appears
on every document the company issues, so replacing it requires
`settings: edit` permission even though the rest of that page is self-service.

---

## 3. Receipt layout — what prints is what you preview

**Every A4 paper is generated as a real A4 page with the receipt already in its
place.** The PDF page is the sheet in the printer, so a print dialog has nothing
to rotate or rescale — "Fit to page", "Actual size" and auto-rotate all print
the same thing, and the preview in Settings (which draws the PDF itself) is
exactly that page.

| Choice | Receipt | On the sheet | Arrangement |
|---|---|---|---|
| **A4 (full page)** | 210 × 297 mm | the whole page | Stacked, four money columns (due / paid / balance c/f) |
| **A4 third — portrait (top third of the page)** | **210 × 99 mm** | the **top third of an upright A4 sheet**, dashed cut line under it | Three tables across: Details · Charges · Summary |
| **A4 third — narrow strip** | 70 × 297 mm | the left third of an upright A4 sheet | One column |
| **Landscape A4 third — wide band** | 297 × 70 mm | the top third of a sideways A4 sheet | Three tables across |
| **Thermal roll (80 mm)** | 80 mm wide | its own 80 mm page (a till printer) | One column |

### Why it used to print wrong

The top-third receipt used to be a PDF whose page *was* 210 × 99 mm. A page
wider than it is tall is turned to landscape by every print dialog and scaled up
to fill A4 — the receipt came out rotated across the whole sheet, tiny text and
huge gaps, while the preview (which shows the page as it is) looked fine. The
old "tall slip" was 99 mm wide, which cannot be cut three times from a 210 mm
sheet at all, so every printer rescaled it too.

### Type and spacing

Sized against a real owner-supplied receipt: a ~22 mm logo, 15 pt "OFFICIAL
RECEIPT", 12.5 pt company name, 9.5 pt contacts and 10 pt body text, with rows
only a hair apart. Details labels are only as wide as their words, so "Received
from  Grace Wanjiru" sit side by side. Long values wrap inside their own column.

**Letterhead size** (Settings → Receipts & colours) scales the logo, the company
name and the contact info separately, 50 %–250 %, and sets the name's alignment.

### When it does not fit

A third of a page cannot grow. The top third prints up to 7 charge lines and 3
"still owed" lines (the 70 mm landscape band 5 and 1) and says how many more
there are — "+2 more items — see the full statement" — rather than cutting
anything off. Verified on the rendered PDF by `server/tests/test_receipt_geometry.py`:
every mark stays above the cut line.

---

## 4. Theme colours — receipts *and* reports

`Settings → Receipt layout & document colours`.

Pick a **primary** and a **secondary** from **36 colours**. Both apply to
**every receipt, statement and report** — not just receipts, because a
statement in one colour handed to an owner alongside a receipt in another looks
like two different companies produced them.

| Role | Where it is used |
|---|---|
| **Primary** | Headings, the company name, table-header text, the signature rule — everything a reader has to **read**. |
| **Secondary** | The rule under the letterhead, the line above a total, the emphasis on the amount paid — the accent, **seen** rather than read. |

### Why it is a closed palette and not a colour picker

These become ink on white paper, printed on an office laser and then
photographed by a tenant. A pastel that looks fine on a backlit screen fails all
three. **Every one of the 36 colours is checked to hold at least 4.5:1 contrast
against white** — pinned by a test that computes the relative luminance of each
entry, so a colour cannot be added later that fails it.

Anything outside the palette is refused and falls back to the default rather
than being honoured. Picking the same colour twice is also corrected: one colour
means no accent, and every rule and total vanishes into the body text.

Table-header and total-row **fills are derived** from your primary by tinting it
towards white — not chosen. That is what makes all 36 combinations legible
without anyone having checked 36 combinations by eye.

**Never touched it?** Nothing changes. `NULL` means the Sahil Pay palette, and
every existing account renders exactly as it did.

---

## 5. Checking it worked

1. `Settings → General` — upload the logo, **Save**. The field should now show
   the stored image with *"Saved — this is what appears on your documents."*
2. `Settings → Account` — upload the signature, **Save account**. Same
   confirmation.
3. `Settings → Receipt layout & document colours` — pick a paper and two
   colours, then **Preview**. The preview is a real PDF from the real renderer
   on the real code path, so what it shows is what prints.
4. Download any receipt and any report and confirm the logo, the signature and
   both colours are on both.

If the logo is missing from the preview but the General page shows it as saved,
it is almost certainly the white-flattening problem in §1.
