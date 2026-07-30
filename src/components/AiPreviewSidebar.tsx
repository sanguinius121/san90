import { AiImagePreview } from './controls/AiImagePreview'

export function AiPreviewSidebar({ onResetLayout }: { onResetLayout?: () => void } = {}) {
  return (
    <aside className="control-sidebar ai-preview-sidebar">
      <div className="sidebar-title">
        <div><b>AI IMAGE PREVIEW</b><span>LATEST AI INPUT</span></div>
        <div className="sidebar-title-actions">
          <button type="button" onClick={onResetLayout} disabled={!onResetLayout} title="Reset right dock width">Reset layout</button>
        </div>
      </div>
      <div className="sidebar-scroll">
        <AiImagePreview />
      </div>
    </aside>
  )
}
