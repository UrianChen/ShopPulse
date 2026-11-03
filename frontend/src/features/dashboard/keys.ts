import { keys } from '../../lib/queries';
import type { ProductOrder } from './types';

// Dashboard-only refinements of the shared keys, so shared invalidations still reach them.
export const dashboardKeys = {
  skuOptions: (datasetId: string, search: string) =>
    [...keys.datasetSkus(datasetId), search] as const,
  products: (snapshotId: string, offset: number, order: ProductOrder) =>
    [...keys.metricProducts(snapshotId, offset), order.sort, order.direction, order.focus] as const,
};
