export interface LocalFile {
  path: string
  name: string
  content: string
}

export interface FolderReadResult {
  rootName: string
  files: LocalFile[]
  skipped: number
}

const MARKDOWN_RE = /\.(md|markdown|mdx|txt)$/i
const SKIP_DIRS = new Set([
  'node_modules', 'dist', 'build', 'out', 'target', 'vendor',
  'coverage', '__pycache__', '.git', '.github', '.obsidian', '.idea', '.vscode',
])
const MAX_FILE_BYTES = 2 * 1024 * 1024
const MAX_FILES = 300

function shouldSkipPath(segments: string[]) {
  return segments.some((segment) => segment.startsWith('.') || SKIP_DIRS.has(segment))
}

async function buildResult(entries: { rel: string; file: File }[]): Promise<FolderReadResult> {
  const normalized = entries
    .map(({ rel, file }) => ({ rel: rel.replace(/\\/g, '/').replace(/^\/+/, ''), file }))
    .filter(({ rel }) => rel.length > 0)

  const rootName = normalized.length && normalized[0].rel.includes('/')
    ? normalized[0].rel.split('/')[0]
    : ''
  const prefix = rootName ? `${rootName}/` : ''

  const files: LocalFile[] = []
  let skipped = 0

  for (const { rel, file } of normalized) {
    if (prefix && !rel.startsWith(prefix)) continue
    const relative = prefix ? rel.slice(prefix.length) : rel
    const segments = relative.split('/').filter(Boolean)
    if (!segments.length) continue
    if (shouldSkipPath(segments)) { skipped += 1; continue }
    if (!MARKDOWN_RE.test(segments[segments.length - 1])) { skipped += 1; continue }
    if (file.size > MAX_FILE_BYTES) { skipped += 1; continue }
    if (files.length >= MAX_FILES) { skipped += 1; continue }
    files.push({
      path: relative,
      name: segments[segments.length - 1],
      content: await file.text(),
    })
  }

  files.sort((a, b) => a.path.localeCompare(b.path, 'zh-Hans-CN', { numeric: true }))
  return { rootName, files, skipped }
}

export async function readFromFileList(list: FileList | null): Promise<FolderReadResult> {
  if (!list || !list.length) return { rootName: '', files: [], skipped: 0 }
  const entries = Array.from(list).map((file) => ({
    rel: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
    file,
  }))
  return buildResult(entries)
}

function readEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = []
    const next = () => reader.readEntries((batch) => {
      if (!batch.length) { resolve(all); return }
      all.push(...batch)
      next()
    }, reject)
    next()
  })
}

function entryFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function walk(entry: FileSystemEntry, prefix: string, out: { rel: string; file: File }[]) {
  if (entry.isFile) {
    out.push({ rel: `${prefix}${entry.name}`, file: await entryFile(entry as FileSystemFileEntry) })
    return
  }
  if (!entry.isDirectory) return
  const reader = (entry as FileSystemDirectoryEntry).createReader()
  const children = await readEntries(reader)
  for (const child of children) {
    await walk(child, `${prefix}${entry.name}/`, out)
  }
}

export async function readFromDataTransfer(transfer: DataTransfer): Promise<FolderReadResult> {
  const entries: { rel: string; file: File }[] = []
  const items = Array.from(transfer.items || [])
  for (const item of items) {
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FileSystemEntry | null })
      .webkitGetAsEntry?.()
    if (entry) {
      await walk(entry, '', entries)
    } else {
      const file = item.getAsFile()
      if (file) entries.push({ rel: file.name, file })
    }
  }
  return buildResult(entries)
}

export function countFolders(files: LocalFile[]): number {
  const dirs = new Set<string>()
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean)
    parts.pop()
    let current = ''
    for (const part of parts) {
      current = current ? `${current}/${part}` : part
      dirs.add(current)
    }
  }
  return dirs.size
}
