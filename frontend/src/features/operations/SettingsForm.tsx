import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { t, useLanguage } from '../../lib/i18n';
import { keys } from '../../lib/queries';
import type { Config } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './operations.module.css';

export function SettingsForm({ initial }: { initial: Config }) {
  useLanguage();
  const client = useQueryClient();
  const [value, setValue] = useState(initial);
  const save = useMutation({
    mutationFn: () => api('/operations/settings', { method: 'PUT', body: JSON.stringify(value) }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.operationsSettings });
      void client.invalidateQueries({ queryKey: keys.workspace });
    },
  });
  return (
    <section className={cx(css.panel, ui.panel)}>
      <h2>{t('店铺与保留策略')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('修订')} {initial.revision}
        {t('。时区和币种作为新导入的默认值；已有数据保持原口径。修改保留时间后先预览清理范围。')}
      </p>
      <form
        onSubmit={e => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
          <label className={cx(ui.field, forms.field)}>
            {t('店铺名称')}
            <input
              required
              maxLength={100}
              value={value.name}
              onChange={e => setValue({ ...value, name: e.target.value })}
            />
          </label>
          <label className={cx(ui.field, forms.field)}>
            {t('店铺时区')}
            <input
              required
              value={value.timezone}
              onChange={e => setValue({ ...value, timezone: e.target.value })}
            />
          </label>
          <label className={cx(ui.field, forms.field)}>
            {t('默认币种')}
            <input
              required
              pattern="[A-Z]{3}"
              value={value.currency}
              onChange={e => setValue({ ...value, currency: e.target.value })}
            />
          </label>
          <label className={cx(ui.field, forms.field)}>
            {t('原文件保留天数（0 为不清理）')}
            <input
              type="number"
              min={0}
              max={3650}
              required
              value={value.raw_retention_days}
              onChange={e => setValue({ ...value, raw_retention_days: Number(e.target.value) })}
            />
          </label>
          <label className={cx(ui.field, forms.field)}>
            {t('新导出保留天数')}
            <input
              type="number"
              min={1}
              max={3650}
              required
              value={value.export_retention_days}
              onChange={e => setValue({ ...value, export_retention_days: Number(e.target.value) })}
            />
          </label>
        </div>
        <button className={ui.primary} disabled={save.isPending}>
          {t('保存设置')}
        </button>
        <ErrorNotice error={save.error} />
      </form>
    </section>
  );
}
