export interface DatasetField {
  field_name: string;
  field_type: string;
  field_role: '输入特征' | '分类标签';
  description: string;
  sample_value: string;
  nullable: boolean;
  enum_values?: string[];
}

export interface Dataset {
  dataset_id: string;
  name: string;
  file_name?: string;
  description: string;
  record_count: number;
  field_count: number;
  fields: DatasetField[];
  created_at: string;
  data_format: 'csv' | 'arff' | 'json';
  dataset_version: string;
  enabled: boolean;
  referenced: boolean;
  change_type?: string | null;
  change_type_label?: string | null;
  is_breaking?: boolean;
  base_version_id?: number | null;
  label_field?: string;
}

export interface DatasetVersion {
  dataset_version_id: string;
  dataset_id: string;
  dataset_version: string;
  name: string;
  data_format: Dataset['data_format'];
  file_path: string;
  record_count: number;
  field_count: number;
  fields: DatasetField[];
  uploaded_at: string;
  enabled: boolean;
  referenced: boolean;
  change_type?: string | null;
  change_type_label?: string | null;
  is_breaking?: boolean;
  base_version_id?: number | null;
}

export interface DataPreview {
  total: number;
  page: number;
  page_size: number;
  rows: Array<Record<string, string | number>>;
  label_field: string;
}

export type ModelStatus = 'TRAINING' | 'FAILED' | 'COMPLETED';

export interface EvaluationMetrics {
  accuracy?: number | null;
  recall?: number | null;
  precision?: number | null;
  specificity?: number | null;
  f1?: number | null;
  g_mean?: number | null;
  risk_recall?: number | null;
  risk_f1?: number | null;
  cv_mean?: number | null;
  cv_std?: number | null;
  quality_availability?: Record<string, { available: boolean; reason: string | null }>;
}

export interface AlgorithmParamDef {
  param_name: string;
  label: string;
  type: 'number' | 'select' | 'string' | 'boolean';
  default_value: string | number | boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ value: string; label: string }>;
  description?: string;
  requires_numeric_features?: boolean;
}

export interface AlgorithmDefinition {
  id: number;
  code: string;
  display_name: string;
  description?: string;
  status: string;
  param_schema?: unknown[];
}
