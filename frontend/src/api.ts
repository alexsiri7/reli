/**
 * The `/api` contract, mirrored from the Pydantic models in backend/api.py.
 *
 * Hand-written rather than generated: the shapes are small, and stating them here is what makes a
 * backend field rename a compile error instead of an `undefined` in a view.
 */

export type RelationshipType = "ChildOf" | "Blocks" | "RelatedTo" | "EvidenceFor" | "References";
export type Direction = "outgoing" | "incoming";
export type Actor = "user" | "claude_interactive" | "claude_scheduled";
export type Operation = "create" | "update" | "delete" | "relate" | "unrelate";
export type EntityType = "thing" | "relationship";

export interface Neighbour {
  id: string;
  title: string;
  tags: string[];
}

export interface ThingSummary {
  id: string;
  title: string;
  tags: string[];
  priority: number;
  active: boolean;
  checkin_date: string | null;
  has_children: boolean;
}

export interface TreeLevel {
  things: ThingSummary[];
}

export interface Thing {
  id: string;
  title: string;
  description: string | null;
  notes: Record<string, string>;
  tags: string[];
  urls: Record<string, string>;
  checkin_date: string | null;
  priority: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Relationship {
  id: string;
  relationship_type: RelationshipType;
  direction: Direction;
  context: string | null;
  created_at: string;
  other: Neighbour;
}

export interface ThingDetail {
  thing: Thing;
  relationships: Relationship[];
}

export interface JournalEntry {
  id: number;
  occurred_at: string;
  actor: Actor;
  operation: Operation;
  entity_type: EntityType;
  entity_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface History {
  entries: JournalEntry[];
  total: number;
  truncated: boolean;
}

export interface Preference {
  thing: Thing;
  scope: string | null;
  rejected: boolean;
  evidence: Neighbour[];
  evidence_count: number;
}

export interface UserModel {
  scope: string | null;
  preferences: Preference[];
}

/** Who the `reli_session` cookie says is signed in. */
export interface Session {
  email: string;
}

export const paths = {
  treeLevel: (parentId?: string) =>
    parentId === undefined ? "/api/things" : `/api/things?parent=${encodeURIComponent(parentId)}`,
  thing: (id: string) => `/api/things/${encodeURIComponent(id)}`,
  history: (id: string) => `/api/things/${encodeURIComponent(id)}/history`,
  userModel: "/api/user-model",
  reject: (id: string) => `/api/preferences/${encodeURIComponent(id)}/reject`,
  session: "/api/auth/me",
  signIn: "/api/auth/google",
  signOut: "/api/auth/logout",
};

let onUnauthorized: () => void = () => {};

/**
 * Called when any `/api` request answers 401: the session has expired or was signed out elsewhere.
 * The app uses it to fall back to the sign-in view rather than leaving a view showing "401".
 */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    if (response.status === 401) onUnauthorized();
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/** The `detail` a FastAPI error carries, or the bare status when the body is not one. */
async function detail(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/** The signed-in session, or `null` when the server answers 401. Anything else is an error. */
export async function currentSession(): Promise<Session | null> {
  const response = await fetch(paths.session, { headers: { Accept: "application/json" } });
  if (response.status === 401) return null;
  return parse<Session>(response);
}

/** Where Google sign-in starts. A 501 names the settings a human has to set; that is the thrown message. */
export async function signInUrl(): Promise<string> {
  const response = await fetch(paths.signIn, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(await detail(response));
  return ((await response.json()) as { auth_url: string }).auth_url;
}

export async function signOut(): Promise<void> {
  const response = await fetch(paths.signOut, { method: "POST" });
  if (!response.ok) throw new Error(await detail(response));
}

export async function getJson<T>(url: string): Promise<T> {
  return parse<T>(await fetch(url, { headers: { Accept: "application/json" } }));
}

/** The one write the view is allowed. Everything else that changes state goes through Claude. */
export async function rejectPreference(id: string): Promise<Preference> {
  return parse<Preference>(await fetch(paths.reject(id), { method: "POST" }));
}
