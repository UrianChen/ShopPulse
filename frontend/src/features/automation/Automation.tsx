import { t, useLanguage } from '../../lib/i18n';
import { Actions } from './Actions';
import { Notes } from './Notes';
import { Schedules } from './Schedules';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import css from './automation.module.css';
import '../../styles/tables.css';

export { ActionRow } from './ActionRow';
export { followupStates, metricNames, noteKinds } from './constants';
export type { ActionItem, Evaluation } from './types';

export function Automation() {
  useLanguage();
  return (
    <div className={css.automation}>
      <section className={cx(ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('自动化')}</h1>
          <p>{t('定时生成周报，记录经营背景，跟进建议效果。')}</p>
        </div>
      </section>
      <Schedules />
      <Notes />
      <Actions />
    </div>
  );
}
