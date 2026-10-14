import { useSyncExternalStore } from 'react'
import { api } from './api'

const STORAGE_KEY = 'tickflow.ai.selectedModel'

let models: string[] = []
let modelsLoaded = false
let modelsLoading = false
let selectedModel = ''
const listeners = new Set<() => void>()

function emit() { listeners.forEach(listener => listener()) }
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

let snapshot = { models, selected: selectedModel }
function rebuildSnapshot() { snapshot = { models, selected: selectedModel } }
function getSnapshot() { return snapshot }

try {
  selectedModel = localStorage.getItem(STORAGE_KEY) ?? ''
} catch { /* SSR / private browsing */ }
rebuildSnapshot()

export async function loadModels(force = false): Promise<void> {
  if (modelsLoading || (modelsLoaded && !force)) return
  modelsLoading = true
  try {
    const response = await api.aiModels()
    models = response.models ?? []
    modelsLoaded = true
    rebuildSnapshot()
    emit()
  } catch { /* keep current selection and fall back to the configured default */ }
  finally { modelsLoading = false }
}

export function selectModel(model: string) {
  selectedModel = model || ''
  try {
    if (selectedModel) localStorage.setItem(STORAGE_KEY, selectedModel)
    else localStorage.removeItem(STORAGE_KEY)
  } catch { /* persistence is optional */ }
  rebuildSnapshot()
  emit()
}

export function useAiModels() {
  const current = useSyncExternalStore(subscribe, getSnapshot, () => snapshot)
  if (!modelsLoaded && !modelsLoading) void loadModels()
  return {
    models: current.models,
    selected: current.selected,
    defaultModel: current.models[0] ?? '',
    select: selectModel,
  }
}

export function getSelectedModel(): string {
  return selectedModel
}
