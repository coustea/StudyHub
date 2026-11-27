import { useMemo, useRef, useState, type FormEvent, type PointerEvent, type KeyboardEvent, type ReactNode } from 'react'
import Icon from './Icon'
import type { NoteNode } from '../types'

interface TreeNode extends NoteNode { children: TreeNode[] }
type Kind = 'folder' | 'doc'
type Destination = { parentId: number; beforeId: number | null; targetId: number; position: 'before' | 'after' | 'inside' | 'root' }

function buildTree(nodes: NoteNode[]): TreeNode[] {
  const map = new Map(nodes.map((node) => [node.id, { ...node, children: [] as TreeNode[] }]))
  const roots: TreeNode[] = []
  nodes.forEach((node) => {
    const item = map.get(node.id)!
    if (node.parent_id && map.has(node.parent_id)) map.get(node.parent_id)!.children.push(item)
    else roots.push(item)
  })
  return roots
}

export default function ProjectFileTree({ nodes, selectedId, owner, onSelect, onCreate, onMove, onDelete, onEdit, onRename, onImportInto }: {
  nodes: NoteNode[]
  selectedId: number | null
  owner: boolean
  onSelect: (node: NoteNode) => void
  onCreate: (parentId: number, kind: Kind, title: string) => Promise<void>
  onMove: (id: number, parentId: number, beforeId: number | null) => Promise<void>
  onDelete: (node: NoteNode) => void
  onEdit: (node: NoteNode) => void
  onRename?: (node: NoteNode, title: string) => Promise<void>
  onImportInto?: (folder: NoteNode) => void
}) {
  const tree = useMemo(() => buildTree(nodes), [nodes])
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [creating, setCreating] = useState<{ parentId: number; kind: Kind } | null>(null)
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState<{ id: number; title: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [drop, setDrop] = useState<Destination | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: number; pointerId: number; y: number; destination: Destination | null; frame: number } | null>(null)

  const siblings = (parentId: number) => nodes.filter((node) => node.parent_id === parentId)
  const isInvalidParent = (sourceId: number, parentId: number) => {
    let current = parentId
    const seen = new Set<number>()
    while (current && !seen.has(current)) {
      if (current === sourceId) return true
      seen.add(current)
      current = byId.get(current)?.parent_id || 0
    }
    return false
  }

  const beginCreate = (parentId: number, kind: Kind) => {
    setRenaming(null)
    setCreating({ parentId, kind })
    setName('')
    if (parentId) setCollapsed((previous) => {
      const next = new Set(previous)
      next.delete(parentId)
      return next
    })
  }

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault()
    if (!creating || !name.trim() || busy) return
    setBusy(true)
    try {
      await onCreate(creating.parentId, creating.kind, name.trim())
      setAnnouncement(`已创建${creating.kind === 'folder' ? '文件夹' : '笔记'} ${name.trim()}`)
      setCreating(null)
      setName('')
    } catch { setAnnouncement('创建失败，请检查提示后重试') }
    finally { setBusy(false) }
  }

  const beginRename = (node: NoteNode) => {
    if (!onRename) { onEdit(node); return }
    setCreating(null)
    setRenaming({ id: node.id, title: node.title })
  }

  const submitRename = async (event: FormEvent) => {
    event.preventDefault()
    if (!renaming || !onRename || busy) return
    const nextTitle = renaming.title.trim()
    const target = byId.get(renaming.id)
    if (!target || !nextTitle) return
    if (nextTitle === target.title) { setRenaming(null); return }
    setBusy(true)
    try {
      await onRename(target, nextTitle)
      setAnnouncement(`已重命名为 ${nextTitle}`)
      setRenaming(null)
    } catch { setAnnouncement('重命名失败，请重试') }
    finally { setBusy(false) }
  }

  const resolveDrop = (sourceId: number, x: number, y: number) => {
    const target = document.elementFromPoint(x, y) as HTMLElement | null
    const row = target?.closest<HTMLElement>('[data-tree-node]')
    if (!row || !scroller.current?.contains(row)) {
      const root = target?.closest('[data-tree-root]')
      return root && scroller.current?.contains(root) ? { parentId: 0, beforeId: null, targetId: 0, position: 'root' as const } : null
    }
    const targetId = Number(row.dataset.treeNode)
    const item = byId.get(targetId)
    if (!item || targetId === sourceId) return null
    const rect = row.getBoundingClientRect()
    const fraction = (y - rect.top) / rect.height
    if (item.kind === 'folder' && fraction >= .25 && fraction <= .75) {
      return isInvalidParent(sourceId, item.id) ? null : { parentId: item.id, beforeId: null, targetId, position: 'inside' as const }
    }
    const siblingsHere = siblings(item.parent_id).filter((node) => node.id !== sourceId)
    const index = siblingsHere.findIndex((node) => node.id === targetId)
    const beforeId = fraction < .5 ? targetId : (siblingsHere[index + 1]?.id || null)
    return isInvalidParent(sourceId, item.parent_id) ? null : {
      parentId: item.parent_id, beforeId, targetId, position: fraction < .5 ? 'before' as const : 'after' as const,
    }
  }

  const updateDrop = (sourceId: number, x: number, y: number) => {
    const destination = resolveDrop(sourceId, x, y)
    if (drag.current) drag.current.destination = destination
    setDrop(destination)
  }

  const scrollWhileDragging = () => {
    const active = drag.current
    const list = scroller.current
    if (!active || !list) return
    const bounds = list.getBoundingClientRect()
    const edge = Math.min(48, bounds.height / 3)
    if (active.y < bounds.top + edge) list.scrollTop -= Math.min(12, (bounds.top + edge - active.y) / 3)
    else if (active.y > bounds.bottom - edge) list.scrollTop += Math.min(12, (active.y - bounds.bottom + edge) / 3)
    const x = Math.max(bounds.left + 1, Math.min(bounds.right - 1, bounds.left + bounds.width / 2))
    updateDrop(active.id, x, active.y)
    active.frame = requestAnimationFrame(scrollWhileDragging)
  }

  const stopDrag = () => {
    if (drag.current) cancelAnimationFrame(drag.current.frame)
    drag.current = null
    setDrop(null)
  }

  const pointerDown = (event: PointerEvent<HTMLButtonElement>, node: NoteNode) => {
    if (event.button !== 0 || drag.current) return
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { id: node.id, pointerId: event.pointerId, y: event.clientY, destination: null, frame: 0 }
    drag.current.frame = requestAnimationFrame(scrollWhileDragging)
  }

  const pointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return
    drag.current.y = event.clientY
    updateDrop(drag.current.id, event.clientX, event.clientY)
  }

  const pointerUp = async (event: PointerEvent<HTMLButtonElement>) => {
    const active = drag.current
    if (!active || active.pointerId !== event.pointerId) return
    const destination = active.destination
    stopDrag()
    if (!destination) return
    const source = byId.get(active.id)!
    const current = siblings(source.parent_id).filter((node) => node.id !== source.id)
    const oldIndex = siblings(source.parent_id).findIndex((node) => node.id === source.id)
    const sameSlot = source.parent_id === destination.parentId && (destination.beforeId === (current[oldIndex]?.id || null))
    if (sameSlot) return
    try {
      await onMove(source.id, destination.parentId, destination.beforeId)
      if (destination.parentId) setCollapsed((previous) => {
        const next = new Set(previous)
        next.delete(destination.parentId)
        return next
      })
      setAnnouncement(`已移动 ${source.title}`)
    } catch { setAnnouncement(`移动 ${source.title} 失败`) }
  }

  const moveByKeyboard = async (event: KeyboardEvent<HTMLButtonElement>, node: NoteNode) => {
    if (!event.altKey || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return
    event.preventDefault()
    const items = siblings(node.parent_id)
    const index = items.findIndex((item) => item.id === node.id)
    let parentId = node.parent_id
    let beforeId: number | null = null
    if (event.key === 'ArrowUp') {
      if (index === 0) return
      beforeId = items[index - 1].id
    } else if (event.key === 'ArrowDown') {
      if (index === items.length - 1) return
      beforeId = items[index + 2]?.id || null
    } else if (event.key === 'ArrowLeft') {
      if (!parentId) return
      const parent = byId.get(parentId)!
      const next = siblings(parent.parent_id)
      parentId = parent.parent_id
      beforeId = next[next.findIndex((item) => item.id === parent.id) + 1]?.id || null
    } else {
      const previous = items[index - 1]
      if (!previous || previous.kind !== 'folder' || isInvalidParent(node.id, previous.id)) return
      parentId = previous.id
    }
    try {
      await onMove(node.id, parentId, beforeId)
      setCollapsed((previous) => { const next = new Set(previous); next.delete(parentId); return next })
      setAnnouncement(`已移动 ${node.title}`)
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-drag-id="${node.id}"]`)?.focus())
    } catch { setAnnouncement(`移动 ${node.title} 失败`) }
  }

  const createInput = (depth: number) => {
    if (!creating) return null
    const parentNode = creating.parentId ? byId.get(creating.parentId) : null
    const placeholder = creating.kind === 'folder'
      ? (parentNode ? `在「${parentNode.title}」下新建子文件夹` : '在根目录新建文件夹')
      : (parentNode ? `在「${parentNode.title}」下新建笔记` : '在根目录新建笔记')
    return (
      <form className="tree-new" style={{ paddingLeft: 8 + depth * 14 }} onSubmit={submitCreate}>
        <Icon name={creating.kind === 'folder' ? 'folder' : 'file'} size={15} />
        <input
          autoFocus
          aria-label={placeholder}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Escape') setCreating(null) }}
          placeholder={placeholder}
          disabled={busy}
        />
        <button type="submit" title="确认创建" aria-label="确认创建" disabled={!name.trim() || busy}>
          <Icon name="check" size={14} />
        </button>
        <button type="button" title="取消" aria-label="取消创建" onClick={() => setCreating(null)} disabled={busy}>
          <Icon name="x" size={14} />
        </button>
      </form>
    )
  }

  const renderItems = (items: TreeNode[], depth: number): ReactNode => items.map((node) => {
    const folder = node.kind === 'folder'
    const open = !collapsed.has(node.id)
    const active = selectedId === node.id
    const isRenaming = renaming?.id === node.id
    return <div key={node.id}>
      {isRenaming ? (
        <form className="tree-new tree-rename" style={{ paddingLeft: 8 + depth * 14 }} onSubmit={submitRename}>
          <Icon name={folder ? 'folder' : 'file'} size={15} />
          <input
            autoFocus
            aria-label={`重命名 ${node.title}`}
            value={renaming.title}
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => setRenaming({ id: node.id, title: event.target.value })}
            onKeyDown={(event) => { if (event.key === 'Escape') setRenaming(null) }}
            disabled={busy}
          />
          <button type="submit" title="保存名称" aria-label="保存名称" disabled={!renaming.title.trim() || busy}>
            <Icon name="check" size={14} />
          </button>
          <button type="button" title="取消" aria-label="取消重命名" onClick={() => setRenaming(null)} disabled={busy}>
            <Icon name="x" size={14} />
          </button>
        </form>
      ) : (
        <div className={`tree-row${active ? ' active' : ''}${drop?.targetId === node.id ? ` drop-${drop.position}` : ''}`}
          data-tree-node={node.id} style={{ paddingLeft: 8 + depth * 14 }}>
          {owner && <button type="button" className="tree-drag" data-drag-id={node.id}
            title="拖动整理；Alt + 方向键移动" aria-label={`移动 ${node.title}，Alt 加方向键调整位置`}
            onPointerDown={(event) => pointerDown(event, node)} onPointerMove={pointerMove}
            onPointerUp={pointerUp} onPointerCancel={stopDrag} onLostPointerCapture={stopDrag}
            onKeyDown={(event) => moveByKeyboard(event, node)}>
            <span aria-hidden="true">⠿</span>
          </button>}
          <button type="button" className="tree-select" aria-expanded={folder ? open : undefined}
            aria-current={active ? 'page' : undefined}
            onDoubleClick={owner && folder && onRename ? () => beginRename(node) : undefined}
            onClick={() => folder ? setCollapsed((previous) => {
              const next = new Set(previous)
              if (next.has(node.id)) next.delete(node.id)
              else next.add(node.id)
              return next
            }) : onSelect(node)}>
            <span className="tree-icon" aria-hidden="true"><Icon name={folder ? (open ? 'folder-open' : 'folder') : 'file'} size={15} /></span>
            <span className="tree-title">{node.title}</span>
            {!folder && node.status === 'draft' && <span className="tree-draft-pill" title="草稿（访客不可见）">草稿</span>}
          </button>
          {owner && <span className="tree-actions">
            {folder && <>
              <button type="button" title="新建子文件夹" aria-label={`在 ${node.title} 下新建子文件夹`} onClick={() => beginCreate(node.id, 'folder')}><Icon name="folder" size={14} /></button>
              <button type="button" title="新建笔记" aria-label={`在 ${node.title} 下新建笔记`} onClick={() => beginCreate(node.id, 'doc')}><Icon name="plus" size={14} /></button>
              {onImportInto && (
                <button type="button" title="导入 Markdown 到此文件夹" aria-label={`导入 Markdown 到 ${node.title}`} onClick={() => onImportInto(node)}><Icon name="upload" size={14} /></button>
              )}
            </>}
            <button
              type="button"
              title={folder && onRename ? '重命名文件夹' : '编辑'}
              aria-label={folder && onRename ? `重命名 ${node.title}` : `编辑 ${node.title}`}
              onClick={() => (folder && onRename ? beginRename(node) : onEdit(node))}
            >
              <Icon name="pencil" size={14} />
            </button>
            <button type="button" className="is-danger" title="删除" aria-label={`删除 ${node.title}`} onClick={() => onDelete(node)}><Icon name="x" size={14} /></button>
          </span>}
        </div>
      )}
      {folder && open && <>
        {creating?.parentId === node.id && createInput(depth + 1)}
        {renderItems(node.children, depth + 1)}
      </>}
    </div>
  })

  return <>
    {owner && <div className="tree-toolbar">
      <strong>目录</strong>
      <div className="tree-toolbar-actions">
        <button type="button" className="tree-toolbar-btn" title="在项目根目录新建文件夹" onClick={() => beginCreate(0, 'folder')}>
          <Icon name="folder" size={14} /><span>文件夹</span>
        </button>
        <button type="button" className="tree-toolbar-btn" title="在项目根目录新建笔记" onClick={() => beginCreate(0, 'doc')}>
          <Icon name="plus" size={14} /><span>笔记</span>
        </button>
      </div>
    </div>}
    <div className="tree-scroll file-tree-scroll" ref={scroller}>
      {creating?.parentId === 0 && createInput(0)}
      {renderItems(tree, 0)}
      {owner && <div className={`tree-root-drop${drop?.position === 'root' ? ' is-target' : ''}`} data-tree-root>
        {tree.length ? '拖到这里移至项目根目录' : '点击上方「文件夹」或「笔记」开始搭建目录'}
      </div>}
      {!owner && !tree.length && <p className="dim tree-empty">还没有内容</p>}
    </div>
    {owner && <p className="tree-hint">悬停文件夹可建二级子目录或导入；双击名称或点铅笔可直接重命名。</p>}
    <span className="sr-only" role="status" aria-live="polite">{announcement}</span>
  </>
}
