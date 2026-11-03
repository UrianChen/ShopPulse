import { t, useLanguage } from '../../lib/i18n';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';

const stateName: Record<string, string> = {
  mapping_required: '待确认映射',
  validating: '校验中',
  review_required: '待处理问题',
  ready: '可发布',
  publishing: '发布中',
  published: '已发布',
  failed: '处理失败',
  parsing: '解析中',
};

export function ImportState({ value }: { value: string }) {
  useLanguage();
  return (
    <span
      className={cx(
        ui.importState,
        forms.importState,
        ui[`state-${value}`],
        forms[`state-${value}`],
        'import-state',
      )}
    >
      {t(stateName[value] ?? value)}
    </span>
  );
}
