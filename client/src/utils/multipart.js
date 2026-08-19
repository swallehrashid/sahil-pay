/**
 * Build a request body that can actually carry a file.
 *
 * A File cannot travel inside JSON: JSON.stringify(file) is `{}`, so a form
 * that posts `{ ...fields, image }` as JSON sends the fields and silently
 * throws the photo away. Nothing errors, the request succeeds, and the picture
 * simply never arrives — which reads as "the upload is broken on that portal"
 * rather than "the body was the wrong shape".
 *
 * Returns FormData when at least one named field holds a File/Blob, and the
 * plain object otherwise, so a form with no attachment keeps the JSON path
 * (and the base query's ""→null sanitising with it).
 */
export function withFiles(values, fileFields = []) {
  const carries = fileFields.some((field) => {
    const value = values[field];
    return value instanceof File || value instanceof Blob;
  });
  if (!carries) {
    // Drop the empty file slots so the JSON body doesn't ship `"image": null`.
    const rest = { ...values };
    for (const field of fileFields) delete rest[field];
    return rest;
  }

  const form = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null) continue;
    if (fileFields.includes(key)) {
      if (value instanceof File || value instanceof Blob) form.append(key, value);
      continue;
    }
    form.append(key, value);
  }
  return form;
}

export default withFiles;
