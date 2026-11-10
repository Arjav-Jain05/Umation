/**
 * Lightweight fetch and SSE wrapper for shorts-engine web UI.
 */

export async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    let errDetail = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      errDetail = errJson.detail || errJson.error?.message || errDetail;
    } catch (_) {}
    throw new Error(errDetail);
  }
  return await res.json();
}

export async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let errDetail = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      errDetail = errJson.detail || errJson.error?.message || errDetail;
    } catch (_) {}
    throw new Error(errDetail);
  }
  return await res.json();
}

export async function patchJSON(url, body) {
  const res = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let errDetail = `HTTP ${res.status}`;
    try {
      const errJson = await res.json();
      errDetail = errJson.detail || errJson.error?.message || errDetail;
    } catch (_) {}
    throw new Error(errDetail);
  }
  return await res.json();
}

/**
 * Open Server-Sent Events stream with automatic reconnect.
 */
export function openEvents(jobId, handlers) {
  let es = null;
  let closed = false;

  function connect() {
    if (closed) return;
    es = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/events`);

    es.addEventListener("progress", (e) => {
      try {
        const data = JSON.parse(e.data);
        handlers.onProgress?.(data);
      } catch (err) {
        console.error("Malformed progress SSE:", err);
      }
    });

    es.addEventListener("stage_done", (e) => {
      try {
        const data = JSON.parse(e.data);
        handlers.onStageDone?.(data);
      } catch (err) {
        console.error("Malformed stage_done SSE:", err);
      }
    });

    es.addEventListener("clip_update", (e) => {
      try {
        const data = JSON.parse(e.data);
        handlers.onClipUpdate?.(data);
      } catch (err) {
        console.error("Malformed clip_update SSE:", err);
      }
    });

    es.addEventListener("warning", (e) => {
      try {
        const data = JSON.parse(e.data);
        handlers.onWarning?.(data.message);
      } catch (err) {
        console.error("Malformed warning SSE:", err);
      }
    });

    es.addEventListener("error", (e) => {
      if (e.data) {
        try {
          const data = JSON.parse(e.data);
          handlers.onError?.(data);
        } catch (_) {}
      }
    });

    es.addEventListener("done", (e) => {
      try {
        const data = JSON.parse(e.data);
        handlers.onDone?.(data);
      } catch (err) {
        console.error("Malformed done SSE:", err);
      }
    });

    es.onerror = () => {
      es.close();
      if (!closed) {
        setTimeout(connect, 2000);
      }
    };
  }

  connect();

  return {
    close() {
      closed = true;
      es?.close();
    },
  };
}
