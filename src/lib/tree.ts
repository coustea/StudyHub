import type { NoteNode } from '../types'

export interface FolderOption {
  id: number
  label: string
  path: string
  depth: number
}

/**
 * 将项目扁平节点列表转换为带层级路径的文件夹下拉选项，
 * 可选排除指定文件夹及其所有子孙（避免把目录移动到自身内部）。
 */
export function buildFolderOptions(nodes: NoteNode[], excludeId?: number): FolderOption[] {
  const excluded = new Set<number>()
  if (excludeId) {
    excluded.add(excludeId)
    let added = true
    while (added) {
      added = false
      for (const node of nodes) {
        if (node.kind === 'folder' && excluded.has(node.parent_id) && !excluded.has(node.id)) {
          excluded.add(node.id)
          added = true
        }
      }
    }
  }

  const childrenByParent = new Map<number, NoteNode[]>()
  for (const node of nodes) {
    if (node.kind !== 'folder' || excluded.has(node.id)) continue
    const list = childrenByParent.get(node.parent_id) || []
    list.push(node)
    childrenByParent.set(node.parent_id, list)
  }

  const options: FolderOption[] = [{ id: 0, label: '项目根目录', path: '项目根目录', depth: 0 }]

  const visit = (parentId: number, depth: number, prefix: string[]) => {
    const children = (childrenByParent.get(parentId) || [])
      .slice()
      .sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
    for (const folder of children) {
      const nextPrefix = [...prefix, folder.title]
      const path = nextPrefix.join(' / ')
      options.push({
        id: folder.id,
        label: `${'　'.repeat(depth)}└ ${folder.title}`,
        path,
        depth: depth + 1,
      })
      visit(folder.id, depth + 1, nextPrefix)
    }
  }

  visit(0, 0, [])
  return options
}
