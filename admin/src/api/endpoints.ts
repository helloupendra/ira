import { request, requestPage, type Page } from './client';
import type { components, operations } from './schema';

type Schemas = components['schemas'];

// Row and view types, named as the OpenAPI document names them.
export type Session = Schemas['SessionResponse'];
export type Status = Schemas['StatusResponse'];
export type User = Schemas['UserView'];
export type UserView = Schemas['UserView'];
export type AdminUserRow = Schemas['AdminUserRow'];
export type RoleView = Schemas['RoleView'];
export type Overview = Schemas['Overview'];
export type ModelUsage = Schemas['ModelUsage'];
export type CallRow = Schemas['CallRow'];
export type ConversationRow = Schemas['ConversationRow'];
export type MessageRow = Schemas['MessageRow'];
export type ToolCallView = Schemas['ToolCallView'];
export type ActionRow = Schemas['ActionRow'];
export type ToolDetail = Schemas['ToolDetail'];
export type ToolTestResult = Schemas['ToolTestResult'];
export type ChannelView = Schemas['ChannelView'];
export type AuditRow = Schemas['AuditRow'];
export type ChangeRow = Schemas['ChangeRow'];
export type CostDay = Schemas['CostDay'];
export type SecurityView = Schemas['SecurityView'];
export type ActionRule = Schemas['ActionRule'];
export type TokenRow = Schemas['TokenRow'];
export type TokenCreated = Schemas['TokenCreated'];
export type InviteView = Schemas['InviteView'];
export type InviteCreated = Schemas['InviteCreated'];
export type PublicInvite = Schemas['PublicInvite'];
export type ModelsView = Schemas['ModelsView'];
export type TierView = Schemas['TierView'];
export type ProviderView = Schemas['ProviderView'];
export type ModelTestResult = Schemas['ModelTestResult'];
export type KeyView = Schemas['KeyView'];
export type SettingsView = Schemas['SettingsView'];
export type SettingValue = Schemas['SettingValue'];
export type SettingsUpdate = Schemas['SettingsUpdate'];
export type SessionView = Schemas['SessionView'];
export type AdminSessionRow = Schemas['AdminSessionRow'];
export type SessionsEnded = Schemas['SessionsEnded'];
export type PinStatus = Schemas['PinStatus'];
export type SetupStatus = Schemas['SetupStatus'];
export type OkResponse = Schemas['OkResponse'];
export type ActionCounts = Schemas['ActionCounts'];
export type TelegramView = Schemas['TelegramView'];
export type TelegramChat = Schemas['TelegramChat'];
export type TelegramPairing = Schemas['TelegramPairing'];
export type VoiceOption = Schemas['VoiceOption'];
export type CoolingReason = Schemas['CoolingReason'];
export type ServerAddress = Schemas['ServerAddress'];
export type MyConversationRow = Schemas['MyConversationRow'];
export type DeviceView = Schemas['DeviceView'];
export type DeviceToolView = Schemas['DeviceToolView'];
export type SkillState = Schemas['SkillState'];
export type PairingView = Schemas['PairingView'];
export type PairingState = Schemas['PairingState'];
export type GrantView = Schemas['GrantView'];
export type DownloadView = Schemas['DownloadView'];
export type { Page };

type QueryOf<Op extends keyof operations> = NonNullable<operations[Op]['parameters']['query']>;

export type CallsQuery = QueryOf<'calls'>;
export type ConversationsQuery = QueryOf<'conversations'>;
export type ActionsQuery = QueryOf<'actions'>;
export type AuditQuery = QueryOf<'audit'>;
export type ChangesQuery = QueryOf<'change_log'>;
export type CostsQuery = QueryOf<'costs'>;
export type SessionsQuery = QueryOf<'my_sessions'>;
export type AdminSessionsQuery = QueryOf<'sessions'>;
export type CountsQuery = QueryOf<'action_counts'>;

const enc = encodeURIComponent;

export const auth = {
  me: (signal?: AbortSignal) => request<Session>('/v1/auth/me', { signal }),
  login: (email: string, password: string) =>
    request<Session>('/v1/auth/login', { method: 'POST', json: { email, password } }),
  logout: () => request<OkResponse>('/v1/auth/logout', { method: 'POST' }),
  status: (signal?: AbortSignal) => request<Status>('/v1/auth/status', { signal }),
};

// First-run setup and invitations: public, each guarded by its own one-time secret.
export const setup = {
  status: (signal?: AbortSignal) => request<SetupStatus>('/v1/setup/status', { signal }),
  owner: (code: string, email: string, password: string) =>
    request<Session>('/v1/setup/owner', { method: 'POST', json: { code, email, password } }),
};

export const invites = {
  lookup: (token: string, signal?: AbortSignal) =>
    request<PublicInvite>('/v1/invites/lookup', { method: 'POST', json: { token }, signal }),
  accept: (token: string, password: string) =>
    request<Session>('/v1/invites/accept', { method: 'POST', json: { token, password } }),
};

// The signed-in person's own PIN and sessions.
export const me = {
  pin: (signal?: AbortSignal) => request<PinStatus>('/v1/me/pin', { signal }),
  setPin: (password: string, pin: string) =>
    request<OkResponse>('/v1/me/pin', { method: 'PUT', json: { password, pin } }),
  sessions: (signal?: AbortSignal) => request<SessionView[]>('/v1/me/sessions', { signal }),
  sessionsPage: (query: SessionsQuery = {}, signal?: AbortSignal) =>
    requestPage<SessionView[]>('/v1/me/sessions', { query, signal }),
  endSession: (id: string) => request<OkResponse>(`/v1/me/sessions/${enc(id)}`, { method: 'DELETE' }),
  endOtherSessions: () =>
    request<SessionsEnded>('/v1/me/sessions/revoke-others', { method: 'POST' }),

  // Your own devices and grants: pairing and switching a skill on need your PIN.
  devices: (signal?: AbortSignal) => request<DeviceView[]>('/v1/me/devices', { signal }),
  pairDevice: (kind: string, label: string | null, skills: string[], pin: string) =>
    request<PairingView>('/v1/me/devices/pairing', { method: 'POST', json: { kind, label, skills, pin } }),
  pairing: (id: string, signal?: AbortSignal) =>
    request<PairingState>(`/v1/me/devices/pairings/${enc(id)}`, { signal }),
  updateDevice: (id: number, update: { skills?: string[]; label?: string; pin?: string }) =>
    request<DeviceView>(`/v1/me/devices/${id}`, { method: 'PATCH', json: update }),
  revokeDevice: (id: number) => request<OkResponse>(`/v1/me/devices/${id}`, { method: 'DELETE' }),
  grants: (signal?: AbortSignal) => request<GrantView[]>('/v1/me/grants', { signal }),
  revokeGrant: (id: string) => request<OkResponse>(`/v1/me/grants/${enc(id)}`, { method: 'DELETE' }),
};

export const downloads = {
  list: (signal?: AbortSignal) => request<DownloadView[]>('/v1/downloads', { signal }),
};

export const admin = {
  // Reads (admin.read).
  overview: (signal?: AbortSignal) => request<Overview>('/v1/admin/overview', { signal }),
  calls: (query: CallsQuery = {}, signal?: AbortSignal) =>
    request<CallRow[]>('/v1/admin/calls', { query, signal }),
  conversations: (query: ConversationsQuery = {}, signal?: AbortSignal) =>
    request<ConversationRow[]>('/v1/admin/conversations', { query, signal }),
  conversation: (id: string, signal?: AbortSignal) =>
    request<MessageRow[]>(`/v1/admin/conversations/${enc(id)}`, { signal }),
  actions: (query: ActionsQuery = {}, signal?: AbortSignal) =>
    request<ActionRow[]>('/v1/admin/actions', { query, signal }),
  tools: (signal?: AbortSignal) => request<ToolDetail[]>('/v1/admin/tools', { signal }),
  channels: (signal?: AbortSignal) => request<ChannelView[]>('/v1/admin/channels', { signal }),
  audit: (query: AuditQuery = {}, signal?: AbortSignal) =>
    request<AuditRow[]>('/v1/admin/audit', { query, signal }),
  changes: (query: ChangesQuery = {}, signal?: AbortSignal) =>
    request<ChangeRow[]>('/v1/admin/changes', { query, signal }),
  costs: (query: CostsQuery = {}, signal?: AbortSignal) =>
    request<CostDay[]>('/v1/admin/costs', { query, signal }),
  security: (signal?: AbortSignal) => request<SecurityView>('/v1/admin/security', { signal }),
  users: (signal?: AbortSignal) => request<AdminUserRow[]>('/v1/admin/users', { signal }),
  roles: (signal?: AbortSignal) => request<RoleView[]>('/v1/admin/roles', { signal }),
  invites: (signal?: AbortSignal) => request<InviteView[]>('/v1/admin/users/invites', { signal }),
  sessions: (signal?: AbortSignal) => request<AdminSessionRow[]>('/v1/admin/sessions', { signal }),
  tokens: (signal?: AbortSignal) => request<TokenRow[]>('/v1/admin/tokens', { signal }),
  models: (signal?: AbortSignal) => request<ModelsView>('/v1/admin/models', { signal }),
  keys: (signal?: AbortSignal) => request<KeyView[]>('/v1/admin/keys', { signal }),
  settings: (signal?: AbortSignal) => request<SettingsView>('/v1/admin/settings', { signal }),

  // Paged lists: the same rows, plus whether more follow (X-Has-More).
  callsPage: (query: CallsQuery = {}, signal?: AbortSignal) =>
    requestPage<CallRow[]>('/v1/admin/calls', { query, signal }),
  conversationsPage: (query: ConversationsQuery = {}, signal?: AbortSignal) =>
    requestPage<ConversationRow[]>('/v1/admin/conversations', { query, signal }),
  conversationInfo: (id: string, signal?: AbortSignal) =>
    request<ConversationRow>(`/v1/admin/conversations/${enc(id)}/info`, { signal }),
  actionsPage: (query: ActionsQuery = {}, signal?: AbortSignal) =>
    requestPage<ActionRow[]>('/v1/admin/actions', { query, signal }),
  actionCounts: (query: CountsQuery = {}, signal?: AbortSignal) =>
    request<ActionCounts>('/v1/admin/actions/counts', { query, signal }),
  auditPage: (query: AuditQuery = {}, signal?: AbortSignal) =>
    requestPage<AuditRow[]>('/v1/admin/audit', { query, signal }),
  changesPage: (query: ChangesQuery = {}, signal?: AbortSignal) =>
    requestPage<ChangeRow[]>('/v1/admin/changes', { query, signal }),
  sessionsPage: (query: AdminSessionsQuery = {}, signal?: AbortSignal) =>
    requestPage<AdminSessionRow[]>('/v1/admin/sessions', { query, signal }),
  telegram: (signal?: AbortSignal) => request<TelegramView>('/v1/admin/telegram', { signal }),
  devices: (signal?: AbortSignal) => request<DeviceView[]>('/v1/admin/devices', { signal }),
  grants: (signal?: AbortSignal) => request<GrantView[]>('/v1/admin/grants', { signal }),

  // Writes: a session with admin.write, or users for accounts and invitations.
  startPairing: (userId?: number) =>
    request<TelegramPairing>('/v1/admin/telegram/pairing', {
      method: 'POST',
      json: userId === undefined ? {} : { user_id: userId },
    }),
  unpairChat: (chatId: number) =>
    request<OkResponse>(`/v1/admin/telegram/chats/${chatId}`, { method: 'DELETE' }),
  createInvite: (email: string, role: string) =>
    request<InviteCreated>('/v1/admin/users/invites', { method: 'POST', json: { email, role } }),
  revokeInvite: (id: string) =>
    request<OkResponse>(`/v1/admin/users/invites/${enc(id)}`, { method: 'DELETE' }),
  changeRole: (userId: number, role: string) =>
    request<AdminUserRow>(`/v1/admin/users/${userId}`, { method: 'PATCH', json: { role } }),
  removeUser: (userId: number) => request<OkResponse>(`/v1/admin/users/${userId}`, { method: 'DELETE' }),
  resetPin: (userId: number) =>
    request<OkResponse>(`/v1/admin/users/${userId}/reset-pin`, { method: 'POST' }),
  revokeSession: (id: string) =>
    request<OkResponse>(`/v1/admin/sessions/${enc(id)}`, { method: 'DELETE' }),
  createToken: (label: string, scopes: string[]) =>
    request<TokenCreated>('/v1/admin/tokens', { method: 'POST', json: { label, scopes } }),
  revokeToken: (id: string) => request<OkResponse>(`/v1/admin/tokens/${enc(id)}`, { method: 'DELETE' }),
  switchTool: (name: string, enabled: boolean) =>
    request<ToolDetail>(`/v1/admin/tools/${enc(name)}`, { method: 'PATCH', json: { enabled } }),
  testTool: (name: string, params: Record<string, unknown>) =>
    request<ToolTestResult>(`/v1/admin/tools/${enc(name)}/test`, { method: 'POST', json: { params } }),
  testModel: (ref: string) =>
    request<ModelTestResult>('/v1/admin/models/test', { method: 'POST', json: { ref } }),
  orderTier: (tier: string, order: string[] | null) =>
    request<TierView>(`/v1/admin/models/tiers/${enc(tier)}`, { method: 'PUT', json: { order } }),
  updateSettings: (update: SettingsUpdate) =>
    request<SettingsView>('/v1/admin/settings', { method: 'PATCH', json: update }),
  // Anyone's devices and grants: switch off or revoke, never switch on.
  switchDeviceSkills: (id: number, skills: string[]) =>
    request<DeviceView>(`/v1/admin/devices/${id}`, { method: 'PATCH', json: { skills } }),
  revokeDevice: (id: number) => request<OkResponse>(`/v1/admin/devices/${id}`, { method: 'DELETE' }),
  revokeGrant: (id: string) => request<OkResponse>(`/v1/admin/grants/${enc(id)}`, { method: 'DELETE' }),
};
