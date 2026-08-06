async function req(path, opts = {}) {
  let resp;
  try {
    resp = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  } catch (err) {
    return { status: 0, body: {} };
  }
  const body = await resp.json().catch(() => ({}));
  return { status: resp.status, body };
}

export const getItems = () => req("/api/items");
export const getMe = () => req("/api/me");
export const vote = (item_id, choice) =>
  req("/api/vote", { method: "POST", body: JSON.stringify({ item_id, choice }) });
export const suggest = (text) =>
  req("/api/suggest", { method: "POST", body: JSON.stringify({ text }) });
