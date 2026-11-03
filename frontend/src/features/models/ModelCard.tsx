import { t, useLanguage, locale, message } from '../../lib/i18n';
import { useState } from 'react';
import { CheckCircle2, CircleX, KeyRound, LoaderCircle, Server, ShieldCheck } from 'lucide-react';
import { api } from '../../lib/api';
import type { ModelConfig } from '../../lib/types';
import { ErrorNotice } from '../../components/ErrorNotice';
import { originOf, protocols, stages, strategies } from './constants';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './models.module.css';

function ConsentUpgrade({ item, onRefresh }: { item: ModelConfig; onRefresh: () => void }) {
  useLanguage();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function confirm() {
    setPending(true);
    setError('');
    try {
      await api(`/model-configs/${item.id}/consent`, { method: 'POST' });
      onRefresh();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t('操作失败。'));
    } finally {
      setPending(false);
    }
  }
  return (
    <div className={cx(css.modelConsent, css.consentUpgrade)} role="status">
      <ShieldCheck size={21} />
      <div>
        <strong>{t('授权范围需要更新')}</strong>
        <p>
          {t('此配置在 1.x 版本确认授权，模型看不到追问原文和商家备注，追问时只收到问题主题。')}
        </p>
        <p>
          {t('确认后将向')}
          <b>{originOf(item.base_url)}</b>
          {t(
            '发送汇总指标、质量摘要、所选商品信息、追问原文、最近三轮回答和与报告周期重叠的商家备注，不发送原始订单。服务地址、密钥和连接测试结果保持不变。',
          )}
        </p>
        <ErrorNotice error={error} />
        <button
          type="button"
          className={ui.primary}
          disabled={pending}
          onClick={() => void confirm()}
        >
          {pending && <LoaderCircle size={16} className={ui.spin} />}
          {t('确认新的授权范围')}
        </button>
      </div>
    </div>
  );
}

export function ModelCard({
  item,
  onEdit,
  onRefresh,
}: {
  item: ModelConfig;
  onEdit: () => void;
  onRefresh: () => void;
}) {
  useLanguage();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const busy = pending || item.test_status === 'queued' || item.test_status === 'running';
  async function action(kind: 'test' | 'delete') {
    setPending(true);
    setError('');
    try {
      await api(`/model-configs/${item.id}${kind === 'test' ? '/test' : ''}`, {
        method: kind === 'test' ? 'POST' : 'DELETE',
      });
      onRefresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : t('操作失败。'));
    } finally {
      setPending(false);
    }
  }
  return (
    <article className={cx(ui.panel, css.modelCard)} aria-label={item.name}>
      <div className={css.modelCardTitle}>
        <span className={ui.tileIcon}>
          <Server size={21} />
        </span>
        <div>
          <h2>{item.name}</h2>
          <p>{item.model_name}</p>
        </div>
        {item.is_default && <span className={ui.subtleBadge}>{t('默认模型')}</span>}
      </div>
      <p className={css.modelUrl}>{item.base_url}</p>
      {!item.consent_current && <ConsentUpgrade item={item} onRefresh={onRefresh} />}
      <div className={css.modelMeta}>
        <span>
          <KeyRound size={13} />
          {item.has_api_key ? t('密钥已保存') : t('未设置密钥')}
        </span>
        <span>{t(protocols[item.protocol ?? 'openai_chat'].label)}</span>
        <span>
          {t('版本')} {item.revision}
        </span>
        <span>{item.product_name_mode === 'sku_only' ? t('仅发送 SKU') : t('包含商品名称')}</span>
      </div>
      <div
        className={cx(css.modelResult, item.capabilities?.usable && css.usable)}
        aria-live="polite"
      >
        <strong>
          {busy ? (
            <>
              <LoaderCircle size={15} className={ui.spin} />
              {t('连接测试中…')}
            </>
          ) : item.capabilities ? (
            <>
              {item.capabilities.usable ? <CheckCircle2 size={15} /> : <CircleX size={15} />}
              {t(strategies[item.capabilities.strategy])}
            </>
          ) : item.test_status === 'failed' ? (
            t('测试作业失败，可重新测试')
          ) : (
            t('尚未测试连接')
          )}
        </strong>
        {item.capabilities && (
          <>
            <details className={css.capabilityDetails} open={!item.capabilities.usable}>
              <summary>{t('测试详情')}</summary>
              <div className={css.capabilityList}>
                {Object.entries(item.capabilities.stages).map(([name, result]) => (
                  <div key={name}>
                    <span>{t(stages[name])}</span>
                    <b className={result.ok ? css.passed : css.limited}>
                      {result.ok
                        ? t('通过')
                        : result.code === 'UNSUPPORTED_REQUEST'
                          ? t('不支持')
                          : t('未通过')}
                    </b>
                    {!result.ok && (
                      <p>
                        {message(result.message)}
                        {result.http_status && `（HTTP ${result.http_status}）`}
                      </p>
                    )}
                  </div>
                ))}
              </div>

              <small>
                {t('测试于')}{' '}
                {item.tested_at ? new Date(item.tested_at).toLocaleString(locale()) : '—'} ·{' '}
                {item.capabilities.requests ?? '—'} {t('次请求')}
              </small>
            </details>
          </>
        )}
        {item.test_status === 'failed' && !item.capabilities && (
          <p>
            {item.test_error_code} {t('· 请确认 Worker 正常运行后重试。')}
          </p>
        )}
        {busy && <p>{t('使用合成内容测试，最长约 90 秒。')}</p>}
      </div>
      <p className={cx(ui.formHint, forms.formHint)}>
        {t('点击测试将调用所填服务，可能产生少量模型费用。')}
      </p>
      <ErrorNotice error={error} />
      <div className={cx(ui.formActions, forms.formActions)}>
        <button className={ui.primary} disabled={busy} onClick={() => void action('test')}>
          {t('测试连接')}
        </button>
        <button className={cx(ui.secondary, forms.secondary)} disabled={busy} onClick={onEdit}>
          {t('编辑')}
        </button>
        <button
          className={cx(ui.textButton, forms.textButton)}
          disabled={busy}
          onClick={() => setConfirmDelete(!confirmDelete)}
        >
          {t('删除')}
        </button>
      </div>
      {confirmDelete && (
        <div className={css.deleteConfirm}>
          <p>
            {t('删除「')}
            {item.name}
            {t('」及已保存的密钥？此操作无法撤销。')}
          </p>
          <button
            className={cx(ui.secondary, forms.secondary)}
            disabled={busy}
            onClick={() => void action('delete')}
          >
            {t('确认删除')}
          </button>
          <button
            className={cx(ui.textButton, forms.textButton)}
            onClick={() => setConfirmDelete(false)}
          >
            {t('保留配置')}
          </button>
        </div>
      )}
    </article>
  );
}
