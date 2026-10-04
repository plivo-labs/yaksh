import { flushSync } from "react-dom";

/** Shows a form's errors at once and brings the first one into view, so an error out of view in a
 * long form is not missed: an invalid field takes focus, and an error under a group of checkboxes,
 * which has no single field, scrolls into view. Returns `valid`. */
export function revealErrors(form: HTMLFormElement, markSubmitted: () => void, valid: boolean) {
  flushSync(markSubmitted);
  if (valid) return true;
  const first = form.querySelector<HTMLElement>("[aria-invalid=true], [data-slot=field-error]");
  if (first?.matches("[aria-invalid=true]")) first.focus();
  else first?.scrollIntoView({ block: "nearest" });
  return false;
}
