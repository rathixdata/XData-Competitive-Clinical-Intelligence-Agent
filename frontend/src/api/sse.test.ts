import { afterEach, describe, expect, it, vi } from 'vitest';
import { SSEParser, askStream } from './sse';
import { jsonResponse } from '../test/utils';

afterEach(() => vi.unstubAllGlobals());

describe('SSEParser', () => {
  it('parses events split across arbitrary chunks and CRLF boundaries', () => {
    const p = new SSEParser();
    const wire = 'event: progress\r\ndata: {"stage":"planned"}\r\n\r\n: ping\r\n\r\nevent: answer\r\ndata: {"a":1}\r\n\r\n';
    const out = [];
    // feed one character at a time: worst-case fragmentation (incl. "\r" | "\n" splits)
    for (const ch of wire) out.push(...p.push(ch));
    out.push(...p.end());
    expect(out).toEqual([
      { event: 'progress', data: '{"stage":"planned"}' },
      { event: 'answer', data: '{"a":1}' },
    ]);
  });

  it('joins multi-line data, defaults the event name, keeps ids and flushes a trailing event', () => {
    const p = new SSEParser();
    const out = p.push('id: 7\ndata: line1\ndata: line2\n\ndata:no-space');
    expect(out).toEqual([{ event: 'message', data: 'line1\nline2', id: '7' }]);
    expect(p.end()).toEqual([{ event: 'message', data: 'no-space', id: '7' }]);
  });

  it('ignores comments and events without data', () => {
    const p = new SSEParser();
    expect(p.push(': keep-alive\n\nevent: progress\n\n')).toEqual([]);
  });
});

function sseResponse(chunks: string[]): Response {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

const ANSWER = { session_id: 's1', turn_id: 't1', artifact_id: 'a1', question: 'q', answer: 'Two things changed.', statements: [], evidence: {}, sources: [], confidence: 'Medium', limitations: [], comparison_warning: '', abstained: false, generated_at: '2026-09-25T00:00:00Z', model_workflow_version: 'x' };

describe('askStream', () => {
  it('streams progress stages then resolves with the answer', async () => {
    const body = [
      'event: progress\r\ndata: {"stage": "planned"}\r\n\r\nevent: progress\r\ndata: {"stage": "retr',
      'ieved", "passages": 8}\r\n\r\nevent: progress\r\ndata: {"stage": "generated"}\r\n\r\n',
      `event: progress\r\ndata: {"stage": "validated"}\r\n\r\nevent: answer\r\ndata: ${JSON.stringify(ANSWER)}\r\n\r\n`,
    ];
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(body));
    vi.stubGlobal('fetch', fetchMock);
    const stages: string[] = [];
    const out = await askStream({ question: 'What changed this week?' }, { onProgress: (p) => stages.push(p.stage) });
    expect(stages).toEqual(['planned', 'retrieved', 'generated', 'validated']);
    expect(out.answer).toBe('Two things changed.');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/ask/stream');
    expect(init.method).toBe('POST');
  });

  it('surfaces an error event as an exception', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(['event: error\ndata: {"message": "budget exceeded"}\n\n'])));
    await expect(askStream({ question: 'x?' })).rejects.toThrow('budget exceeded');
  });

  it('falls back to POST /ask when the stream ends without an answer', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(sseResponse(['event: progress\ndata: {"stage":"planned"}\n\n']))
      .mockResolvedValueOnce(jsonResponse(ANSWER));
    vi.stubGlobal('fetch', fetchMock);
    const out = await askStream({ question: 'x?' });
    expect(out.artifact_id).toBe('a1');
    expect((fetchMock.mock.calls[1] as [string])[0]).toBe('/api/v1/ask');
  });

  it('falls back to POST /ask when the streaming endpoint is unavailable', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ error: { code: 'x', message: 'bad gateway' } }, 502))
      .mockResolvedValueOnce(jsonResponse(ANSWER));
    vi.stubGlobal('fetch', fetchMock);
    await expect(askStream({ question: 'x?' })).resolves.toMatchObject({ turn_id: 't1' });
  });

  it('does not fall back on client errors such as rate limiting', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'rate_limited', message: 'rate limit exceeded (20/min)' } }, 429));
    vi.stubGlobal('fetch', fetchMock);
    await expect(askStream({ question: 'x?' })).rejects.toThrow('rate limit exceeded');
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
