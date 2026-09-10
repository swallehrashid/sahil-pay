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
**160 × 56 px** slot (`services/report_builder.py`), receipts at about **46 px
tall** on a full page and less on a cut slip
(`services/receipt_layout.py::page_css`). A square or portrait logo is fitted to
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

## 3. Receipt layout — what "a third of a page" means

A third of A4 can be cut two ways, and both are now offered as separate
choices, because "third portrait" described both and meant neither.

| Choice | Page size | How it cuts | Arrangement |
|---|---|---|---|
| **A4 (full page)** | 210 × 297 mm | — | Stacked, four money columns |
| **A4 third — wide band** | **210 × 99 mm** | Three stacked **down** a portrait sheet (cut across) | Three columns side by side |
| **A4 third — tall slip** | **99 × 297 mm** | Three **side by side** across a portrait sheet (cut down) | One narrow column |
| **Landscape A4 third — wide band** | **297 × 70 mm** | Three stacked down a landscape sheet | Three columns side by side |
| **Thermal roll (80 mm)** | 80 × 297 mm | Continuous | One narrow column |

### Choosing a paper rearranges the receipt — it does not shrink it

This is what was wrong before. Every paper used the same stacked arrangement,
and only the page size and font changed. The result was an A4 receipt that had
been made smaller, marooned in the middle of the paper.

Now the paper picks a **flow**:

* **Band** (short and wide) — the body is dealt into **three columns**:
  details | charges | totals. The height stays inside the band and the width is
  actually used. Charge tables drop to *item + paid*, because four money columns
  across a third of a page leaves each about two characters wide.
* **Column** (narrow and tall — a cut slip, a till roll) — one column,
  condensed, header stacked and centred.
* **Full** — unchanged from before.

Measured on the rendered PDF: a wide band now uses **97% of its width and 82%
of its height**; the landscape band **98% and 90%**. Verified by
`server/tests/test_receipt_geometry.py`, which reads the page box out of the PDF
and scans the image for where the ink actually reaches — so this cannot quietly
regress.

A band also **caps its charge rows at 7** and prints `+N more items — see the
full statement`. A fixed-height band cannot grow, and its second page is a
near-empty slip that reads as a printing fault.

### ⚠️ Printing: set the dialog to "Actual size", not "Fit to page"

**This is the single most common reason a correct layout comes out wrong, and it
is not a bug in the receipt.**

The PDF is generated at exactly the size chosen — a 210 × 99 mm band really is a
210 × 99 mm page. If the print dialog is set to **Fit to page** (the default
nearly everywhere), the printer scales that small page up onto the A4 sheet and
centres it — producing a shrunken receipt surrounded by white margin on all
sides. That is the printer resizing the page, not the layout.

Set **Actual size / 100% / None** under Scale. The warning now appears in the
settings screen next to the paper choice.

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
