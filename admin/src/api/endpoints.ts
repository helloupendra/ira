import { request } from './client';
import type { components, operations } from './schema';

type Schemas = components['schemas'];

export type Session = Schemas['SessionResponse'];
export type Status = Schemas['StatusResponse'];
export type User = Schemas['UserView'];
export type Overview = Schemas['Overview'];
export type ModelUsage = Schemas['ModelUsage'];
export type CallRow = Schemas['CallRow'];
export type ConversationRow = Schemas['ConversationRow'];
export type MessageRow = Schemas['MessageRow'];
export type ActionRow = Schemas['ActionRow'];
export type ToolDetail = Schemas['ToolDetail'];
export type ChannelView = Schemas['ChannelView'];
export type AuditRow = Schemas['AuditRow'];
export type UserView = Schemas['UserView'];
export type TokenRow = Schemas['TokenRow'];
export type OkResponse = Schemas['OkResponse'];

type QueryOf<Op extends keyof operations> = NonNullable<operations[Op]['parameters']['query']>;

export type CallsQuery = QueryOf<'calls'>;
export type ConversationsQuery = QueryOf<'conversations'>;
export type ActionsQuery = QueryOf<'actions'>;
export type AuditQuery = QueryOf<'audit'>;

export const auth = {
  me: (signal?: AbortSignal) => request<Session>('/v1/auth/me', { signal }),
  login: (email: string, password: string) =>
    request<Session>('/v1/auth/login', { method: 'POST', json: { email, password } }),
  logout: () => request<OkResponse>('/v1/auth/logout', { method: 'POST' }),
  status: (signal?: AbortSignal) => request<Status>('/v1/auth/status', { signal }),
};

export const admin = {
  overview: (signal?: AbortSignal) => request<Overview>('/v1/admin/overview', { signal }),
  calls: (query: CallsQuery = {}, signal?: AbortSignal) =>
    request<CallRow[]>('/v1/admin/calls', { query, signal }),
  conversations: (query: ConversationsQuery = {}, signal?: AbortSignal) =>
    request<ConversationRow[]>('/v1/admin/conversations', { query, signal }),
  conversation: (id: string, signal?: AbortSignal) =>
    request<MessageRow[]>(`/v1/admin/conversations/${encodeURIComponent(id)}`, { signal }),
  actions: (query: ActionsQuery = {}, signal?: AbortSignal) =>
    request<ActionRow[]>('/v1/admin/actions', { query, signal }),
  tools: (signal?: AbortSignal) => request<ToolDetail[]>('/v1/admin/tools', { signal }),
  channels: (signal?: AbortSignal) => request<ChannelView[]>('/v1/admin/channels', { signal }),
  audit: (query: AuditQuery = {}, signal?: AbortSignal) =>
    request<AuditRow[]>('/v1/admin/audit', { query, signal }),
  users: (signal?: AbortSignal) => request<UserView[]>('/v1/admin/users', { signal }),
  tokens: (signal?: AbortSignal) => request<TokenRow[]>('/v1/admin/tokens', { signal }),
};
