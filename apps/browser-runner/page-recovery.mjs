/** Retire a damaged document without letting a stuck browser close block its lane. */
export async function retireReportPage(page, timeout = 3000) {
  if (!page || page.isClosed()) return;
  let timer;
  try {
    await Promise.race([
      page.close().catch(() => {}),
      new Promise(resolve => {timer = setTimeout(resolve, timeout);}),
    ]);
  } finally {clearTimeout(timer);}
}

/** Retry read-only document setup after navigation; never repeat a form submission. */
export async function stableDocumentRead(page, read, timeout = 15000) {
  const deadline = Date.now() + timeout;
  for (;;) {
    try {
      await page.waitForLoadState('domcontentloaded', {timeout: Math.max(1, deadline - Date.now())});
      return await read();
    } catch (error) {
      if (!/Execution context was destroyed|Cannot find context with specified id/i.test(error.message)) throw error;
      if (Date.now() >= deadline) throw new Error('VAHAN_PAGE_NOT_READY: document kept navigating during setup.');
      await new Promise(resolve => setTimeout(resolve, Math.min(100, Math.max(1, deadline - Date.now()))));
    }
  }
}

export function isConnectionError(error) {
  return /net::ERR_(?:INTERNET_DISCONNECTED|NETWORK_CHANGED|NAME_NOT_RESOLVED|CONNECTION_(?:CLOSED|RESET|REFUSED|TIMED_OUT)|ADDRESS_UNREACHABLE)|ECONN(?:RESET|REFUSED)|ENETUNREACH|EHOSTUNREACH|ENOTFOUND|ETIMEDOUT|fetch failed|Failed to fetch/i.test(error?.message || '');
}
