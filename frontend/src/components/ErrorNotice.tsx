import { message, useLanguage } from '../lib/i18n';
import { ApiError } from '../lib/api';
import ui from './ui.module.css';

/** Shared error banner: localizes server messages and shows the error code when there is one. */
export function ErrorNotice({ error }: { error: unknown }) {
  useLanguage();
  if (!error) return null;
  const text = error instanceof Error ? error.message : String(error);
  return (
    <div className={ui.errorNotice} role="alert">
      {message(text)}
      {error instanceof ApiError && <small>{error.code}</small>}
    </div>
  );
}
