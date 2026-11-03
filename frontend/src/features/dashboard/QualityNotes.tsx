import { Info } from 'lucide-react';
import { t, useLanguage } from '../../lib/i18n';
import css from './dashboard.module.css';

const warnings: Record<string, string> = {
  INCOMPLETE_COVERAGE:
    '本期超出源文件确认的完整覆盖范围。当前仅显示已提供记录，不能视为完整周期经营数据。',
  COMPARISON_INCOMPLETE: '比较期覆盖不完整，已禁用增长率与贡献分解。',
  COST_MISSING: '存在成本缺失，整体商品毛利不可用；下方单独显示匹配子集。',
  RESTOCK_ESTIMATED: '部分回库数量未知，按不回转成本计算，毛利标记为估算。',
  REFUND_UNKNOWN: '累计退款未知，净销售额、净客单价和毛利不可用。',
  REFUND_ALLOCATED: '订单退款按明细实付分摊，商品相关净值标记为估算。',
  SMALL_SAMPLE: '本期订单少于 20 笔。可查看实际比例，不据此给出显著变化结论。',
};

export function QualityNotes({ codes }: { codes: string[] }) {
  useLanguage();
  return (
    <aside className={css.qualityNotes} aria-label={t('数据质量提示')}>
      <Info size={18} />
      <div>
        {codes.map(code => (
          <p key={code}>{t(warnings[code] ?? code)}</p>
        ))}
      </div>
    </aside>
  );
}
