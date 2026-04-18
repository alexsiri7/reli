/**
 * AUTO-GENERATED — DO NOT EDIT
 *
 * Generated from Pydantic models via OpenAPI schema.
 * Run `npm run generate:types` to regenerate.
 *
 * Source: backend/models.py, backend/routers/*.py
 */

import { z } from 'zod'

// ═══════════════════════════════════════════════════════════════════════
// TypeScript Interfaces
// ═══════════════════════════════════════════════════════════════════════

export interface ThingType {
  id: string
  name: string
  icon: string
  color: string | null
  created_at: string
}

export interface Thing {
  id: string
  title: string
  type_hint: string | null
  checkin_date: string | null
  importance: number
  active: boolean
  surface: boolean
  data: Record<string, unknown> | null
  created_at: string
  updated_at: string
  last_referenced: string | null
  open_questions: string[] | null
  children_count: number | null
  completed_count: number | null
  parent_ids: string[] | null
}

export interface GraphNode {
  id: string
  title: string
  type_hint: string | null
  icon: string | null
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  relationship_type: string
}

export interface GraphResponse {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface Relationship {
  id: string
  from_thing_id: string
  to_thing_id: string
  relationship_type: string
  metadata: Record<string, unknown> | null
  created_at: string
}

export interface CallUsage {
  model: string
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
}

export interface ChatMessage {
  id: number
  session_id: string
  role: string
  content: string
  applied_changes: Record<string, unknown> | null
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  model: string | null
  per_call_usage: CallUsage[]
  timestamp: string
}

export interface UsageInfo {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  api_calls: number
  model: string
  per_call_usage: CallUsage[]
}

export interface ModelUsage {
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
  cost_usd: number
}

export interface SessionUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  api_calls: number
  cost_usd: number
  per_model: ModelUsage[]
}

export interface ChatResponse {
  session_id: string
  reply: string
  applied_changes: Record<string, unknown>
  questions_for_user: string[]
  mode: string
  usage: UsageInfo | null
  session_usage: SessionUsage | null
}

export interface SweepFinding {
  id: string
  thing_id: string | null
  finding_type: string
  message: string
  priority: number
  dismissed: boolean
  created_at: string
  expires_at: string | null
  snoozed_until: string | null
  thing: Thing | null
}

export interface LearnedPreference {
  id: string
  title: string
  confidence_label: string
}

export interface BriefingItem {
  thing: Record<string, unknown>
  importance: number
  urgency: number
  score: number
  reasons: string[]
}

export interface BriefingResponse {
  date: string
  the_one_thing: BriefingItem | null
  secondary: BriefingItem[]
  parking_lot: Record<string, unknown>[]
  findings: SweepFinding[]
  learned_preferences: LearnedPreference[]
  total: number
  stats: Record<string, number>
}

export interface StaleItem {
  thing: Thing
  days_stale: number
  is_neglected: boolean
  active_children: number
}

export interface OverdueCheckin {
  thing: Thing
  days_overdue: number
}

export interface StalenessCategory {
  stale: number
  neglected: number
  overdue_checkins: number
}

export interface StalenessReport {
  as_of: string
  stale_threshold_days: number
  stale_items: StaleItem[]
  overdue_checkins: OverdueCheckin[]
  counts: StalenessCategory
  total: number
}

export interface MorningBriefingItem {
  thing_id: string
  title: string
  score: number | null
  reasons: string[]
  days_overdue: number | null
  blocked_by: string[]
}

export interface MorningBriefingFinding {
  id: string
  message: string
  priority: number
  thing_id: string | null
  thing_title: string | null
}

export interface MorningBriefingContent {
  summary: string
  priorities: MorningBriefingItem[]
  overdue: MorningBriefingItem[]
  blockers: MorningBriefingItem[]
  findings: MorningBriefingFinding[]
  stats: Record<string, number>
}

export interface MorningBriefing {
  id: string
  briefing_date: string
  content: MorningBriefingContent
  generated_at: string
}

export interface BriefingPreferences {
  include_priorities: boolean
  include_overdue: boolean
  include_blockers: boolean
  include_findings: boolean
  max_priorities: number
  max_findings: number
}

export interface Nudge {
  id: string
  nudge_type: string
  message: string
  thing_id: string | null
  thing_title: string | null
  thing_type_hint: string | null
  days_away: number | null
  primary_action_label: string | null
}

export interface WeeklyBriefingItem {
  thing_id: string
  title: string
  type_hint: string | null
  detail: string | null
}

export interface WeeklyBriefingConnection {
  from_title: string
  to_title: string
  relationship_type: string
}

export interface WeeklyBriefingContent {
  summary: string
  week_start: string
  week_end: string
  completed: WeeklyBriefingItem[]
  upcoming: WeeklyBriefingItem[]
  new_connections: WeeklyBriefingConnection[]
  preferences_learned: string[]
  open_questions: WeeklyBriefingItem[]
  stats: Record<string, number>
}

export interface WeeklyBriefing {
  id: string
  week_start: string
  content: WeeklyBriefingContent
  generated_at: string
}

export interface ProactiveSurface {
  thing: Thing
  reason: string
  date_key: string
  days_away: number
}

export interface FocusRecommendation {
  thing: Thing
  score: number
  reasons: string[]
  is_blocked: boolean
}

export interface FocusResponse {
  recommendations: FocusRecommendation[]
  total: number
  calendar_active: boolean
}

export interface ConflictAlert {
  alert_type: string
  severity: string
  message: string
  thing_ids: string[]
  thing_titles: string[]
}

export interface MergeSuggestionThing {
  id: string
  title: string
  type_hint: string | null
}

export interface MergeSuggestion {
  thing_a: MergeSuggestionThing
  thing_b: MergeSuggestionThing
  reason: string
}

export interface MergeResult {
  keep_id: string
  remove_id: string
  keep_title: string
  remove_title: string
}

export interface ConnectionSuggestionThing {
  id: string
  title: string
  type_hint: string | null
}

export interface ConnectionSuggestion {
  id: string
  from_thing: ConnectionSuggestionThing
  to_thing: ConnectionSuggestionThing
  suggested_relationship_type: string
  reason: string
  confidence: number
  status: string
  created_at: string
}

export interface ModelSettings {
  context: string
  reasoning: string
  response: string
  chat_context_window: number
}

export interface UserSettings {
  requesty_api_key: string
  openai_api_key: string
  embedding_model: string
  context_model: string
  reasoning_model: string
  response_model: string
  chat_context_window: number | null
  theme: string
  chat_mode: string
  stale_threshold_days: number
  proactivity_level: string
  interaction_style: string
}

export interface RequestyModel {
  id: string
  name: string | null
  input_cost_per_million: number | null
  output_cost_per_million: number | null
}

export interface UserProfileRelationship {
  id: string
  relationship_type: string
  direction: string
  related_thing_id: string
  related_thing_title: string
}

export interface UserProfile {
  thing: Thing
  relationships: UserProfileRelationship[]
}


// ═══════════════════════════════════════════════════════════════════════
// Zod Validation Schemas
// ═══════════════════════════════════════════════════════════════════════

export const ThingTypeSchema = z.object({
  id: z.string(),
  name: z.string(),
  icon: z.string(),
  color: z.string().nullable(),
  created_at: z.string(),
})

export const ThingSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable(),
  checkin_date: z.string().nullable(),
  importance: z.number(),
  active: z.boolean(),
  surface: z.boolean(),
  data: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  last_referenced: z.string().nullable().default(null),
  open_questions: z.array(z.string()).nullable().default(null),
  children_count: z.number().nullable().default(null),
  completed_count: z.number().nullable().default(null),
  parent_ids: z.array(z.string()).nullable().default(null),
})

export const GraphNodeSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable(),
  icon: z.string().nullable(),
})

export const GraphEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  relationship_type: z.string(),
})

export const GraphResponseSchema = z.object({
  nodes: z.array(GraphNodeSchema),
  edges: z.array(GraphEdgeSchema),
})

export const RelationshipSchema = z.object({
  id: z.string(),
  from_thing_id: z.string(),
  to_thing_id: z.string(),
  relationship_type: z.string(),
  metadata: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
})

export const CallUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number().default(0),
  completion_tokens: z.number().default(0),
  cost_usd: z.number().default(0.0),
})

export const ChatMessageSchema = z.object({
  id: z.number(),
  session_id: z.string(),
  role: z.string(),
  content: z.string(),
  applied_changes: z.record(z.string(), z.unknown()).nullable(),
  prompt_tokens: z.number().default(0),
  completion_tokens: z.number().default(0),
  cost_usd: z.number().default(0.0),
  model: z.string().nullable().default(null),
  per_call_usage: z.array(CallUsageSchema).default([]),
  timestamp: z.string(),
})

export const UsageInfoSchema = z.object({
  prompt_tokens: z.number().default(0),
  completion_tokens: z.number().default(0),
  total_tokens: z.number().default(0),
  cost_usd: z.number().default(0.0),
  api_calls: z.number().default(0),
  model: z.string().default(""),
  per_call_usage: z.array(CallUsageSchema).default([]),
})

export const ModelUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number().default(0),
  completion_tokens: z.number().default(0),
  total_tokens: z.number().default(0),
  api_calls: z.number().default(0),
  cost_usd: z.number().default(0.0),
})

export const SessionUsageSchema = z.object({
  prompt_tokens: z.number().default(0),
  completion_tokens: z.number().default(0),
  total_tokens: z.number().default(0),
  api_calls: z.number().default(0),
  cost_usd: z.number().default(0.0),
  per_model: z.array(ModelUsageSchema).default([]),
})

export const ChatResponseSchema = z.object({
  session_id: z.string(),
  reply: z.string(),
  applied_changes: z.record(z.string(), z.unknown()),
  questions_for_user: z.array(z.string()),
  mode: z.string().default("normal"),
  usage: UsageInfoSchema.nullable().default(null),
  session_usage: SessionUsageSchema.nullable().default(null),
})

export const SweepFindingSchema = z.object({
  id: z.string(),
  thing_id: z.string().nullable(),
  finding_type: z.string(),
  message: z.string(),
  priority: z.number(),
  dismissed: z.boolean(),
  created_at: z.string(),
  expires_at: z.string().nullable(),
  snoozed_until: z.string().nullable().default(null),
  thing: ThingSchema.nullable().default(null),
})

export const LearnedPreferenceSchema = z.object({
  id: z.string(),
  title: z.string(),
  confidence_label: z.string(),
})

export const BriefingItemSchema = z.object({
  thing: z.record(z.string(), z.unknown()),
  importance: z.number(),
  urgency: z.number(),
  score: z.number(),
  reasons: z.array(z.string()),
})

export const BriefingResponseSchema = z.object({
  date: z.string(),
  the_one_thing: BriefingItemSchema.nullable().default(null),
  secondary: z.array(BriefingItemSchema).default([]),
  parking_lot: z.array(z.record(z.string(), z.unknown())).default([]),
  findings: z.array(SweepFindingSchema).default([]),
  learned_preferences: z.array(LearnedPreferenceSchema).default([]),
  total: z.number(),
  stats: z.record(z.string(), z.number()).default({}),
})

export const StaleItemSchema = z.object({
  thing: ThingSchema,
  days_stale: z.number(),
  is_neglected: z.boolean(),
  active_children: z.number().default(0),
})

export const OverdueCheckinSchema = z.object({
  thing: ThingSchema,
  days_overdue: z.number(),
})

export const StalenessCategorySchema = z.object({
  stale: z.number().default(0),
  neglected: z.number().default(0),
  overdue_checkins: z.number().default(0),
})

export const StalenessReportSchema = z.object({
  as_of: z.string(),
  stale_threshold_days: z.number(),
  stale_items: z.array(StaleItemSchema),
  overdue_checkins: z.array(OverdueCheckinSchema),
  counts: StalenessCategorySchema,
  total: z.number(),
})

export const MorningBriefingItemSchema = z.object({
  thing_id: z.string(),
  title: z.string(),
  score: z.number().nullable().default(null),
  reasons: z.array(z.string()).default([]),
  days_overdue: z.number().nullable().default(null),
  blocked_by: z.array(z.string()).default([]),
})

export const MorningBriefingFindingSchema = z.object({
  id: z.string(),
  message: z.string(),
  priority: z.number(),
  thing_id: z.string().nullable().default(null),
  thing_title: z.string().nullable().default(null),
})

export const MorningBriefingContentSchema = z.object({
  summary: z.string(),
  priorities: z.array(MorningBriefingItemSchema).default([]),
  overdue: z.array(MorningBriefingItemSchema).default([]),
  blockers: z.array(MorningBriefingItemSchema).default([]),
  findings: z.array(MorningBriefingFindingSchema).default([]),
  stats: z.record(z.string(), z.number()).default({}),
})

export const MorningBriefingSchema = z.object({
  id: z.string(),
  briefing_date: z.string(),
  content: MorningBriefingContentSchema,
  generated_at: z.string(),
})

export const BriefingPreferencesSchema = z.object({
  include_priorities: z.boolean().default(true),
  include_overdue: z.boolean().default(true),
  include_blockers: z.boolean().default(true),
  include_findings: z.boolean().default(true),
  max_priorities: z.number().default(5),
  max_findings: z.number().default(10),
})

export const NudgeSchema = z.object({
  id: z.string(),
  nudge_type: z.string(),
  message: z.string(),
  thing_id: z.string().nullable().nullable().default(null),
  thing_title: z.string().nullable().nullable().default(null),
  thing_type_hint: z.string().nullable().nullable().default(null),
  days_away: z.number().nullable().nullable().default(null),
  primary_action_label: z.string().nullable().nullable().default(null),
})

export const WeeklyBriefingItemSchema = z.object({
  thing_id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable().default(null),
  detail: z.string().nullable().default(null),
})

export const WeeklyBriefingConnectionSchema = z.object({
  from_title: z.string(),
  to_title: z.string(),
  relationship_type: z.string(),
})

export const WeeklyBriefingContentSchema = z.object({
  summary: z.string(),
  week_start: z.string(),
  week_end: z.string(),
  completed: z.array(WeeklyBriefingItemSchema).default([]),
  upcoming: z.array(WeeklyBriefingItemSchema).default([]),
  new_connections: z.array(WeeklyBriefingConnectionSchema).default([]),
  preferences_learned: z.array(z.string()).default([]),
  open_questions: z.array(WeeklyBriefingItemSchema).default([]),
  stats: z.record(z.string(), z.number()).default({}),
})

export const WeeklyBriefingSchema = z.object({
  id: z.string(),
  week_start: z.string(),
  content: WeeklyBriefingContentSchema,
  generated_at: z.string(),
})

export const ProactiveSurfaceSchema = z.object({
  thing: ThingSchema,
  reason: z.string(),
  date_key: z.string(),
  days_away: z.number(),
})

export const FocusRecommendationSchema = z.object({
  thing: ThingSchema,
  score: z.number(),
  reasons: z.array(z.string()),
  is_blocked: z.boolean().default(false),
})

export const FocusResponseSchema = z.object({
  recommendations: z.array(FocusRecommendationSchema),
  total: z.number(),
  calendar_active: z.boolean().default(false),
})

export const ConflictAlertSchema = z.object({
  alert_type: z.string(),
  severity: z.string(),
  message: z.string(),
  thing_ids: z.array(z.string()),
  thing_titles: z.array(z.string()),
})

export const MergeSuggestionThingSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable(),
})

export const MergeSuggestionSchema = z.object({
  thing_a: MergeSuggestionThingSchema,
  thing_b: MergeSuggestionThingSchema,
  reason: z.string(),
})

export const MergeResultSchema = z.object({
  keep_id: z.string(),
  remove_id: z.string(),
  keep_title: z.string(),
  remove_title: z.string(),
})

export const ConnectionSuggestionThingSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable(),
})

export const ConnectionSuggestionSchema = z.object({
  id: z.string(),
  from_thing: ConnectionSuggestionThingSchema,
  to_thing: ConnectionSuggestionThingSchema,
  suggested_relationship_type: z.string(),
  reason: z.string(),
  confidence: z.number(),
  status: z.string(),
  created_at: z.string(),
})

export const ModelSettingsSchema = z.object({
  context: z.string(),
  reasoning: z.string(),
  response: z.string(),
  chat_context_window: z.number().default(3),
})

export const UserSettingsSchema = z.object({
  requesty_api_key: z.string().default(""),
  openai_api_key: z.string().default(""),
  embedding_model: z.string().default(""),
  context_model: z.string().default(""),
  reasoning_model: z.string().default(""),
  response_model: z.string().default(""),
  chat_context_window: z.number().nullable().default(null),
  theme: z.string().default(""),
  chat_mode: z.string().default("normal"),
  stale_threshold_days: z.number().default(14),
  proactivity_level: z.string().default("medium"),
  interaction_style: z.string().default("auto"),
})

export const RequestyModelSchema = z.object({
  id: z.string(),
  name: z.string().nullable().default(null),
  input_cost_per_million: z.number().nullable().default(null),
  output_cost_per_million: z.number().nullable().default(null),
})

export const UserProfileRelationshipSchema = z.object({
  id: z.string(),
  relationship_type: z.string(),
  direction: z.string(),
  related_thing_id: z.string(),
  related_thing_title: z.string(),
})

export const UserProfileSchema = z.object({
  thing: ThingSchema,
  relationships: z.array(UserProfileRelationshipSchema),
})
