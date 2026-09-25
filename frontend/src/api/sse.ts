import { ApiError, rawRequest, request } from './client';
import type { AskAnswer, AskProgress } from './types';

export interface SSEMessage {
  event: string;
  data: string;
  id?: string;
}

/**
 * Incremental parser for the text/event-stream wire format (WHATWG HTML §9.2).
 * Feed it arbitrary chunks (they may split lines or even CRLF pairs); it yields complete messages.
 */
export class SSEParser {
  private buffer = '';
  private event = '';
  private data: string[] = [];
  private id: string | undefined;
  private pendingCR = false;

  push(chunk: string): SSEMessage[] {
    const out: SSEMessage[] = [];
    let text = chunk;
    if (this.pendingCR && text.startsWith('\n')) text = text.slice(1);
    this.pendingCR = false;
    this.buffer += text;
    // Split on CRLF, LF or CR. A trailing lone CR may be the first half of a CRLF split across chunks.
    const lines = this.buffer.split(/\r\n|\n|\r/);
    this.buffer = lines.pop() ?? '';
    if (this.buffer === '' && /\r$/.test(text)) this.pendingCR = true;
    for (const line of lines) {
      const msg = this.line(line);
      if (msg) out.push(msg);
    }
    return out;
  }

  /** Flush at end of stream (a final message without the blank-line terminator is dispatched). */
  end(): SSEMessage[] {
    const out: SSEMessage[] = [];
    if (this.buffer) {
      const msg = this.line(this.buffer);
      this.buffer = '';
      if (msg) out.push(msg);
    }
    const last = this.dispatch();
    if (last) out.push(last);
    return out;
  }

  private line(line: string): SSEMessage | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null; // comment / keep-alive ping
    const idx = line.indexOf(':');
    const field = idx === -1 ? line : line.slice(0, idx);
    let value = idx === -1 ? '' : line.slice(idx + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.event = value;
    else if (field === 'data') this.data.push(value);
    else if (field === 'id') this.id = value;
    return null;
  }

  private dispatch(): SSEMessage | null {
    if (this.data.length === 0) {
      this.event = '';
      return null;
    }
    const msg: SSEMessage = { event: this.event || 'message', data: this.data.join('\n') };
    if (this.id !== undefined) msg.id = this.id;
    this.event = '';
    this.data = [];
    return msg;
  }
}

export interface AskRequest {
  question: string;
  session_id?: string | null;
  landscape_id?: string | null;
}

export interface AskStreamHandlers {
  onProgress?: (p: AskProgress) => void;
  signal?: AbortSignal;
}

/**
 * POST /ask/stream with fetch + ReadableStream (EventSource cannot POST or send a bearer token).
 * Resolves with the final answer. Falls back to the non-streaming POST /ask when the stream is
 * unavailable (no ReadableStream support, proxy stripping the body, or the stream closing early).
 */
export async function askStream(body: AskRequest, handlers: AskStreamHandlers = {}): Promise<AskAnswer> {
  const payload = { question: body.question, session_id: body.session_id || undefined, landscape_id: body.landscape_id || undefined };
  let res: Response;
  try {
    res = await rawRequest('/ask/stream', {
      method: 'POST',
      body: payload,
      headers: { Accept: 'text/event-stream' },
      signal: handlers.signal,
    });
  } catch (e) {
    // Auth, validation and rate-limit errors are real answers; only fall back for transport issues.
    if (e instanceof ApiError && e.status !== 0 && e.status !== 404 && e.status !== 405 && e.status < 500) throw e;
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    return askOnce(payload, handlers.signal);
  }
  if (!res.body || typeof res.body.getReader !== 'function') return askOnce(payload, handlers.signal);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  const state: { answer: AskAnswer | null } = { answer: null };

  const handle = (m: SSEMessage): void => {
    let data: unknown;
    try {
      data = JSON.parse(m.data);
    } catch {
      return;
    }
    if (m.event === 'progress') handlers.onProgress?.(data as AskProgress);
    else if (m.event === 'answer') state.answer = data as AskAnswer;
    else if (m.event === 'error') {
      const msg = (data as { message?: string }).message ?? 'The answer could not be generated.';
      throw new ApiError(500, 'ask_stream_error', msg);
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const m of parser.push(decoder.decode(value, { stream: true }))) handle(m);
    if (state.answer) {
      // The server closes right after `answer`; stop reading promptly.
      void reader.cancel().catch(() => undefined);
      break;
    }
  }
  if (!state.answer) for (const m of parser.end()) handle(m);
  return state.answer ?? askOnce(payload, handlers.signal);
}

export function askOnce(body: AskRequest, signal?: AbortSignal): Promise<AskAnswer> {
  return request<AskAnswer>('/ask', { method: 'POST', body, signal });
}
