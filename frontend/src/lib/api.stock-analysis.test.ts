// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('@/components/Toast', () => ({ toast: vi.fn() }))

afterEach(() => vi.unstubAllGlobals())

it('sends the selected model with stock analysis requests', async () => {
  let payload: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    payload = JSON.parse(String(init?.body)) as Record<string, unknown>
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"type":"done"}\n'))
        controller.close()
      },
    })
    return new Response(stream, { status: 200 })
  }))

  const { api } = await import('./api')
  const chunks = []
  for await (const chunk of api.stockAnalyzeStream('600000.SH', 'cash flow', 'gpt-6-astra')) {
    chunks.push(chunk)
  }

  expect(chunks).toEqual([{ type: 'done' }])
  expect(payload).toEqual({ symbol: '600000.SH', focus: 'cash flow', model: 'gpt-6-astra' })
})

it('stores the reported model with a stock analysis report', async () => {
  let payload: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    payload = JSON.parse(String(init?.body)) as Record<string, unknown>
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }))

  const { api } = await import('./api')
  await api.stockAnalysisReportSave({
    symbol: '600000.SH',
    model: 'gpt-6-astra',
    content: 'report',
  })

  expect(payload?.model).toBe('gpt-6-astra')
})
