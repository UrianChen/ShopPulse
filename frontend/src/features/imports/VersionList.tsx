import { t, useLanguage } from '../../lib/i18n';
import { Database } from 'lucide-react';
import type { Version } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = {
  title: string;
  versions: Version[];
  pending: boolean;
  onOpen: (id: string) => void;
};

/** One kind of published version, each with a button that opens its detail. */
export function VersionList({ title, versions, pending, onOpen }: Props) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel)}>
      <div className={ui.panelTitle}>
        <h2>{title}</h2>
        <span className={css.outlineBadge}>
          {versions.length === 1 ? t('1 个版本') : t('{0} 个版本', versions.length)}
        </span>
      </div>
      {versions.map(v => (
        <div className={cx(css.versionRow, 'version-row')} key={v.id}>
          <span className={ui.tileIcon}>
            <Database size={17} />
          </span>
          <div>
            <strong>{v.name}</strong>
            <p>
              {v.row_count} {t('行 ·')}
              {v.snapshot.config.options.currency} · {v.id.slice(0, 8)}
            </p>
          </div>
          <button
            className={cx(css.textButton, ui.textButton, forms.textButton)}
            onClick={() => onOpen(v.id)}
          >
            {t('查看')}
          </button>
        </div>
      ))}
      {!pending && !versions.length && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('暂无版本，通过校验后即可发布。')}</p>
      )}
    </section>
  );
}
