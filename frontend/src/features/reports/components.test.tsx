/** @vitest-environment jsdom */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setLanguage } from '../../lib/i18n';
import { content } from '../../test/fixtures';
import { renderPage } from '../../test/render';
import { serveApi } from '../../test/server';
import { Advice, Sentences } from './Advice';
import { EvidenceView } from './EvidenceViews';
import { Hypotheses } from './Hypotheses';
import { Questions } from './Questions';
import { ReportForm } from './ReportForm';
import type { Message } from './types';

afterEach(() => {
  vi.unstubAllGlobals();
  setLanguage('zh');
});

describe('evidence-bound sentences', () => {
  it('links every sentence to the evidence of its values', () => {
    const open = vi.fn();
    render(
      <Sentences
        values={[
          { text: '一条事实。', evidence_refs: ['a'] },
          { text: '两条来源。', evidence_refs: ['b', 'c'] },
        ]}
        onEvidence={open}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '查看证据' }));
    fireEvent.click(screen.getByRole('button', { name: '证据 2' }));
    expect(open.mock.calls).toEqual([['a'], ['c']]);
  });

  it('shows supported hypotheses with their test and keeps untested ones apart', () => {
    const open = vi.fn();
    const { findings, recommendations } = content();
    render(<Advice findings={findings} recommendations={recommendations} onEvidence={open} />);
    expect(screen.getByText('数据支持的假设').parentElement).toHaveTextContent(
      '退款集中在单个商品上。',
    );
    expect(screen.getByText('待验证假设').parentElement).toHaveTextContent('可能与质量问题有关');
    fireEvent.click(screen.getByRole('button', { name: '查看检验' }));
    expect(open).toHaveBeenCalledWith('ev-verdict');
    expect(screen.getByText(/验证指标：累计退款占比/)).toBeInTheDocument();
  });
});

describe('hypothesis tests', () => {
  it('labels the three server verdicts and lists ruled-out causes', () => {
    render(<Hypotheses content={content()} onEvidence={vi.fn()} />);
    const [list, ruled] = screen.getAllByRole('list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows.map(row => row.querySelector('b')?.textContent)).toEqual([
      '数据支持',
      '已被排除',
      '无法判断',
    ]);
    expect(rows[0]).toHaveTextContent('服务端提出');
    // Estimated values are marked in the sentence itself; the row notes the test used them.
    expect(rows[1]).toHaveTextContent('模型提出 · 第 1 轮 · 基于估算值');
    expect(rows[1]).not.toHaveTextContent('（估算）');
    expect(rows[2]).toHaveTextContent('模型提出 · 第 2 轮 · 订单样本偏少');
    expect(within(ruled).getByRole('listitem')).toHaveTextContent('数据不支持该解释。');
  });

  it('renders a verdict record as condition, operands and state', () => {
    const open = vi.fn();
    render(
      <EvidenceView
        record={{
          evidence_id: 'ev-verdict',
          tool: 'test_hypothesis',
          result_hash: 'abcdef1234567890',
          payload: {
            statement: '退款集中在单个商品上。',
            state: 'supported',
            reason: null,
            op: 'share_ge',
            threshold: '0.5',
            k: null,
            operands: [
              {
                evidence_id: 'ev-refunds',
                tool: 'refund_breakdown',
                path: 'metrics.refund_amount',
                select: { list: 'items', key: 'sku', value: 'A' },
                value: { value: '10000', unit: 'minor_currency', quality: 'confirmed' },
              },
            ],
            derived: { value: '0.8', unit: 'ratio', quality: 'confirmed', signed: false },
            test_evidence_id: 'ev-refunds',
          },
        }}
        result={content().metrics}
        onEvidence={open}
      />,
    );
    expect(screen.getByText('数据支持')).toBeInTheDocument();
    expect(screen.getByText('份额不低于 0.5')).toBeInTheDocument();
    expect(screen.getByText(/退款拆解 · A · metrics.refund_amount = ¥100.00/)).toBeInTheDocument();
    expect(screen.getByText('80.00%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看检验数据' }));
    expect(open).toHaveBeenCalledWith('ev-refunds');
  });
});

function message(id: string, answer: Partial<NonNullable<Message['answer']>>): Message {
  return {
    id,
    sequence: 1,
    question: '问题 ' + id,
    status: 'ready',
    created_at: '2026-10-05T00:00:00Z',
    answer: {
      generation_mode: 'native_tools',
      message: null,
      summary: [],
      analysis: null,
      limitations: [],
      error_code: null,
      new_analysis_required: false,
      evidence_index: [],
      ...answer,
    },
  };
}

describe('follow-up questions', () => {
  it('renders answers, clarifying options and suggested new ranges', async () => {
    serveApi({
      '/reports/r1/messages': {
        total: 3,
        items: [
          message('m1', {
            kind: 'answer',
            summary: [{ text: '本期累计退款为 CNY 100.00。', evidence_refs: ['ev'] }],
          }),
          message('m2', { kind: 'clarify', message: '你想了解退款还是毛利？', options: ['退款'] }),
          message('m3', {
            kind: 'suggested_query',
            new_analysis_required: true,
            suggested_query: {
              start: '2026-09-21',
              end_exclusive: '2026-09-28',
              comparison: 'previous',
              skus: [],
            },
          }),
        ],
      },
    });
    renderPage(<Questions reportId="r1" onEvidence={vi.fn()} />);
    expect(await screen.findByText('本期累计退款为 CNY 100.00。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '退款' }));
    expect(screen.getByLabelText('你的问题')).toHaveValue('退款');
    const link = screen.getByRole('link', { name: '按建议范围创建新分析' });
    expect(link.getAttribute('href')).toContain('start=2026-09-21');
    expect(link.getAttribute('href')).toContain('parent=r1');
  });
});

describe('language switching', () => {
  it('translates the form without losing what the user typed', async () => {
    renderPage(
      <ReportForm
        versions={[
          {
            id: 'd1',
            name: '订单',
            row_count: 6,
            created_at: '2026-10-05T00:00:00Z',
            summary: null,
            snapshot: {
              config: {
                options: {
                  coverage_start: '2026-09-01T00:00:00+08:00',
                  coverage_end_exclusive: '2026-10-05T00:00:00+08:00',
                },
              },
            },
          },
        ]}
        models={[]}
      />,
    );
    const title = screen.getByLabelText('报告标题');
    fireEvent.change(title, { target: { value: '我的周报' } });
    act(() => setLanguage('en'));
    await waitFor(() => expect(screen.getByLabelText('Report title')).toHaveValue('我的周报'));
  });
});
