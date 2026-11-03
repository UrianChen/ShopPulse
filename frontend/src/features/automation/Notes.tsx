import { t, useLanguage } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { NotebookPen, Trash2 } from 'lucide-react';
import { api } from '../../lib/api';
import { keys } from '../../lib/queries';
import { day, lastDay } from '../../lib/dates';
import { ErrorNotice } from '../../components/ErrorNotice';
import { noteKinds } from './constants';
import type { Note } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './automation.module.css';

export function Notes() {
  useLanguage();
  const client = useQueryClient();
  const notes = useQuery({ queryKey: keys.notes, queryFn: () => api<Note[]>('/notes') });
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({ start: today, last: today, kind: 'promotion', text: '' });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  function refresh() {
    void client.invalidateQueries({ queryKey: keys.notes });
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await api('/notes', {
        method: 'POST',
        body: JSON.stringify({
          start_date: form.start,
          end_exclusive: day(form.last, 1),
          kind: form.kind,
          text: form.text,
        }),
      });
      setForm({ ...form, text: '' });
      refresh();
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  async function remove(note: Note) {
    try {
      await api(`/notes/${note.id}`, { method: 'DELETE' });
      refresh();
    } catch (failure) {
      setError(failure);
    }
  }
  return (
    <section className={css.automationSection}>
      <div className={ui.panelTitle}>
        <div>
          <h2>
            <NotebookPen size={19} />
            {t('商家备注')}
          </h2>
          <p className={cx(ui.formHint, forms.formHint)}>
            {t(
              '记录促销、节假日、缺货或调价。覆盖报告周期的备注会作为分析背景，模型可在假设中引用。',
            )}
          </p>
        </div>
      </div>
      <form className={cx(ui.panel, css.automationForm)} onSubmit={save}>
        <fieldset disabled={pending}>
          <div className={cx(css.formGrid, ui.formGrid, forms.formGrid, css.four)}>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('开始日期')}
              <input
                type="date"
                required
                value={form.start}
                onChange={e => setForm({ ...form, start: e.target.value })}
              />
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('结束日期（含当日）')}
              <input
                type="date"
                required
                min={form.start}
                value={form.last}
                onChange={e => setForm({ ...form, last: e.target.value })}
              />
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('类型')}
              <select value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}>
                {Object.entries(noteKinds).map(([key, label]) => (
                  <option key={key} value={key}>
                    {t(label)}
                  </option>
                ))}
              </select>
            </label>
            <label className={cx(css.field, ui.field, forms.field)}>
              {t('内容')}
              <input
                required
                maxLength={300}
                value={form.text}
                onChange={e => setForm({ ...form, text: e.target.value })}
                placeholder={t('例如：国庆满减活动')}
              />
            </label>
          </div>
          <ErrorNotice error={error ?? notes.error} />
          <div className={cx(ui.formActions, forms.formActions)}>
            <button className={ui.primary}>{t('添加备注')}</button>
          </div>
        </fieldset>
      </form>
      <ul className={ui.noteList}>
        {notes.data?.map(note => (
          <li key={note.id}>
            <span className={ui.subtleBadge}>{t(noteKinds[note.kind] ?? note.kind)}</span>
            <span>
              {note.start_date} {t('至')} {lastDay(note.end_exclusive)}
            </span>
            <span>{note.text}</span>
            <button
              className={cx(ui.textButton, forms.textButton)}
              onClick={() => void remove(note)}
              aria-label={t('删除备注')}
            >
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>
      {notes.data?.length === 0 && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('还没有备注。')}</p>
      )}
    </section>
  );
}
