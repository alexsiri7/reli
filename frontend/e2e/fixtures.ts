/**
 * The `/api` responses the screenshot tests run against.
 *
 * Every view is rendered from these rather than from a database: a screenshot test is a view test,
 * and the API contract is proven by backend/tests/test_api.py. No clock, no container, no fixtures
 * to migrate — and every timestamp below is fixed, so a snapshot cannot drift by being taken later.
 */

import type { History, Session, ThingDetail, TreeLevel, UserModel } from "../src/api";

export const ROOT_ID = "11111111-1111-1111-1111-111111111111";
export const CHILD_ID = "22222222-2222-2222-2222-222222222222";
export const LEAF_ID = "33333333-3333-3333-3333-333333333333";
export const BLOCKER_ID = "44444444-4444-4444-4444-444444444444";
export const OBSERVATION_ID = "55555555-5555-5555-5555-555555555555";
export const PREFERENCE_ID = "66666666-6666-6666-6666-666666666666";
export const REJECTED_ID = "77777777-7777-7777-7777-777777777777";

export const session: Session = { email: "owner@example.test" };

export const topLevel: TreeLevel = {
  things: [
    {
      id: ROOT_ID,
      title: "Rebuild Reli",
      tags: ["#Project", "#Reli"],
      priority: 5,
      active: true,
      checkin_date: "2026-10-01",
      has_children: true,
    },
    {
      id: LEAF_ID,
      title: "Book the dentist",
      tags: ["#Admin"],
      priority: 1,
      active: true,
      checkin_date: null,
      has_children: false,
    },
  ],
};

export const childrenOf: Record<string, TreeLevel> = {
  [ROOT_ID]: {
    things: [
      {
        id: CHILD_ID,
        title: "Read-only web view",
        tags: ["#Issue"],
        priority: 4,
        active: true,
        checkin_date: null,
        has_children: false,
      },
      {
        id: BLOCKER_ID,
        title: "The learning pass",
        tags: ["#Issue"],
        priority: 2,
        active: true,
        checkin_date: null,
        has_children: false,
      },
    ],
  },
};

export const thingDetail: ThingDetail = {
  thing: {
    id: CHILD_ID,
    title: "Read-only web view",
    description: "Tree, Thing detail with history, and the user model.",
    notes: {
      why: "Chat can say **what Claude did**. It cannot show fifty inferred preferences at a glance.",
      shape: "Three views, one read-only API, and exactly one button.",
    },
    tags: ["#Issue", "#Reli"],
    urls: { issue: "https://github.com/alexsiri7/reli/issues/1414" },
    checkin_date: "2026-09-20",
    priority: 4,
    active: true,
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-09T16:30:00Z",
  },
  relationships: [
    {
      id: "a1111111-1111-1111-1111-111111111111",
      relationship_type: "ChildOf",
      direction: "incoming",
      context: "ninth issue of the rebuild",
      created_at: "2026-09-01T09:00:00Z",
      other: { id: ROOT_ID, title: "Rebuild Reli", tags: ["#Project"] },
    },
    {
      id: "a2222222-2222-2222-2222-222222222222",
      relationship_type: "Blocks",
      direction: "outgoing",
      context: null,
      created_at: "2026-09-02T10:15:00Z",
      other: { id: BLOCKER_ID, title: "The learning pass", tags: ["#Issue"] },
    },
  ],
};

export const history: History = {
  entries: [
    {
      id: 41,
      occurred_at: "2026-09-01T09:00:00Z",
      actor: "claude_interactive",
      operation: "create",
      entity_type: "thing",
      entity_id: CHILD_ID,
      before: null,
      after: { title: "Read-only web view", priority: 0 },
    },
    {
      id: 57,
      occurred_at: "2026-09-09T16:30:00Z",
      actor: "claude_scheduled",
      operation: "update",
      entity_type: "thing",
      entity_id: CHILD_ID,
      before: { priority: 0 },
      after: { priority: 4 },
    },
    {
      id: 58,
      occurred_at: "2026-09-10T08:05:00Z",
      actor: "user",
      operation: "update",
      entity_type: "thing",
      entity_id: CHILD_ID,
      before: { checkin_date: null },
      after: { checkin_date: "2026-09-20" },
    },
  ],
  total: 3,
  truncated: false,
};

export const userModel: UserModel = {
  scope: null,
  preferences: [
    {
      thing: {
        id: PREFERENCE_ID,
        title: "Prefers deep work 9-11am",
        description: null,
        notes: { scope: "scheduling" },
        tags: ["#Preference"],
        urls: {},
        checkin_date: null,
        priority: 3,
        active: true,
        created_at: "2026-08-20T07:00:00Z",
        updated_at: "2026-09-05T07:00:00Z",
      },
      scope: "scheduling",
      rejected: false,
      evidence: [
        { id: OBSERVATION_ID, title: "Moved the 9am standup again", tags: ["#Observation"] },
        { id: CHILD_ID, title: "Read-only web view", tags: ["#Issue"] },
      ],
      evidence_count: 2,
    },
    {
      thing: {
        id: REJECTED_ID,
        title: "Prefers meetings on Fridays",
        description: null,
        notes: { scope: "scheduling" },
        tags: ["#Preference", "#Rejected"],
        urls: {},
        checkin_date: null,
        priority: 1,
        active: true,
        created_at: "2026-08-22T07:00:00Z",
        updated_at: "2026-09-06T07:00:00Z",
      },
      scope: "scheduling",
      rejected: true,
      evidence: [{ id: OBSERVATION_ID, title: "Moved the 9am standup again", tags: ["#Observation"] }],
      evidence_count: 1,
    },
  ],
};
