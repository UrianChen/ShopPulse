import { t, useLanguage } from '../../lib/i18n';
import type { Summary } from './types';
import type { DraftForm } from './useDraftForm';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './imports.module.css';

type Props = { summary: Summary; form: DraftForm; busy: boolean; onResolve: () => void };

/** Acknowledge warning codes and exclude source rows, with a reason for the record. */
export function ResolutionBox({ summary, form, busy, onResolve }: Props) {
  useLanguage();
  const { ack, setAck } = form;
  return (
    <fieldset disabled={busy}>
      <div className={css.resolutionBox}>
        <h3>{t('确认与排除决策')}</h3>
        {summary.warning_codes.map(code => (
          <label className={cx(ui.checkField, forms.checkField)} key={code}>
            <input
              type="checkbox"
              checked={ack.includes(code)}
              onChange={e =>
                setAck(e.target.checked ? [...ack, code] : ack.filter(v => v !== code))
              }
            />
            {t('已核实并接受')}
            {code}（{summary.issue_counts[code]} {t('处）')}
          </label>
        ))}
        <div className={cx(ui.formGrid, forms.formGrid)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('排除的源表行号')}
            <input
              aria-label={t('排除的源表行号')}
              value={form.excluded}
              placeholder={t('例如 8,12；不排除则留空')}
              onChange={e => form.setExcluded(e.target.value)}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('决策原因')}
            <input
              aria-label={t('决策原因')}
              value={form.reason}
              maxLength={500}
              placeholder={t('说明排除或接受警告的依据')}
              onChange={e => form.setReason(e.target.value)}
            />
          </label>
        </div>
        <button
          className={cx(ui.secondary, forms.secondary)}
          disabled={!form.reason.trim()}
          onClick={onResolve}
        >
          {t('保存决策并重新校验')}
        </button>
      </div>
    </fieldset>
  );
}
