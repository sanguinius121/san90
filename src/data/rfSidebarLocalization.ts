import { useCallback, useMemo } from 'react'
import localizationWorksheet from '../../docs/rf-sidebar-localization-worksheet.md?raw'
import { useUiPreferencesStore } from '../stores'
import type { UiLanguage } from './uiLanguage'

export type RfSidebarSection =
  | 'Header'
  | 'Frequency'
  | 'Frequency Scan'
  | 'RF Path'
  | 'Amplitude'
  | 'Bandwidth'
  | 'Detection'
  | 'Record'
  | 'Playback'
  | 'Common'
  | 'Dynamic'

interface LocalizationEntry {
  translation: string
  hint: string
}

type TemplateValues = Readonly<Record<string, string | number>>

function worksheetSection(heading: string): RfSidebarSection | null {
  const named = heading.match(/Section `([^`]+)`/u)?.[1]
  if (named) return named as RfSidebarSection
  if (heading.includes('Header của sidebar')) return 'Header'
  if (heading.includes('Thuật ngữ dùng chung')) return 'Common'
  if (heading.includes('Nội dung động')) return 'Dynamic'
  return null
}

export function parseRfSidebarWorksheet(markdown: string): Map<string, LocalizationEntry> {
  const entries = new Map<string, LocalizationEntry>()
  const lines = markdown.split(/\r?\n/u)
  let section: RfSidebarSection | null = null
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    if (line.startsWith('## ')) {
      section = worksheetSection(line.slice(3))
      continue
    }
    const match = line.match(/^### `(.+)`$/u)
    if (!match || !section) continue
    let translation = ''
    let hint = ''
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const field = lines[cursor]
      if (field.startsWith('## ') || field.startsWith('### ')) break
      if (field.startsWith('- Việt hóa thuật ngữ:')) {
        translation = field.slice('- Việt hóa thuật ngữ:'.length).trim()
      } else if (field.startsWith('- Gợi ý:')) {
        hint = field.slice('- Gợi ý:'.length).trim()
      }
    }
    entries.set(`${section}\u0000${match[1]}`, { translation, hint })
  }
  return entries
}

const worksheetEntries = parseRfSidebarWorksheet(localizationWorksheet)

function entry(section: RfSidebarSection, source: string): LocalizationEntry | undefined {
  const contextual = worksheetEntries.get(`${section}\u0000${source}`)
  if (contextual) return contextual
  return worksheetEntries.get(`Common\u0000${source}`)
}

function interpolate(template: string, values: TemplateValues = {}): string {
  return template.replace(/\{([^}]+)\}/gu, (placeholder, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : placeholder,
  )
}

export function localizeRfSidebar(
  language: UiLanguage,
  section: RfSidebarSection,
  source: string,
  values: TemplateValues = {},
): string {
  if (language === 'en') return interpolate(source, values)
  const translation = entry(section, source)?.translation
  return interpolate(translation || source, values)
}

export function rfSidebarHint(
  language: UiLanguage,
  section: RfSidebarSection,
  source: string,
  values: TemplateValues = {},
): string | undefined {
  if (language === 'en') return undefined
  const hint = entry(section, source)?.hint
  return hint ? interpolate(hint, values) : undefined
}

export function useRfSidebarLocalization(section: RfSidebarSection) {
  const language = useUiPreferencesStore(state => state.language)
  const t = useCallback(
    (source: string, values: TemplateValues = {}) =>
      localizeRfSidebar(language, section, source, values),
    [language, section],
  )
  const hint = useCallback(
    (source: string, values: TemplateValues = {}) =>
      rfSidebarHint(language, section, source, values),
    [language, section],
  )
  return useMemo(() => ({ language, t, hint }), [language, t, hint])
}
