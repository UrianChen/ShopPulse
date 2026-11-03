import { t, useLanguage } from '../../lib/i18n';
import { useState } from 'react';
import type { FormEvent } from 'react';
import { KeyRound, LoaderCircle, ShieldCheck } from 'lucide-react';
import { api } from '../../lib/api';
import type { ModelConfig, ModelInput, ModelPatch, Protocol } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { empty, originOf, protocols } from './constants';
import type { ModelForm } from './constants';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './models.module.css';

export function ConfigForm({
  item,
  onDone,
  onCancel,
}: {
  item?: ModelConfig;
  onDone: () => void;
  onCancel: () => void;
}) {
  useLanguage();
  const [form, setForm] = useState<ModelForm>(
    item
      ? {
          name: item.name,
          base_url: item.base_url,
          model_name: item.model_name,
          review_model_name: item.review_model_name ?? '',
          protocol: item.protocol ?? 'openai_chat',
          timeout_seconds: item.timeout_seconds,
          is_default: item.is_default,
          product_name_mode: item.product_name_mode,
          token_limit_parameter: item.token_limit_parameter,
        }
      : empty,
  );
  // Never put secrets in query/mutation caches, URLs or browser storage.
  const [key, setKey] = useState('');
  const [clear, setClear] = useState(false);
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  function change<K extends keyof ModelForm>(field: K, value: ModelForm[K]) {
    setForm(previous => ({ ...previous, [field]: value }));
    if (field === 'base_url' || field === 'product_name_mode' || field === 'protocol')
      setConsent(false);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    // Unreachable (required checkbox, disabled button), but it narrows `consent` to `true`.
    if (!consent) return;
    setPending(true);
    setError('');
    const input: ModelInput | ModelPatch = {
      ...form,
      consent,
      ...(item ? { revision: item.revision } : {}),
      ...(key ? { api_key: key } : {}),
      ...(clear ? { clear_api_key: true } : {}),
    };
    const body = JSON.stringify(input);
    setKey('');
    try {
      await api(`/model-configs${item ? `/${item.id}` : ''}`, {
        method: item ? 'PATCH' : 'POST',
        body,
      });
      onDone();
    } catch (error) {
      setError(error instanceof Error ? error.message : t('保存失败，请重试。'));
    } finally {
      setPending(false);
    }
  }
  return (
    <section className={cx(ui.panel, css.modelEditor)}>
      <div className={ui.panelTitle}>
        <div>
          <h2>{item ? t('编辑模型配置') : t('添加模型配置')}</h2>
        </div>
        <KeyRound size={21} />
      </div>
      <form onSubmit={save}>
        <fieldset disabled={pending}>
          <div className={cx(ui.formGrid, forms.formGrid)}>
            <label className={cx(ui.field, forms.field)}>
              {t('配置名称')}
              <input
                required
                maxLength={100}
                value={form.name}
                onChange={e => change('name', e.target.value)}
                placeholder={t('例如：经营分析模型')}
              />
            </label>
            <label className={cx(ui.field, forms.field)}>
              {t('模型名称')}
              <input
                required
                maxLength={200}
                value={form.model_name}
                onChange={e => change('model_name', e.target.value)}
                placeholder={t('服务提供方给出的模型 ID')}
              />
            </label>
          </div>
          <label className={cx(ui.field, forms.field)}>
            {t('接口协议')}
            <select
              value={form.protocol}
              onChange={e => change('protocol', e.target.value as Protocol)}
            >
              {(Object.keys(protocols) as Protocol[]).map(key => (
                <option key={key} value={key}>
                  {t(protocols[key].label)}
                </option>
              ))}
            </select>
          </label>
          <label className={cx(ui.field, forms.field)}>
            {t('API 根地址')}
            <input
              required
              type="url"
              maxLength={500}
              value={form.base_url}
              onChange={e => change('base_url', e.target.value)}
              placeholder={protocols[form.protocol].placeholder}
            />
          </label>
          <p className={cx(ui.formHint, forms.formHint)}>{t(protocols[form.protocol].hint)}</p>
          <label className={cx(ui.field, forms.field)}>
            API Key
            <input
              type="password"
              autoComplete="new-password"
              maxLength={4096}
              value={key}
              disabled={clear}
              onChange={e => setKey(e.target.value)}
              placeholder={
                item?.has_api_key
                  ? t('已保存密钥，留空保留；输入新值替换')
                  : t('可选，无认证服务可留空')
              }
            />
          </label>
          <p className={cx(ui.formHint, forms.formHint)}>{t('密钥在后端加密保存，不会回显。')}</p>
          {item?.has_api_key && (
            <label className={cx(css.checkField, ui.checkField, forms.checkField)}>
              <input
                type="checkbox"
                checked={clear}
                onChange={e => {
                  setClear(e.target.checked);
                  setKey('');
                }}
              />
              {t('清除已保存的 API Key')}
            </label>
          )}
          <details className={ui.advancedSettings}>
            <summary>{t('高级设置')}</summary>{' '}
            <div className={cx(ui.formGrid, forms.formGrid)}>
              <label className={cx(ui.field, forms.field)}>
                {t('请求超时（秒）')}
                <input
                  type="number"
                  min={5}
                  max={300}
                  required
                  value={form.timeout_seconds}
                  onChange={e => change('timeout_seconds', Number(e.target.value))}
                />
              </label>
              <label className={cx(ui.field, forms.field)}>
                {t('输出长度参数')}
                <select
                  value={form.token_limit_parameter}
                  onChange={e =>
                    change(
                      'token_limit_parameter',
                      e.target.value as ModelForm['token_limit_parameter'],
                    )
                  }
                >
                  <option value="none">{t('不发送（兼容优先）')}</option>
                  <option value="max_tokens">max_tokens</option>
                  <option value="max_completion_tokens">max_completion_tokens</option>
                </select>
              </label>
            </div>
            <p className={cx(ui.formHint, forms.formHint)}>{t('仅在服务支持时设置长度参数。')}</p>
            <label className={cx(ui.field, forms.field)}>
              {t('审稿模型（可选）')}
              <input
                maxLength={200}
                value={form.review_model_name}
                onChange={e => change('review_model_name', e.target.value)}
                placeholder={t('同一服务上更便宜的模型 ID，留空不审稿')}
              />
            </label>
            <p className={cx(ui.formHint, forms.formHint)}>
              {t(
                '报告校验通过后用该模型独立审读正文，发现方向不符或结论过度时触发一次局部修复；使用相同地址、密钥和授权范围。',
              )}
            </p>
          </details>
          <div className={css.modelConsent}>
            <ShieldCheck size={21} />
            <div>
              <strong>{t('确认数据发送范围')}</strong>
              <p>
                {t('目标服务：')}
                <b>{originOf(form.base_url)}</b>
              </p>
              <p>
                {t(
                  '发送汇总指标、质量摘要、所选商品信息、追问原文、最近三轮回答和与报告周期重叠的商家备注，不发送原始订单。',
                )}
              </p>
              <label className={cx(ui.field, forms.field)}>
                {t('商品信息范围')}
                <select
                  value={form.product_name_mode}
                  onChange={e =>
                    change('product_name_mode', e.target.value as ModelForm['product_name_mode'])
                  }
                >
                  <option value="sku_only">{t('仅 SKU（默认）')}</option>
                  <option value="include_names">{t('SKU 与商品名称')}</option>
                </select>
              </label>
              <label className={cx(css.checkField, ui.checkField, forms.checkField)}>
                <input
                  required
                  type="checkbox"
                  checked={consent}
                  onChange={e => setConsent(e.target.checked)}
                />
                {t('我同意向该服务发送上述数据。')}
              </label>
            </div>
          </div>
          <label className={cx(css.checkField, ui.checkField, forms.checkField)}>
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={e => change('is_default', e.target.checked)}
            />
            {t('设为默认模型')}
          </label>
          <ErrorNotice error={error} />
          <div className={cx(ui.formActions, forms.formActions)}>
            <button className={ui.primary} disabled={!consent || pending}>
              {pending && <LoaderCircle size={16} className={ui.spin} />}
              {t('保存配置')}
            </button>
            <button type="button" className={cx(ui.secondary, forms.secondary)} onClick={onCancel}>
              {t('取消')}
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
