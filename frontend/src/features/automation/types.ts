import type { Refine, Schema } from '../../lib/types';

export type Evaluation = {
  state: string;
  reason: string | null;
  change_rate: string | null;
  report_id: string;
};
/** A recommended action of `/reports/{id}/actions`; `/actions` adds the report title. */
export type ActionItem = Refine<Schema<'ActionItem'>, { evaluation: Evaluation | null }> & {
  report_title?: string | null;
};
export type Schedule = Schema<'Schedule'>;
export type Note = Schema<'Note'>;
