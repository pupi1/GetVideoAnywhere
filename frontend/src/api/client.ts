const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export type DownloadTask = {
  id: string;
  url: string;
  status: string;
  progress: number;
  format_id?: string;
  file_path?: string;
  error?: string;
};

async function unwrap<T>(res: Response): Promise<T> {
  const data = await res.json();
  if (!res.ok || data.success === false) {
    throw new Error(data.detail || data.message || "Request failed");
  }
  return data.data as T;
}

export async function parseVideo(url: string): Promise<any> {
  const res = await fetch(`${API_BASE}/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const data = await unwrap<any>(res);
  if (data?.thumbnail) {
    data.thumbnail = getThumbnailProxyLink(data.thumbnail);
  }
  return data;
}

export async function createDownload(url: string, format_id?: string): Promise<DownloadTask> {
  const res = await fetch(`${API_BASE}/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, format_id }),
  });
  return unwrap(res);
}

export async function createBatchDownloads(urls: string[], format_id?: string): Promise<DownloadTask[]> {
  const res = await fetch(`${API_BASE}/download/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls, format_id }),
  });
  return unwrap(res);
}

export async function listTasks(): Promise<DownloadTask[]> {
  const res = await fetch(`${API_BASE}/tasks`);
  return unwrap(res);
}

export async function summarizeText(text: string): Promise<{ summary: string; keywords: string }> {
  const res = await fetch(`${API_BASE}/ai/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  return unwrap(res);
}

export async function translateText(text: string, target_language: string): Promise<{ translated_text: string }> {
  const res = await fetch(`${API_BASE}/ai/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, target_language }),
  });
  return unwrap(res);
}

export function getDownloadLink(taskId: string): string {
  return `${API_BASE}/file/${taskId}`;
}

export function getThumbnailProxyLink(sourceUrl: string): string {
  let normalized = sourceUrl.trim();
  if (normalized.startsWith("//")) {
    normalized = `https:${normalized}`;
  }
  if (!/^https?:\/\//i.test(normalized)) {
    return "";
  }
  return `${API_BASE}/thumbnail?url=${encodeURIComponent(normalized)}`;
}
