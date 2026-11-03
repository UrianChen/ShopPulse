/** @vitest-environment jsdom */
import axe from 'axe-core';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { report } from '../../test/fixtures';
import { renderPage } from '../../test/render';
import { recordedReportId, serveApi } from '../../test/server';
import { ReportDetail } from './ReportDetail';

// Charts are covered by the dashboard; here they would only need a full metric result.
vi.mock('../dashboard/Dashboard', () => ({ Trend: () => null, Contributions: () => null }));

function open(value: ReturnType<typeof report>, extra: Record<string, unknown> = {}) {
  serveApi({
    '/reports/r1': value,
    '/reports/r1/runs': [],
    '/reports/r1/actions': [],
    '/reports/r1/exports': [],
    '/reports/r1/messages': { total: 0, items: [] },
    ...extra,
  });
  return renderPage(<ReportDetail />, { route: '/reports/r1', path: '/reports/:reportId' });
}

describe('report detail', () => {
  it('shows progress while the report is analyzed', async () => {
    open(report({ status: 'analyzing', content: null }));
    const status = await screen.findByText('分析与校验中');
    expect(status.closest('.report-status')).toHaveTextContent('正在准备报告');
    expect(screen.queryByText('经营概览')).not.toBeInTheDocument();
  });

  it('explains a failed report', async () => {
    open(report({ status: 'failed', error_code: 'METRICS_FAILED', content: null }));
    expect(await screen.findByRole('alert')).toHaveTextContent('报告未完成：METRICS_FAILED');
  });

  it('keeps the deterministic summary when the model failed', async () => {
    const value = report({ status: 'ready_with_warnings' });
    value.content = { ...value.content!, model_error_code: 'EVIDENCE_VALIDATION_FAILED' };
    open(value);
    expect(await screen.findByText(/EVIDENCE_VALIDATION_FAILED/)).toHaveTextContent(
      '当前保留确定性摘要',
    );
  });

  it('opens the evidence behind a sentence and follows its sources', async () => {
    open(report(), {
      '/reports/r1/evidence/ev-metrics': {
        evidence_id: 'ev-metrics',
        tool: 'calculate_metrics',
        payload: { current: {} },
        result_hash: 'abc',
      },
      '/reports/r1/evidence/ev-verdict': {
        evidence_id: 'ev-verdict',
        tool: 'test_hypothesis',
        result_hash: 'def',
        payload: {
          statement: '退款集中在单个商品上。',
          state: 'supported',
          reason: null,
          op: 'share_ge',
          threshold: '0.5',
          k: null,
          operands: [],
          derived: null,
          test_evidence_id: 'ev-refunds',
        },
      },
    });
    const overview = (await screen.findByText('经营概览')).closest('section')!;
    fireEvent.click(within(overview).getByRole('button', { name: '查看证据' }));
    const drawer = await screen.findByRole('dialog', { name: '计算证据' });
    expect(await within(drawer).findByText(/经营指标计算/)).toBeInTheDocument();
    // Raw data stays available; it is expanded for evidence without a readable view.
    expect(within(drawer).getByText('原始证据数据').closest('details')).toHaveAttribute('open');
    fireEvent.click(screen.getAllByRole('button', { name: '查看检验' })[0]);
    expect(await within(drawer).findByText('份额不低于 0.5')).toBeInTheDocument();
    fireEvent.click(within(drawer).getByRole('button', { name: '关闭证据' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('has no serious accessibility violations on a recorded agent report', async () => {
    const { container } = renderPage(<ReportDetail />, {
      route: `/reports/${recordedReportId}`,
      path: '/reports/:reportId',
    });
    await screen.findByRole('heading', { name: '假设检验' });
    // jsdom cannot compute colours, so contrast is checked in the browser, not here.
    const results = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } });
    const serious = results.violations.filter(v =>
      ['serious', 'critical'].includes(v.impact ?? ''),
    );
    expect(serious.map(v => `${v.id}: ${v.nodes.length}`)).toEqual([]);
  });
});
