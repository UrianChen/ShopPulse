import { t, useLanguage, getLanguage } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { LoaderCircle } from 'lucide-react';
import { api } from '../../lib/api';
import type { DatasetVersion, ModelConfig } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { formats, weekdays } from './constants';
import type { Schedule } from './types';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './automation.module.css';

export function ScheduleForm({
  item,
  versions,
  models,
  onDone,
  onCancel,
}: {
  item?: Schedule;
  versions: DatasetVersion[];
  models: ModelConfig[];
  onDone: () => void;
  onCancel: () => void;
}) {
  useLanguage();
  const [form, setForm] = useState({
    name: item?.name ?? '',
    title: item?.title ?? t('经营周报'),
    dataset_id: item?.dataset_id ?? '',
    model_config_id: item?.model_config_id ?? '',
    period_days: item?.period_days ?? 7,
    weekday: item?.weekday ?? 0,
    hour: item?.hour ?? 8,
    language: item?.language ?? getLanguage(),
    webhook_format: item?.webhook_format ?? 'generic',
    enabled: item?.enabled ?? true,
  });
  const [webhook, setWebhook] = useState('');
  const [clearWebhook, setClearWebhook] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  function change<K extends keyof typeof form>(field: K, value: (typeof form)[K]) {
    setForm(previous => ({ ...previous, [field]: value }));
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    const body = {
      ...form,
      dataset_id: form.dataset_id || null,
      model_config_id: form.model_config_id || null,
      ...(webhook ? { webhook_url: webhook } : {}),
      ...(clearWebhook ? { clear_webhook: true } : {}),
      ...(item ? { revision: item.revision } : {}),
    };
    try {
      await api(`/schedules${item ? `/${item.id}` : ''}`, {
        method: item ? 'PATCH' : 'POST',
        body: JSON.stringify(body),
      });
      setWebhook('');
      onDone();
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  return (
    <form className={cx(ui.panel, css.automationForm)} onSubmit={save}>
      <h2>{item ? t('编辑定时周报') : t('新建定时周报')}</h2>
      <fieldset disabled={pending}>
        <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('任务名称')}
            <input
              required
              maxLength={100}
              value={form.name}
              onChange={e => change('name', e.target.value)}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('报告标题')}
            <input
              required
              maxLength={100}
              value={form.title}
              onChange={e => change('title', e.target.value)}
            />
          </label>
        </div>
        <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('订单数据版本')}
            <select value={form.dataset_id} onChange={e => change('dataset_id', e.target.value)}>
              <option value="">{t('始终使用最新版本')}</option>
              {versions.map(v => (
                <option key={v.id} value={v.id}>
                  {v.name} · {v.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('分析模型')}
            <select
              value={form.model_config_id}
              onChange={e => change('model_config_id', e.target.value)}
            >
              <option value="">{t('无需模型 · 确定性摘要')}</option>
              {models.map(m => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className={cx(css.formGrid, ui.formGrid, forms.formGrid, css.four)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('分析天数')}
            <input
              type="number"
              min={1}
              max={31}
              required
              value={form.period_days}
              onChange={e => change('period_days', Number(e.target.value))}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('执行日')}
            <select value={form.weekday} onChange={e => change('weekday', Number(e.target.value))}>
              {weekdays.map((name, index) => (
                <option key={name} value={index}>
                  {t(name)}
                </option>
              ))}
            </select>
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('执行时刻')}
            <select value={form.hour} onChange={e => change('hour', Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, hour) => (
                <option key={hour} value={hour}>
                  {String(hour).padStart(2, '0')}:00
                </option>
              ))}
            </select>
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('报告语言')}
            <select value={form.language} onChange={e => change('language', e.target.value)}>
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>
        <p className={cx(ui.formHint, forms.formHint)}>
          {t('每次以数据覆盖截止日为终点，分析最近若干天并与上一等长周期比较；没有新数据时跳过。')}
        </p>
        <div className={cx(css.formGrid, ui.formGrid, forms.formGrid)}>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('通知地址（Webhook）')}
            <input
              type="url"
              autoComplete="off"
              maxLength={1000}
              value={webhook}
              disabled={clearWebhook}
              onChange={e => setWebhook(e.target.value)}
              placeholder={item?.has_webhook ? t('已保存地址，留空保留；输入新值替换') : 'https://'}
            />
          </label>
          <label className={cx(css.field, ui.field, forms.field)}>
            {t('消息格式')}
            <select
              value={form.webhook_format}
              onChange={e => change('webhook_format', e.target.value)}
            >
              {Object.entries(formats).map(([key, label]) => (
                <option key={key} value={key}>
                  {t(label)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className={cx(ui.formHint, forms.formHint)}>
          {t('地址加密保存且不回显；仅允许公网 HTTPS，内网地址需部署者加入白名单。')}
        </p>
        {item?.has_webhook && (
          <label className={cx(ui.checkField, forms.checkField)}>
            <input
              type="checkbox"
              checked={clearWebhook}
              onChange={e => {
                setClearWebhook(e.target.checked);
                setWebhook('');
              }}
            />
            {t('清除已保存的通知地址')}
          </label>
        )}
        <label className={cx(ui.checkField, forms.checkField)}>
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={e => change('enabled', e.target.checked)}
          />
          {t('启用')}
        </label>
        <ErrorNotice error={error} />
        <div className={cx(ui.formActions, forms.formActions)}>
          <button className={ui.primary}>
            {pending && <LoaderCircle size={16} className={ui.spin} />}
            {t('保存')}
          </button>
          <button type="button" className={cx(ui.secondary, forms.secondary)} onClick={onCancel}>
            {t('取消')}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
