// Readable views of the evidence types introduced with hypothesis tests and computed values.
// Every view is a summary; the drawer always keeps the raw record below it.
import type { ReactNode } from 'react';
import { t, useLanguage } from '../../lib/i18n';
import type { Result } from '../dashboard/Dashboard';
import { decimal, formatMetric } from '../dashboard/format';
import type { Metric } from '../dashboard/format';
import { HistoryTable, StateBadge } from './Hypotheses';
import type { EvidenceRecord } from './EvidenceDrawer';
import { hypothesisReasons, hypothesisStates, toolNames } from './labels';
import type { HistoryWindow, OnEvidence } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

type Value = { value: string | null; unit: string; quality?: string; signed?: boolean };
type Source = { evidence_id?: string; path?: string };
type Operand = {
  evidence_id: string;
  tool: string;
  path?: string;
  select?: { list: string; key: string; value: string } | null;
  value?: Value;
  rank?: number;
};

const OPS: Record<string, string> = {
  diff: '差值',
  ratio: '比率',
  multiple: '倍数',
  share: '份额',
  gt: '大于',
  lt: '小于',
  abs_ge: '绝对值不低于',
  abs_gt: '绝对值大于',
  share_ge: '份额不低于',
  rank_le: '排名不晚于',
  same_sign: '同向变化',
};

export function valueText(v: Value | null | undefined, result: Result | undefined) {
  if (!v || v.value === null) return '—';
  const estimated = v.quality === 'estimated' ? t('（估算）') : '';
  const sign = v.signed && Number(v.value) > 0 ? '+' : '';
  if (v.unit === 'pp') return t('{0}{1} 个百分点', sign, decimal(v.value)) + estimated;
  if (v.unit === 'multiple') return `${decimal(v.value)}×${estimated}`;
  const unit = v.unit;
  if (unit !== 'minor_currency' && unit !== 'count' && unit !== 'ratio') return v.value;
  if (unit === 'minor_currency' && !result) return v.value;
  const metric: Metric = { value: v.value, unit, quality: 'confirmed', unavailable_reason: null };
  const text = formatMetric(metric, result?.currency ?? '', result?.currency_exponent ?? 0);
  return sign + text + estimated;
}

function SourceButton({ source, onEvidence }: { source?: Source; onEvidence: OnEvidence }) {
  useLanguage();
  if (!source?.evidence_id) return null;
  return (
    <button className={css.evidenceLink} onClick={() => onEvidence(source.evidence_id!)}>
      {t('来源证据')} {source.path}
    </button>
  );
}

function Derived({ record, result, onEvidence }: ViewProps) {
  const payload = record.payload as { op: string; a: Value; b: Value; result: Value };
  const args = (record.args ?? {}) as { a?: Source; b?: Source };
  return (
    <dl>
      <dt>{t('运算')}</dt>
      <dd>{t(OPS[payload.op] ?? payload.op)}</dd>
      <dt>a</dt>
      <dd>
        {valueText(payload.a, result)} <SourceButton source={args.a} onEvidence={onEvidence} />
      </dd>
      <dt>b</dt>
      <dd>
        {valueText(payload.b, result)} <SourceButton source={args.b} onEvidence={onEvidence} />
      </dd>
      <dt>{t('结果')}</dt>
      <dd>
        <strong>{valueText(payload.result, result)}</strong>
      </dd>
    </dl>
  );
}

function Verdict({ record, result, onEvidence }: ViewProps) {
  const p = record.payload as {
    statement: string | null;
    state: string;
    reason: string | null;
    op: string;
    threshold: string | null;
    k: number | null;
    operands: Operand[];
    derived: Value | null;
    test_evidence_id: string;
  };
  return (
    <>
      <p>
        <StateBadge state={p.state} /> {p.statement}
      </p>
      <dl>
        <dt>{t('检验条件')}</dt>
        <dd>
          {t(OPS[p.op] ?? p.op)}
          {p.threshold !== null && ` ${p.threshold}`}
          {p.k !== null && ` ${p.k}`}
        </dd>
        {p.operands.map((o, i) => (
          <div key={i}>
            <dt>{i === 0 ? 'a' : 'b'}</dt>
            <dd>
              {t(toolNames[o.tool] ?? o.tool)}
              {o.select && ` · ${o.select.value}`}
              {o.path && ` · ${o.path}`}
              {' = '}
              {o.rank !== undefined ? `#${o.rank}` : valueText(o.value, result)}{' '}
              <SourceButton source={{ evidence_id: o.evidence_id }} onEvidence={onEvidence} />
            </dd>
          </div>
        ))}
        {p.derived && (
          <>
            <dt>{t('份额')}</dt>
            <dd>{valueText(p.derived, result)}</dd>
          </>
        )}
        {p.reason && (
          <>
            <dt>{t('说明')}</dt>
            <dd>{t(hypothesisReasons[p.reason] ?? p.reason)}</dd>
          </>
        )}
      </dl>
      <button className={css.evidenceLink} onClick={() => onEvidence(p.test_evidence_id)}>
        {t('查看检验数据')}
      </button>
    </>
  );
}

function Recheck({ record }: ViewProps) {
  const items = (record.payload.items ?? []) as {
    id: string;
    statement: string | null;
    previous_state: string;
    state: string;
  }[];
  return (
    <ul className={cx(css.hypothesisList, 'hypothesis-list')}>
      {items.map(item => (
        <li key={item.id}>
          <StateBadge state={item.state} />
          <span>{item.statement ?? item.id}</span>
          <small>
            {t('上期结论')} {t(hypothesisStates[item.previous_state] ?? item.previous_state)}
          </small>
          <span />
        </li>
      ))}
    </ul>
  );
}

function History({ record, result }: ViewProps) {
  if (!result) return null;
  return <HistoryTable windows={record.payload.windows as HistoryWindow[]} result={result} />;
}

type ViewProps = { record: EvidenceRecord; result: Result | undefined; onEvidence: OnEvidence };
const VIEWS: Record<string, (props: ViewProps) => ReactNode> = {
  derive: Derived,
  test_hypothesis: Verdict,
  recheck_hypotheses: Recheck,
  get_history: History,
};

export function EvidenceView(props: ViewProps) {
  useLanguage();
  const View = VIEWS[props.record.tool];
  return (
    <>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t(toolNames[props.record.tool] ?? props.record.tool)}
        {props.record.result_hash && ` · SHA-256 ${props.record.result_hash.slice(0, 12)}`}
      </p>
      {View && <View {...props} />}
    </>
  );
}
EvidenceView.handles = (tool: string) => tool in VIEWS;
