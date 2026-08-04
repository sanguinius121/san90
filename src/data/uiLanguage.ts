export type UiLanguage = 'en' | 'vi'

export const UI_LANGUAGE_STORAGE_KEY = 'san90.ui.language'
export const DEFAULT_UI_LANGUAGE: UiLanguage = 'en'

export function isUiLanguage(value: unknown): value is UiLanguage {
  return value === 'en' || value === 'vi'
}

export function readStoredUiLanguage(): UiLanguage {
  try {
    const stored = window.localStorage.getItem(UI_LANGUAGE_STORAGE_KEY)
    return isUiLanguage(stored) ? stored : DEFAULT_UI_LANGUAGE
  } catch {
    return DEFAULT_UI_LANGUAGE
  }
}

export function persistUiLanguage(language: UiLanguage): void {
  try {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, language)
  } catch {
    // Language selection remains usable when browser storage is unavailable.
  }
}
