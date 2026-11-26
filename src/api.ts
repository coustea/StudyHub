import type { AdminNote, AiConfig, NoteNode, Project, ReaderNote, User } from './types'

const TOKEN_KEY = 'notes_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(url, { ...options, headers })
  let body: any = null
  try {
    body = await response.json()
  } catch {
    body = null
  }
  if (!response.ok) {
    if (response.status === 401 && token) clearToken()
    throw new Error(body?.error || `请求失败（${response.status}）`)
  }
  return body as T
}

export const api = {
  login: (data: { username: string; password: string }) =>
    request<{ token: string; user: User }>('/api/auth/login', { method: 'POST', body: JSON.stringify(data) }),

  me: () => request<{ user: User }>('/api/auth/me'),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ ok: boolean }>('/api/auth/change-password', {
      method: 'POST', body: JSON.stringify({ oldPassword, newPassword }),
    }),

  search: (q: string, publicView = false) =>
    request<{ query: string; projects: Project[]; notes: (ReaderNote & { excerpt: string })[] }>(
      `/api/search?q=${encodeURIComponent(q)}${publicView ? '&public=1' : ''}`,
    ),

  recent: (limit = 20, publicView = false) =>
    request<{ notes: ReaderNote[] }>(`/api/recent?limit=${limit}${publicView ? '&public=1' : ''}`),

  daily: (date?: string, days = 120) =>
    request<{ date: string; todayCount: number; streak: number; activeDays: number; notes: any[]; calendar: { date: string; count: number }[] }>(
      `/api/daily?days=${days}${date ? `&date=${encodeURIComponent(date)}` : ''}`,
    ),

  dailyNew: (data: { date?: string; title?: string }) =>
    request<{ node: any; project: any }>('/api/daily/new', {
      method: 'POST', body: JSON.stringify(data),
    }),

  trash: () => request<{ nodes: any[]; total: number }>('/api/trash'),
  restoreNode: (id: number) =>
    request<{ ok: boolean; node: any }>(`/api/trash/${id}/restore`, { method: 'POST' }),

  purgeNode: (id: number) => request<{ ok: boolean }>(`/api/trash/${id}`, { method: 'DELETE' }),

  emptyTrash: (days?: number) =>
    request<{ ok: boolean; removed: number }>(`/api/trash${days ? `?days=${days}` : ''}`, { method: 'DELETE' }),

  upload: (fileName: string, mimeType: string, data: string) =>
    request<{ url: string; name: string }>('/api/uploads', {
      method: 'POST', body: JSON.stringify({ fileName, mimeType, data }),
    }),

  generateMarkdown: (data: { apiKey?: string; model?: string; baseURL?: string; mode: 'draft' | 'continue' | 'rewrite'; prompt: string; title: string; context: string }) =>
    request<{ markdown: string }>('/api/ai/markdown', { method: 'POST', body: JSON.stringify(data) }),

  aiConfig: () => request<{ config: AiConfig }>('/api/admin/ai-config'),

  saveAiConfig: (data: { apiKey?: string; model: string; baseURL: string; clearApiKey?: boolean }) =>
    request<{ config: AiConfig }>('/api/admin/ai-config', { method: 'PUT', body: JSON.stringify(data) }),
  testAiConfig: (data: { apiKey?: string; model?: string; baseURL?: string }) =>
    request<{ ok: boolean; endpoint: string; model: string; hint: string }>('/api/admin/ai-config/test', { method: 'POST', body: JSON.stringify(data) }),

  adminNotes: () => request<{ notes: AdminNote[] }>('/api/admin/notes'),

  batchAdminNotes: (ids: number[], action: 'publish' | 'draft' | 'trash') =>
    request<{ ok: boolean; affected: number }>('/api/admin/notes/batch', {
      method: 'POST', body: JSON.stringify({ ids, action }),
    }),

  site: (publicView = false) => request<{ site: any }>(`/api/site${publicView ? '?public=1' : ''}`),

  overview: (publicView = false) => request<{
    site: any; projects: Project[]; recent: ReaderNote[]; tags: { tag: string; count: number }[]
    daily: { date: string; todayCount: number; streak: number; activeDays: number }
  }>(`/api/overview${publicView ? '?public=1' : ''}`),

  createProject: (data: any) =>
    request<{ project: Project }>('/api/projects', { method: 'POST', body: JSON.stringify(data) }),

  createProjectFromFolder: (data: any) =>
    request<{ project: Project; imported: number; skipped: number }>('/api/projects/from-folder', {
      method: 'POST', body: JSON.stringify(data),
    }),

  getProject: (id: string | number, publicView = false) =>
    request<{ project: Project; nodes: NoteNode[] }>(`/api/projects/${id}${publicView ? '?public=1' : ''}`),

  updateProject: (id: number, data: any) =>
    request<{ project: any }>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteProject: (id: number) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: 'DELETE' }),

  createNode: (data: any) =>
    request<{ node: any }>('/api/nodes', { method: 'POST', body: JSON.stringify(data) }),

  getNode: (id: number) => request<{ node: any }>(`/api/nodes/${id}`),

  nodeRevisions: (id: number) =>
    request<{ revisions: { id: number; title: string; created_at: string }[] }>(`/api/nodes/${id}/revisions`),

  nodeRevision: (id: number, revisionId: number) =>
    request<{ revision: { title: string; slug: string; content: string; tags: string } }>(
      `/api/nodes/${id}/revisions/${revisionId}`,
    ),

  updateNode: (id: number, data: any) =>
    request<{ node: any }>(`/api/nodes/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  moveNode: (id: number, data: { parentId: number; beforeId: number | null }) =>
    request<{ node: any }>(`/api/nodes/${id}/move`, { method: 'POST', body: JSON.stringify(data) }),

  deleteNode: (id: number) => request<{ ok: boolean }>(`/api/nodes/${id}`, { method: 'DELETE' }),

  importFiles: (data: any) =>
    request<{ ok: boolean; imported: number; skipped: number; duplicates: number }>('/api/import', {
      method: 'POST', body: JSON.stringify(data),
    }),
}
