import { t, useLanguage } from '../../lib/i18n';
import { Link } from 'react-router-dom';
import { CheckCircle2 } from 'lucide-react';
import type { Draft } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

export function PublishedCard({ draft, onBack }: { draft: Draft; onBack: () => void }) {
  useLanguage();
  return (
    <section className={cx(css.panel, ui.panel, css.publishedCard, 'published-card')}>
      <CheckCircle2 size={36} />
      <h2>{t('数据版本已发布')}</h2>
      <p>
        {draft.summary?.included_rows}{' '}
        {t('行已安全保存。原始文件哈希、字段映射、排除决策和口径均已冻结。')}
      </p>
      <code>{draft.published_id}</code>
      <button className={cx(css.primary, ui.primary)} onClick={onBack}>
        {t('查看数据版本')}
      </button>
      {draft.kind === 'orders' && (
        <Link
          className={cx(ui.secondary, forms.secondary)}
          to={`/dashboard?dataset=${draft.published_id}`}
        >
          {t('打开经营看板')}
        </Link>
      )}
    </section>
  );
}
