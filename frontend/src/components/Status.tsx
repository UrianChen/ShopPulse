import type { ReactNode } from 'react';
import { t, useLanguage } from '../lib/i18n';
import { ErrorNotice } from './ErrorNotice';
import ui from './ui.module.css';

/**
 * Loading, error and empty states for a query, in that order; renders ``children`` otherwise.
 * ``empty`` is shown when ``isEmpty`` is true after loading.
 */
export function QueryState({
  pending,
  error,
  isEmpty = false,
  empty,
  loading,
  children,
}: {
  pending: boolean;
  error: unknown;
  isEmpty?: boolean;
  empty?: ReactNode;
  loading?: ReactNode;
  children: ReactNode;
}) {
  useLanguage();
  if (error) return <ErrorNotice error={error} />;
  if (pending) return <p className={ui.emptyCopy}>{loading ?? t('读取中…')}</p>;
  if (isEmpty) return <>{empty}</>;
  return <>{children}</>;
}
