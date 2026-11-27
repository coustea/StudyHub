import Icon from './Icon'

export function ArticlePublishControl({
  status,
  busy = false,
  mode = 'preview',
  onPublish,
  onDraft,
  saveHint,
}: {
  status: 'draft' | 'published'
  busy?: boolean
  mode?: 'editor' | 'preview'
  onPublish: () => void
  onDraft: () => void
  saveHint?: string
}) {
  if (mode === 'editor') {
    return (
      <div className="publish-control" role="group" aria-label="发布与保存操作">
        <span className={`badge ${status === 'published' ? 'badge-published' : 'badge-draft'}`}>
          {status === 'published' ? '已发布' : '草稿'}
        </span>
        {status === 'draft' ? (
          <>
            <button type="button" className="btn btn-sm" onClick={onDraft} disabled={busy} title={saveHint}>
              {busy ? '保存中…' : '保存草稿'}
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={onPublish} disabled={busy}>
              <Icon name="check-circle" size={14} />
              {busy ? '发布中…' : '保存并发布'}
            </button>
          </>
        ) : (
          <>
            <button type="button" className="btn btn-sm" onClick={onDraft} disabled={busy}>
              <Icon name="eye-slash" size={14} />转为草稿
            </button>
            <button type="button" className="btn btn-primary btn-sm" onClick={onPublish} disabled={busy} title={saveHint}>
              <Icon name="check" size={14} />
              {busy ? '更新中…' : '更新发布'}
            </button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="publish-control" role="group" aria-label="文章发布控制">
      <span className={`badge ${status === 'published' ? 'badge-published' : 'badge-draft'}`}>
        {status === 'published' ? '已发布' : '草稿'}
      </span>
      {status === 'draft' ? (
        <button type="button" className="btn btn-primary btn-sm" onClick={onPublish} disabled={busy}>
          <Icon name="check-circle" size={14} />发布此篇
        </button>
      ) : (
        <button type="button" className="btn btn-sm" onClick={onDraft} disabled={busy}>
          <Icon name="eye-slash" size={14} />转为草稿
        </button>
      )}
    </div>
  )
}

export function ProjectPublishControl({
  status,
  draftCount = 0,
  busy = false,
  onToggleProject,
  onPublishAllDrafts,
}: {
  status: 'draft' | 'published'
  draftCount?: number
  busy?: boolean
  onToggleProject: () => void
  onPublishAllDrafts?: () => void
}) {
  return (
    <div className="publish-control" role="group" aria-label="项目发布控制">
      <span className={`badge ${status === 'published' ? 'badge-published' : 'badge-draft'}`}>
        {status === 'published' ? '项目已发布' : '草稿项目'}
      </span>
      {draftCount > 0 && onPublishAllDrafts && (
        <button type="button" className="btn btn-sm" onClick={onPublishAllDrafts} disabled={busy}>
          <Icon name="check-circle" size={14} />发布全部草稿（{draftCount}）
        </button>
      )}
      <button
        type="button"
        className={`btn btn-sm${status === 'draft' ? ' btn-primary' : ''}`}
        onClick={onToggleProject}
        disabled={busy}
      >
        <Icon name={status === 'published' ? 'eye-slash' : 'eye'} size={14} />
        {status === 'published' ? '项目转草稿' : '发布项目'}
      </button>
    </div>
  )
}

export function DraftProjectBanner({
  projectName,
  busy = false,
  onPublishProject,
}: {
  projectName?: string
  busy?: boolean
  onPublishProject: () => void
}) {
  return (
    <div className="alert alert-info draft-project-banner" role="status">
      <Icon name="warning-circle" size={16} />
      <span>
        所属项目{projectName ? `「${projectName}」` : ''}目前为<strong>草稿状态</strong>，即使单篇文章已发布，访客在前台也暂时看不到。
      </span>
      <button type="button" className="btn btn-primary btn-sm" onClick={onPublishProject} disabled={busy}>
        {busy ? '发布中…' : '同时发布项目'}
      </button>
    </div>
  )
}
