import { t } from '../../lib/i18n';
import type { ModelConfig, Protocol } from '../../lib/types';

export const strategies: Record<string, string> = {
  native_tools: '原生工具调用',
  restricted_json: '受限 JSON 模式',
  narrative: '固定流程叙述',
  unavailable: '连接不可用',
};
export const stages: Record<string, string> = {
  basic: '基础连接',
  tools: '工具调用与回传',
  json: 'JSON 模式',
  json_schema: '结构化输出（JSON Schema）',
  text_json: '文本 JSON 校验',
  review: '审稿模型',
};
export const protocols: Record<Protocol, { label: string; hint: string; placeholder: string }> = {
  openai_chat: {
    label: 'OpenAI 兼容 · Chat Completions',
    hint: '填写 API 前缀（如 /v1），无需添加 /chat/completions。',
    placeholder: 'https://provider.example/v1',
  },
  openai_responses: {
    label: 'OpenAI Responses',
    hint: '填写 API 前缀（如 /v1），无需添加 /responses。',
    placeholder: 'https://api.openai.com/v1',
  },
  anthropic_messages: {
    label: 'Anthropic Messages',
    hint: '填写 API 前缀（如 /v1），无需添加 /messages；连接测试会探测工具调用和结构化输出。',
    placeholder: 'https://api.anthropic.com/v1',
  },
};

/** Editable fields of a model configuration; the API key is kept out of this on purpose. */
export type ModelForm = Pick<
  ModelConfig,
  | 'name'
  | 'base_url'
  | 'model_name'
  | 'protocol'
  | 'timeout_seconds'
  | 'is_default'
  | 'product_name_mode'
  | 'token_limit_parameter'
> & { review_model_name: string };

export const empty: ModelForm = {
  name: '',
  base_url: '',
  model_name: '',
  review_model_name: '',
  protocol: 'openai_chat',
  timeout_seconds: 120,
  is_default: false,
  product_name_mode: 'sku_only',
  token_limit_parameter: 'none',
};

export function originOf(value: string) {
  try {
    return new URL(value).origin;
  } catch {
    return t('填写 API 根地址后显示');
  }
}
