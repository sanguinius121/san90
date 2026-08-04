import { AiImagePreview } from './controls/AiImagePreview'

export function AiPreviewSidebar({ onResetLayout }: { onResetLayout?: () => void } = {}) {
  return (
    <aside className="control-sidebar ai-preview-sidebar">
      <div className="sidebar-title">
        <div><b>XEM TRƯỚC ẢNH AI</b></div>
        <div className="sidebar-title-actions">
          <button type="button" onClick={onResetLayout} disabled={!onResetLayout} title="Đặt lại chiều rộng bảng điều khiển">Đặt lại bố cục</button>
        </div>
      </div>
      <div className="sidebar-scroll">
        <AiImagePreview />
      </div>
    </aside>
  )
}
