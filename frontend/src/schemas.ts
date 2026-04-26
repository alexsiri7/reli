import { z } from 'zod'

// ── Re-exported from generated (auto-generated from Pydantic models) ──────────
export {
  ThingTypeSchema,
  ThingSchema,
  RelationshipSchema,
  SweepFindingSchema,
  MorningBriefingItemSchema,
  MorningBriefingFindingSchema,
  MorningBriefingContentSchema,
  MorningBriefingSchema,
  BriefingPreferencesSchema,
  ProactiveSurfaceSchema,
  ConflictAlertSchema,
  ModelSettingsSchema,
  UserSettingsSchema,
  RequestyModelSchema,
  FocusRecommendationSchema,
  FocusResponseSchema,
  MergeSuggestionThingSchema,
  MergeSuggestionSchema,
  MergeResultSchema,
  ConnectionSuggestionThingSchema,
  ConnectionSuggestionSchema,
  LearnedPreferenceSchema,
  ModelUsageSchema,
} from './generated/api-types'

import {
  ThingSchema,
  SweepFindingSchema as GeneratedSweepFindingSchema,
  LearnedPreferenceSchema as GeneratedLearnedPreferenceSchema,
  ModelUsageSchema,
} from './generated/api-types'

// ── Frontend-only schemas (not derived from Pydantic models) ──────────────────

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
  created: z.array(z.object({ id: z.string(), title: z.string(), type_hint: z.string().optional() }).catchall(z.unknown())).optional(),
  updated: z.array(z.object({ id: z.string(), title: z.string() }).catchall(z.unknown())).optional(),
  deleted: z.array(z.string()).optional(),
  context_things: z.array(ContextThingSchema).optional(),
  referenced_things: z.array(ReferencedThingSchema).optional(),
  web_results: z.array(WebSearchResultSchema).optional(),
})

// ChatMessage uses frontend-specific fields (streaming, id union) not in backend
const CallUsageSchema = z.object({
  model: z.string(),
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  cost_usd: z.number(),
})

export const ChatMessageSchema = z.object({
  id: z.union([z.number(), z.string()]),
  session_id: z.string(),
  role: z.enum(['user', 'assistant', 'system']),
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

// BriefingItem.thing uses ThingSchema for stricter validation than backend's dict[str, Any]
export const BriefingItemSchema = z.object({
  thing: ThingSchema,
  importance: z.number(),
  urgency: z.number(),
  score: z.number(),
  reasons: z.array(z.string()),
})

export const BriefingResponseSchema = z.object({
  the_one_thing: BriefingItemSchema.nullable().optional(),
  secondary: z.array(BriefingItemSchema).optional(),
  parking_lot: z.array(z.record(z.string(), z.unknown())).optional(),
  findings: z.array(GeneratedSweepFindingSchema).optional(),
  learned_preferences: z.array(GeneratedLearnedPreferenceSchema).optional(),
  total: z.number().optional(),
  stats: z.record(z.string(), z.number()).optional(),
})

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

export const GmailStatusSchema = z.object({
  connected: z.boolean(),
  email: z.string().nullable(),
})

export const SessionStatsSchema = z.object({
  prompt_tokens: z.number(),
  completion_tokens: z.number(),
  total_tokens: z.number(),
  api_calls: z.number(),
  cost_usd: z.number(),
  per_model: z.array(ModelUsageSchema),
})

export const HealthResponseSchema = z.object({
  status: z.string(),
})

export const AuthUserSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  picture: z.string().nullable(),
})

// UserProfileRelationship uses z.enum for stricter direction validation
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
