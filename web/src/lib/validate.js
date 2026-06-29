/**
 * validate.js — shared field validation rules, ported from ValidationService.
 *
 * Usage pattern in a modal:
 *
 *   import { rules, fieldClass, fieldError } from '../../lib/validate';
 *
 *   // Derive errors from current state (no extra state needed):
 *   const errors = {
 *     name:    rules.name(name),
 *     version: rules.version(version),
 *     url:     rules.gitUrl(url),
 *   };
 *   const canSave = Object.values(errors).every(e => !e);
 *
 *   // Track which fields the user has touched (show errors after blur):
 *   const [touched, setTouched] = useState({});
 *   const touch = field => setTouched(t => ({ ...t, [field]: true }));
 *
 *   // In JSX:
 *   <input className={fieldClass(touched.name && errors.name)}
 *          onBlur={() => touch('name')} ... />
 *   {touched.name && errors.name &&
 *     <div className="invalid-feedback">{errors.name}</div>}
 *
 *   // Save button:
 *   <button disabled={busy || !canSave}>Save</button>
 */

// ── Regex ──────────────────────────────────────────────────────────────────────

const RE_NAME    = /^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$|^[a-zA-Z0-9]{1}$/;
const RE_VERSION = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;
const RE_HTTP    = /^(?:https?:\/\/)(?:[\w._-]+(\.[\w._-]+)+(:\d+)?)(?:\/[\w./_~:@!$&'()*+,;=%-]*)?$/;
const RE_GIT     = [
  /^(https?:\/\/)(?:[\w._-]+(\.[\w._-]+)+(:\d+)?)(?:\/[\w._~-]+)+$/,
  /^(ssh:\/\/)?(\w+@)?(?:[\w._-]+(\.[\w._-]+)+(:\d+)?)[:/][\w._~-]+(\/[\w._-]+)+$/,
];
const RE_EMAIL   = /^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$/i;

// ── Rule functions — return error string or '' ─────────────────────────────────

export const rules = {
  /** Project/mirror name, username: letters, digits, dots, hyphens, underscores; ≥2 chars */
  name(value) {
    const v = (value ?? '').trim();
    if (!v) return 'Required';
    if (v.length < 2) return 'Minimum 2 characters';
    if (!RE_NAME.test(v)) return 'Letters, digits, dots, hyphens and underscores only';
    return '';
  },

  /** Version string: letters, digits, dots, hyphens; ≥1 char */
  version(value) {
    const v = (value ?? '').trim();
    if (!v) return 'Required';
    if (!RE_VERSION.test(v)) return 'Letters, digits, dots and hyphens only';
    return '';
  },

  /** HTTP/HTTPS URL */
  httpUrl(value) {
    const v = (value ?? '').trim();
    if (!v) return 'Required';
    if (!RE_HTTP.test(v)) return 'Must be a valid HTTP/HTTPS URL';
    return '';
  },

  /** Git URL (https or ssh) */
  gitUrl(value) {
    const v = (value ?? '').trim();
    if (!v) return 'Required';
    if (!RE_GIT.some(re => re.test(v))) return 'Must be a valid git URL (https:// or git@…)';
    return '';
  },

  /** Email — optional field, only validated if non-empty */
  email(value) {
    const v = (value ?? '').trim();
    if (!v) return '';          // optional
    if (!RE_EMAIL.test(v)) return 'Invalid email address';
    return '';
  },

  /** Required non-empty string with optional minimum length */
  required(value, minLen = 1, label = 'This field') {
    const v = (value ?? '').trim();
    if (!v) return 'Required';
    if (v.length < minLen) return `Minimum ${minLen} characters`;
    return '';
  },

  /** Password: required on create (minLen 8), optional on edit */
  password(value, isEdit = false) {
    const v = value ?? '';
    if (isEdit && !v) return '';   // optional on edit
    if (!v) return 'Required';
    if (v.length < 8) return 'Minimum 8 characters';
    return '';
  },
};

// ── JSX helpers ───────────────────────────────────────────────────────────────

/** Returns Bootstrap input className, adding is-invalid when there is an error to show. */
export function fieldClass(showError, base = 'form-control') {
  return showError ? `${base} is-invalid` : base;
}

/**
 * Returns the error message string to show, or null if nothing to show.
 * Use in JSX as: {fieldError(touched.foo && errors.foo, errors.foo) &&
 *   <div className="invalid-feedback">{errors.foo}</div>}
 *
 * Or more concisely just inline the condition:
 *   {touched.foo && errors.foo && <div className="invalid-feedback">{errors.foo}</div>}
 *
 * This function exists purely for symmetry with fieldClass — you can drop it
 * and use the inline pattern directly.
 */
export function fieldError(showError, message) {
  if (!showError || !message) return null;
  return message;   // return the string; caller wraps in <div className="invalid-feedback">
}
