// Shared API types, generated from the backend's OpenAPI document (`npm run api:types`): request
// bodies from its Pydantic input models, responses from its response models. Free-form JSON
// fields (frozen snapshots, report content, capabilities) are typed `{ [key: string]: unknown }`
// there; `Refine` replaces them with the shapes the pages read.
import type { components } from './schema';

type Schemas = components['schemas'];
/** A request body or response model of the API, generated from the backend's Pydantic models. */
export type Schema<Name extends keyof Schemas> = Schemas[Name];
/** Request body of an API endpoint. */
export type Body<Name extends keyof Schemas> = Schemas[Name];
/** A generated model with some (free-form) fields replaced by hand-written shapes. */
export type Refine<T, Fields> = Omit<T, keyof Fields> & Fields;

export type ReportInput = Body<'ReportInput'>;
export type ModelInput = Body<'ModelInput'>;
export type ModelPatch = Body<'ModelPatch'>;
export type MetricQuery = Body<'MetricQuery'>;
export type NoteInput = Body<'NoteInput'>;
export type ScheduleInput = Body<'ScheduleInput'>;
export type QuestionInput = Body<'QuestionInput'>;

export type Workspace = Schema<'Workspace'>;

/** The frozen import configuration of a published version, as far as several pages read it. */
export type VersionSnapshot = {
  config: { options: { coverage_start: string; coverage_end_exclusive: string } };
  file_sha256?: string;
  engine_version?: string;
};

/** A published order or cost version as listed by `/datasets` and `/cost-versions`. */
export type DatasetVersion = Refine<Schema<'DatasetVersion'>, { snapshot: VersionSnapshot }>;

export type Protocol = Schema<'ModelConfig'>['protocol'];

export type ModelStage = { ok: boolean; code: string; message: string; http_status?: number };

export type ModelCapabilities = {
  usable: boolean;
  strategy: string;
  stages: Record<string, ModelStage>;
  requests?: number;
  protocol?: string;
};

/** A model configuration as returned by `/model-configs`. */
export type ModelConfig = Refine<Schema<'ModelConfig'>, { capabilities: ModelCapabilities | null }>;

export type Paged<T> = { total: number; items: T[] };
