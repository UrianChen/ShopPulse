import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { LoaderCircle, Send } from 'lucide-react';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { message, t, useLanguage } from '../../lib/i18n';
import { anyActive, keys, pollWhile, POLL } from '../../lib/queries';
import type { Paged, QuestionInput } from '../../lib/types';
import { Advice, Sentences } from './Advice';
import { modes, states, suggestedLink } from './labels';
import type { Message, OnEvidence } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './reports.module.css';

type Answer = NonNullable<Message['answer']>;

function AnswerView({
  reportId,
  answer,
  onEvidence,
  onOption,
}: {
  reportId: string;
  answer: Answer;
  onEvidence: OnEvidence;
  onOption: (option: string) => void;
}) {
  useLanguage();
  return (
    <>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t(modes[answer.generation_mode])}
        {answer.error_code && ` · ${answer.error_code}`}
      </p>
      {answer.message && <p>{message(answer.message)}</p>}
      {answer.kind === 'clarify' && !!answer.options?.length && (
        <div className={css.clarifyOptions}>
          {answer.options.map(option => (
            <button
              type="button"
              className={cx(ui.secondary, forms.secondary)}
              key={option}
              onClick={() => onOption(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <Sentences values={answer.summary} onEvidence={onEvidence} />
      {answer.analysis && (
        <Advice
          findings={answer.analysis.findings}
          recommendations={answer.analysis.recommendations}
          onEvidence={onEvidence}
        />
      )}
      {answer.new_analysis_required && (
        <Link
          className={cx(ui.textButton, forms.textButton)}
          to={suggestedLink(reportId, answer.suggested_query)}
        >
          {t(answer.suggested_query ? '按建议范围创建新分析' : '选择范围并创建新分析')}
        </Link>
      )}
    </>
  );
}

export function Questions({
  reportId,
  onEvidence,
  limitedConsent: limited = false,
}: {
  reportId: string;
  onEvidence: OnEvidence;
  limitedConsent?: boolean;
}) {
  useLanguage();
  const client = useQueryClient();
  const [question, setQuestion] = useState('');
  const [offset, setOffset] = useState(0);
  const [key, setKey] = useState(crypto.randomUUID());
  const messages = useQuery({
    queryKey: [...keys.reportMessages(reportId), offset],
    queryFn: () => api<Paged<Message>>(`/reports/${reportId}/messages?offset=${offset}`),
    refetchInterval: pollWhile<Paged<Message>>(
      data => anyActive(data.items, m => m.status),
      POLL.fast,
    ),
  });
  const send = useMutation({
    mutationFn: () => {
      const body: QuestionInput = { question };
      return api(`/reports/${reportId}/messages`, {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body: JSON.stringify(body),
      });
    },
    onSuccess: () => {
      setQuestion('');
      setKey(crypto.randomUUID());
      setOffset(0);
      void client.invalidateQueries({ queryKey: keys.reportMessages(reportId) });
      void client.invalidateQueries({ queryKey: keys.reportRuns(reportId) });
    },
  });
  function ask(text: string) {
    setQuestion(text);
    setKey(crypto.randomUUID());
  }
  const busy = send.isPending || anyActive(messages.data?.items, m => m.status);
  return (
    <section className={cx(css.panel, ui.panel, css.reportQuestions)}>
      <h2>{t('追问报告')}</h2>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('可追问销售、退款、成本与商品；更换周期请新建报告。')}
      </p>
      {limited && (
        <p className={cx(ui.reportWarning, 'report-warning')}>
          {t(
            '本报告创建时的模型授权不含追问原文，模型只会收到问题主题。在模型设置中确认新的授权范围后，创建新修订即可使用完整追问。',
          )}
        </p>
      )}
      <form
        onSubmit={e => {
          e.preventDefault();
          send.mutate();
        }}
      >
        <label className={cx(ui.field, forms.field)}>
          {t('你的问题')}
          <textarea
            required
            maxLength={2000}
            rows={3}
            value={question}
            onChange={e => ask(e.target.value)}
            placeholder={t('例如：这期退款需要关注什么？')}
          />
        </label>
        <button className={cx(css.primary, ui.primary)} disabled={busy || !question.trim()}>
          {busy ? <LoaderCircle size={15} className={ui.spin} /> : <Send size={15} />}
          {t('提交追问')}
        </button>
      </form>
      <ErrorNotice error={send.error ?? messages.error} />
      <div className={cx(css.questionList, 'question-list')}>
        {messages.data?.items.map(m => (
          <article key={m.id}>
            <h3>{m.question}</h3>
            <span className={cx(ui.importState, forms.importState, 'import-state')}>
              {t(states[m.status])}
            </span>
            {m.answer && (
              <AnswerView
                reportId={reportId}
                answer={m.answer}
                onEvidence={onEvidence}
                onOption={ask}
              />
            )}
            {m.status === 'failed' && (
              <p className={cx(ui.reportWarning, 'report-warning')}>
                {t('本次追问未完成，原报告保持不变。可以重新提交。')}
              </p>
            )}
          </article>
        ))}
      </div>
      {messages.data && messages.data.total > 20 && (
        <div className={cx(ui.pagination, forms.pagination)}>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={!offset}
            onClick={() => setOffset(offset - 20)}
          >
            {t('较新追问')}
          </button>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={offset + 20 >= messages.data.total}
            onClick={() => setOffset(offset + 20)}
          >
            {t('较早追问')}
          </button>
        </div>
      )}
    </section>
  );
}
