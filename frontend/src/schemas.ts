import { z } from 'zod'

// --- Thing Types ---

export const ThingTypeSchema = z.object({
  id: z.string(),
  name: z.string(),
  icon: z.string(),
  color: z.string().nullable(),
  created_at: z.string(),
})

// --- Things ---

export const ThingSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable(),
  parent_id: z.string().nullable(),
  checkin_date: z.string().nullable(),
  priority: z.number(),
  active: z.boolean(),
  surface: z.boolean(),
  data: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  last_referenced: z.string().nullable(),
  open_questions: z.array(z.string()).nullable(),
  children_count: z.number().nullable(),
  completed_count: z.number().nullable(),
})

// --- Chat ---

export const WebSearchResultSchema = z.object({
  title: z.string(),
  url: z.string(),
  snippet: z.string(),
})

export const ContextThingSchema = z.object({
  id: z.string(),
  title: z.string(),
  type_hint: z.string().nullable().optional(),
})

export const ReferencedThingSchema = z.object({
  mention: z.string(),
  thing_id: z.string(),
})

export const AppliedChangesSchema = z.object({
  created: z.array(z.object({ id: z.string(), title: z.string(), type_hint: z.string().optional() })).optional(),
  updated: z.array(z.object({ id: z.string(), title: z.string() }).catchall(z.unknown())).optional(),
  deleted: z.array(z.string()).optional(),
  context_things: z.array(ContextThingSchema).optional(),
  referenced_things: z.array(ReferencedThingSchema).optional(),
  web_results: z.array(WebSearchResultSchema).optional(),
})

const CallUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  cost_usd: z.number(),
})

export const ChatMessageSchema = z.object({
  id: z.union([z.number(), z.string()]),
  session_id: z.string(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  applied_changes: AppliedChangesSchema.nullable(),
  questions_for_user: z.array(z.string()),
  prompt_tokens: z.number().optional(),
  completion_tokens: z.number().optional(),
  cost_usd: z.number().optional(),
  model: z.string().nullable().optional(),
  per_call_usage: z.array(CallUsageSchema).optional(),
  timestamp: z.string(),
})

export const ChatResponseSchema = z.object({
  reply: z.string(),
  applied_changes: AppliedChangesSchema.nullable().optional(),
  questions_for_user: z.array(z.string()).optional(),
  mode: z.string().optional(),
  usage: z.object({
    prompt_tokens: z.number(),
    completion_tokens: z.number(),
    cost_usd: z.number(),
    model: z.string().nullable(),
    per_call_usage: z.array(CallUsageSchema).optional(),
  }).optional(),
  session_usage: z.object({
    prompt_tokens: z.number(),
    completion_tokens: z.number(),
    total_tokens: z.number(),
    api_calls: z.number(),
    cost_usd: z.number(),
    per_model: z.array(z.object({
      model: z.string(),
      prompt_tokens: z.number(),
      completion_tokens: z.number(),
      total_tokens: z.number(),
      api_calls: z.number(),
      cost_usd: z.number(),
    })),
  }).optional(),
})

// --- Briefing ---

export const SweepFindingSchema = z.object({
  id: z.string(),
  thing_id: z.string().nullable(),
  finding_type: z.string(),
  message: z.string(),
  priority: z.number(),
  dismissed: z.boolean(),
  created_at: z.string(),
  expires_at: z.string().nullable(),
  snoozed_until: z.string().nullable(),
  thing: ThingSchema.nullable(),
})

export const BriefingResponseSchema = z.object({
  things: z.array(ThingSchema).optional(),
  findings: z.array(SweepFindingSchema).optional(),
})

// --- Morning Briefing ---

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
  include_priorities: z.boolean(),
  include_overdue: z.boolean(),
  include_blockers: z.boolean(),
  include_findings: z.boolean(),
  max_priorities: z.number(),
  max_findings: z.number(),
})

// --- Proactive Surfaces ---

export const ProactiveSurfaceSchema = z.object({
  thing: ThingSchema,
  reason: z.string(),
  date_key: z.string(),
  days_away: z.number(),
})

// --- Conflict Alerts ---

export const ConflictAlertSchema = z.object({
  alert_type: z.string(),
  severity: z.string(),
  message: z.string(),
  thing_ids: z.array(z.string()),
  thing_titles: z.array(z.string()),
})

// --- Calendar ---

export const CalendarEventSchema = z.object({
  id: z.string(),
  summary: z.string(),
  start: z.string(),
  end: z.string(),
  all_day: z.boolean(),
  location: z.string().nullable(),
  status: z.string(),
})

export const CalendarStatusSchema = z.object({
  configured: z.boolean(),
  connected: z.boolean(),
})

// --- Session Stats ---

export const ModelUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number(),
  api_calls: z.number(),
  cost_usd: z.number(),
})

export const SessionStatsSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number(),
  api_calls: z.number(),
  cost_usd: z.number(),
  per_model: z.array(ModelUsageSchema),
})

// --- Health ---

export const HealthResponseSchema = z.object({
  status: z.string(),
})

// --- Relationships ---

export const RelationshipSchema = z.object({
  id: z.string(),
  from_thing_id: z.string(),
  to_thing_id: z.string(),
  relationship_type: z.string(),
  metadata: z.record(z.string(), z.unknown()).nullable(),
  created_at: z.string(),
})

// --- Auth ---

export const AuthUserSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  picture: z.string().nullable(),
})

// --- Settings ---

export const ModelSettingsSchema = z.object({
  context: z.string(),
  reasoning: z.string(),
  response: z.string(),
  chat_context_window: z.number(),
})

export const UserSettingsSchema = z.object({
  requesty_api_key: z.string(),
  openai_api_key: z.string(),
  embedding_model: z.string(),
  context_model: z.string(),
  reasoning_model: z.string(),
  response_model: z.string(),
  chat_context_window: z.number().nullable(),
  theme: z.string(),
  chat_mode: z.string().optional().default('normal'),
  stale_threshold_days: z.number().default(14),
  proactivity_level: z.string().default('medium'),
  interaction_style: z.string().optional().default('auto'),
})

export const RequestyModelSchema = z.object({
  id: z.string(),
  name: z.string().nullable(),
  input_cost_per_million: z.number().nullable().optional(),
  output_cost_per_million: z.number().nullable().optional(),
})

// --- User Profile ---

export const UserProfileRelationshipSchema = z.object({
  id: z.string(),
  relationship_type: z.string(),
  direction: z.enum(['outgoing', 'incoming']),
  related_thing_id: z.string(),
  related_thing_title: z.string(),
})

export const UserProfileSchema = z.object({
  thing: ThingSchema,
  relationships: z.array(UserProfileRelationshipSchema),
})

// --- Focus Recommendations ---

export const FocusRecommendationSchema = z.object({
  thing: ThingSchema,
  score: z.number(),
  reasons: z.array(z.string()),
  is_blocked: z.boolean(),
})

export const FocusResponseSchema = z.object({
  recommendations: z.array(FocusRecommendationSchema),
  total: z.number(),
  calendar_active: z.boolean(),
})

// --- Merge Suggestions ---

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

// --- Connection Suggestions ---

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

// --- Nudges ---

export const NudgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  source_id: z.string(),
  message: z.string(),
  action_label: z.string().nullable(),
  action_url: z.string().nullable(),
  thing_id: z.string().nullable(),
  dismissed: z.boolean(),
  created_at: z.string(),
})

// --- Weekly Digest ---

export const WeeklyDigestContentSchema = z.object({
  week_start: z.string(),
  things_completed: z.array(z.object({ id: z.string(), title: z.string(), type: z.string() })),
  new_connections: z.array(z.object({ from: z.string(), to: z.string(), relationship: z.string() })),
  preferences_learned: z.array(z.object({ pattern: z.string(), confidence: z.string() })),
  upcoming_deadlines: z.array(z.object({ id: z.string(), title: z.string(), type: z.string() })),
  open_questions: z.array(z.string()),
  summary: z.string(),
})

export const WeeklyDigestSchema = z.object({
  id: z.string(),
  week_start: z.string(),
  content: WeeklyDigestContentSchema,
  generated_at: z.string(),
})

// --- Validation helper ---

/**
 * Validates data against a Zod schema. Logs a warning on mismatch but
 * always returns the original data so the app never crashes from validation.
 */
export function validateResponse<T>(schema: z.ZodType<T>, data: unknown, endpoint: string): T {
  const result = schema.safeParse(data)
  if (!result.success) {
    console.warn(
      `[API Validation] Response from ${endpoint} does not match expected schema:`,
      result.error.issues,
    )
  }
  return data as T
}
