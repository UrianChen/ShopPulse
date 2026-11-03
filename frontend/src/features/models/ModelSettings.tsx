import { t, useLanguage, message } from '../../lib/i18n';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Sparkles } from 'lucide-react';
import { api } from '../../lib/api';
import { anyActive, keys, POLL } from '../../lib/queries';
import type { ModelConfig } from '../../lib/types';
import { ConfigForm } from './ConfigForm';
import { ModelCard } from './ModelCard';
import { cx } from '../../lib/cx';
import ui from '../../components/ui.module.css';
import forms from '../../components/forms.module.css';
import css from './models.module.css';
import '../../styles/tables.css';

export function ModelSettings() {
  useLanguage();
  const client = useQueryClient();
  const [editing, setEditing] = useState<ModelConfig | 'new' | null>(null);
  const configs = useQuery({
    queryKey: keys.modelConfigs,
    queryFn: () => api<ModelConfig[]>('/model-configs'),
    // Not pollWhile: without data (first load, error) this page should not poll.
    refetchInterval: query =>
      anyActive(query.state.data, item => item.test_status) ? POLL.fast : false,
  });
  function refresh() {
    void client.invalidateQueries({ queryKey: keys.modelConfigs });
  }
  return (
    <div>
      <section className={cx(ui.pageHeading, 'page-heading')}>
        <div>
          <h1>{t('模型设置')}</h1>
          <p>{t('连接 OpenAI 兼容、OpenAI Responses 或 Anthropic Messages 模型服务。')}</p>
        </div>
        <button className={ui.primary} disabled={!!editing} onClick={() => setEditing('new')}>
          <Plus size={16} />
          {t('添加模型')}
        </button>
      </section>

      {!!configs.data?.some(item => !item.consent_current) && (
        <div className={cx(ui.reportWarning, 'report-warning')} role="status">
          {t(
            '有 {0} 个模型配置仍使用 1.x 的授权范围，确认后追问与商家备注才会发送给模型。',
            configs.data.filter(item => !item.consent_current).length,
          )}
        </div>
      )}
      {configs.error && (
        <div role="alert" className={ui.errorNotice}>
          {message(configs.error.message)}
          <button className={cx(ui.textButton, forms.textButton)} onClick={refresh}>
            {t('重新加载')}
          </button>
        </div>
      )}
      {editing && (
        <ConfigForm
          key={editing === 'new' ? 'new' : editing.id}
          item={editing === 'new' ? undefined : editing}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {configs.isPending && (
        <p className={cx(ui.emptyCopy, forms.emptyCopy)}>{t('正在读取配置…')}</p>
      )}
      {!editing && configs.data?.length === 0 && (
        <section className={cx(ui.panel, css.modelEmpty)}>
          <Sparkles size={34} />
          <h2>{t('添加分析模型')}</h2>
          <p>{t('支持 OpenAI 兼容、OpenAI Responses 与 Anthropic Messages 接口。')}</p>
          <button className={ui.primary} onClick={() => setEditing('new')}>
            {t('添加第一个模型')}
          </button>
        </section>
      )}
      <div className={css.modelsGrid}>
        {configs.data?.map(item => (
          <ModelCard
            key={item.id}
            item={item}
            onEdit={() => setEditing(item)}
            onRefresh={refresh}
          />
        ))}
      </div>
    </div>
  );
}
