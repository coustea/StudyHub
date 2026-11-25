// 类型定义：与 server/db.js 的表结构一一对应。
export interface User {
  id: number
  username: string
  display_name: string
}

export interface Project {
  id: number
  owner_id: number
  name: string
  slug: string
  description: string
  status: 'draft' | 'published'
  sort_order: number
  doc_count?: number
  folder_count?: number
  tags?: string[]
  created_at: string
  updated_at: string
}

export interface NoteNode {
  id: number
  owner_id: number
  project_id: number
  parent_id: number
  kind: 'folder' | 'doc'
  title: string
  slug: string
  content: string
  tags: string
  sort_order: number
  status: 'draft' | 'published'
  daily_date: string
  deleted_at: string | null
  created_at: string
  updated_at: string
}
