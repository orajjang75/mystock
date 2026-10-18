import type { SettingsDocument, SettingsResponse } from '../../api/types'

/** The part of a settings response that PUT /api/settings takes (everything but the presets). */
export function toDocument(settings: SettingsResponse): SettingsDocument {
  const { presets, ...document } = settings
  void presets
  return document
}
