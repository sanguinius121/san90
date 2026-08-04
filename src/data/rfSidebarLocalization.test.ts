import { describe, expect, it } from 'vitest'
import {
  localizeRfSidebar,
  parseRfSidebarWorksheet,
  rfSidebarHint,
} from './rfSidebarLocalization'

describe('RF sidebar localization worksheet', () => {
  it('parses section-scoped translations and hints', () => {
    const parsed = parseRfSidebarWorksheet(`## 2. Section \`Frequency\`
### \`Frequency\`
- Việt hóa thuật ngữ: Tần số
- Gợi ý: Chọn tần số
`)
    expect(parsed.get('Frequency\u0000Frequency')).toEqual({
      translation: 'Tần số',
      hint: 'Chọn tần số',
    })
  })

  it('leaves English and blank Vietnamese terms unchanged', () => {
    expect(localizeRfSidebar('en', 'Frequency', 'Frequency')).toBe('Frequency')
    expect(localizeRfSidebar('vi', 'Frequency', 'GHz')).toBe('GHz')
  })

  it('keeps duplicate terms scoped to their sidebar section', () => {
    expect(localizeRfSidebar('vi', 'Frequency', 'Frequency')).toBe('CÀI ĐẶT TẦN SỐ')
    expect(localizeRfSidebar('vi', 'Bandwidth', 'Frequency')).toBe('Tần số')
    expect(localizeRfSidebar('vi', 'Playback', 'Off')).toBe('Off')
    expect(localizeRfSidebar('vi', 'Amplitude', 'Off')).toBe('Tắt')
  })

  it('interpolates variables and exposes only filled Vietnamese hints', () => {
    expect(localizeRfSidebar('vi', 'Frequency Scan', 'Dwell ≥ {seconds}s · default step 10 MHz', { seconds: 0.5 }))
      .toBe('Thời gian ≥ 0.5s · Bước tần mặc định 10 MHz')
    expect(rfSidebarHint('vi', 'Frequency', 'Center frequency')).toContain('2440 MHz')
    expect(rfSidebarHint('vi', 'Frequency', 'GHz')).toBeUndefined()
    expect(rfSidebarHint('en', 'Frequency', 'Center frequency')).toBeUndefined()
  })
})
