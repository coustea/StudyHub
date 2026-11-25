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
    request<{ token: string; user: any }>('/api/auth/login', { method: 'POST', body: JSON.stringify(data) }),

  me: () => request<{ user: any }>('/api/auth/me'),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<{ ok: boolean }>('/api/auth/change-password', {
      method: 'POST', body: JSON.stringify({ oldPassword, newPassword }),
    }),

  search: (q: string) => request<{ query: string; projects: any[]; notes: any[] }>(`/api/search?q=${encodeURIComponent(q)}`),

  recent: (limit = 20) => request<{ notes: any[] }>(`/api/recent?limit=${limit}`),

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

  site: () => request<{ site: any }>('/api/site'),

  overview: () => request<{
    site: any; projects: any[]; recent: any[]; tags: any[]
    daily: { date: string; todayCount: number; streak: number; activeDays: number }
  }>('/api/overview'),

  createProject: (data: any) =>
    request<{ project: any }>('/api/projects', { method: 'POST', body: JSON.stringify(data) }),

  createProjectFromFolder: (data: any) =>
    request<{ project: any; imported: number; skipped: number }>('/api/projects/from-folder', {
      method: 'POST', body: JSON.stringify(data),
    }),

  getProject: (id: string | number) => request<{ project: any; nodes: any[] }>(`/api/projects/${id}`),

  updateProject: (id: number, data: any) =>
    request<{ project: any }>(`/api/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteProject: (id: number) =>
    request<{ ok: boolean }>(`/api/projects/${id}`, { method: 'DELETE' }),

  createNode: (data: any) =>
    request<{ node: any }>('/api/nodes', { method: 'POST', body: JSON.stringify(data) }),

  getNode: (id: number) => request<{ node: any }>(`/api/nodes/${id}`),

  updateNode: (id: number, data: any) =>
    request<{ node: any }>(`/api/nodes/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteNode: (id: number) => request<{ ok: boolean }>(`/api/nodes/${id}`, { method: 'DELETE' }),

  importFiles: (data: any) =>
    request<{ ok: boolean; imported: number; skipped?: number }>('/api/import', { method: 'POST', body: JSON.stringify(data) }),
}
