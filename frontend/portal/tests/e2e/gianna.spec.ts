import { expect, test } from '@playwright/test';

test('entrada administrativa explícita y rutas desconocidas bloqueadas', async ({ page }) => {
  const login = await page.goto('/admin/login');
  expect(login?.status()).toBe(200);
  await expect(page.getByRole('textbox', { name: 'Correo electrónico', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/login$/);
  for (const path of ['/admin/no-existe', '/admin/index.html']) {
    const response = await page.goto(path);
    expect(response?.status()).toBe(404);
    await expect(page.getByRole('textbox', { name: 'Correo electrónico', exact: true })).toHaveCount(0);
  }
});

const conversation = (page: import('@playwright/test').Page) => page.frameLocator('.gianna-agent-frame');
const event = (name: string, data: unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;

test('Gianna conserva la página original y los enlaces editoriales sin JavaScript', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, baseURL });
  const page = await context.newPage();
  await page.goto('/');
  await page.locator('.gianna-promo').getByRole('link', { name: /preguntale a gianna/i }).click();
  await expect(page).toHaveURL(/\/gianna\/$/);
  await expect(page.getByRole('heading', { level: 1, name: /conocé lavalleja con gianna/i })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ver fuentes editoriales' })).toHaveAttribute('href', '/fuentes/');
  await expect(page.locator('.gianna-agent-frame')).toHaveAttribute('src', '/_gianna/?theme=invest');
  expect(await page.locator('noscript').textContent()).toContain('El chat necesita JavaScript.');
  await expect(page.getByText(/La conversación se guarda únicamente en este navegador/)).toBeVisible();
  await context.close();
});

test('el agente conserva mensajes, SSE, fuentes, herramientas y sugerencias dentro del portal', async ({ page }) => {
  const requests: { messages: { role: string; content: string }[] }[] = [];
  const apiPaths: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiPaths.push(new URL(request.url()).pathname);
  });
  await page.route('**/api/chat', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers().authorization).toBeUndefined();
    requests.push(route.request().postDataJSON());
    await route.fulfill({
      contentType: 'text/event-stream',
      body: event('status', 'Buscando en la guía…') + event('sources', ['Guía · Turismo [S12]']) +
        event('token', 'Texto provisional') + event('reset', '') + event('status', 'Revisando la ficha O12…') +
        event('token', '**Respuesta** de prueba ') + event('token', 'con fuentes [S12].') +
        event('tools', ['Ficha de oportunidad']) + event('suggest', [{ label: 'Profundizar', text: 'Contame más sobre esta opción' }]) + event('done', ''),
    });
  });
  await page.goto('/gianna/');
  const chat = conversation(page);
  await expect(chat.getByRole('heading', { name: 'Gianna', exact: true })).toBeVisible();
  const input = chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…');
  await input.fill('Quiero evaluar un alojamiento turístico');
  await chat.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(chat.locator('.prose-chat').last()).toContainText('Respuesta de prueba con fuentes [S12].');
  await expect(chat.getByText('Texto provisional', { exact: true })).toHaveCount(0);
  await expect(chat.getByText('Ficha de oportunidad', { exact: true })).toBeVisible();
  await chat.getByText('Basado en la guía', { exact: true }).click();
  await expect(chat.getByText('Guía · Turismo [S12]', { exact: true })).toBeVisible();
  expect(requests[0]).toEqual({ messages: [{ role: 'user', content: 'Quiero evaluar un alojamiento turístico' }] });
  await chat.getByRole('button', { name: 'Profundizar', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].messages).toEqual([
    { role: 'user', content: 'Quiero evaluar un alojamiento turístico' },
    { role: 'assistant', content: '**Respuesta** de prueba con fuentes [S12].' },
    { role: 'user', content: 'Contame más sobre esta opción' },
  ]);
  await expect(chat.getByRole('button', { name: 'Enviar', exact: true })).toBeVisible();
  await page.reload();
  await expect(conversation(page).getByText('Quiero evaluar un alojamiento turístico', { exact: true })).toBeVisible();
  await expect(conversation(page).getByText('Contame más sobre esta opción', { exact: true })).toBeVisible();
  await conversation(page).getByRole('button', { name: 'Nueva conversación' }).click();
  await expect(conversation(page).getByText('Quiero evaluar un alojamiento turístico', { exact: true })).toHaveCount(0);
  await expect.poll(async () => JSON.parse(await page.evaluate(() => localStorage.getItem('gianna-chat-v1')!))).toEqual([]);
  expect(apiPaths.every((path) => ['/api/chat', '/api/chat/session', '/api/chat/quota'].includes(path))).toBe(true);
});

test('detener y volver a enviar conserva el control de la conversación', async ({ page }) => {
  await page.route('**/api/chat', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({ contentType: 'text/event-stream', body: event('token', 'Respuesta final') + event('done', '') }).catch(() => {});
  });
  await page.goto('/gianna/');
  const chat = conversation(page);
  const input = chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…');
  await expect(input).toHaveAttribute('maxlength', '2000');
  await input.fill('Primera línea');
  await input.press('Shift+Enter');
  await expect(input).toHaveValue('Primera línea\n');
  await input.press('Enter');
  await chat.getByRole('button', { name: 'Detener', exact: true }).click();
  await expect(chat.getByText('Respuesta detenida.', { exact: true })).toBeVisible();
  await expect(input).toBeFocused();
  await input.fill('Otra consulta');
  await input.press('Enter');
  await expect(chat.getByText('Respuesta final', { exact: true })).toBeVisible();
});

test('los errores de la API siguen visibles y permiten reintentar', async ({ page }) => {
  let attempt = 0;
  await page.route('**/api/chat', async (route) => {
    attempt += 1;
    if (attempt === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Base de conocimiento temporalmente no disponible.' }) });
    expect(route.request().postDataJSON().messages).toEqual([
      { role: 'user', content: 'Mi proyecto' }, { role: 'user', content: 'Reintentar' },
    ]);
    return route.fulfill({ contentType: 'text/event-stream', body: event('token', 'Ahora sí') + event('done', '') });
  });
  await page.goto('/gianna/');
  const chat = conversation(page);
  const input = chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…');
  await input.fill('Mi proyecto');
  await input.press('Enter');
  await expect(chat.getByText('Base de conocimiento temporalmente no disponible.', { exact: true })).toBeVisible();
  await input.fill('Reintentar');
  await input.press('Enter');
  await expect(chat.getByText('Ahora sí', { exact: true })).toBeVisible();
});

test('el chat integrado cabe en móvil y sólo se abre desde el portal; admin sigue disponible', async ({ page }) => {
  await page.goto('/gianna/');
  await expect(conversation(page).getByRole('button', { name: 'Nueva conversación' })).toBeVisible();
  const bounds = await page.locator('.gianna-agent-frame').boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  const frame = page.frames().find((item) => item.url().includes('/_gianna/'))!;
  const layout = await frame.evaluate(() => {
    const messages = document.querySelector('main')!;
    return { scroll: document.documentElement.scrollWidth, width: window.innerWidth,
      messagesScroll: messages.scrollWidth, messagesWidth: messages.clientWidth,
      theme: document.documentElement.dataset.theme };
  });
  expect(layout.scroll).toBeLessThanOrEqual(layout.width);
  expect(layout.messagesScroll).toBeLessThanOrEqual(layout.messagesWidth);
  expect(layout.theme).toBe('invest');
  await frame.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    document.querySelector('main')!.scrollTop = 0;
  });
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: `reports/captures/gianna-${test.info().project.name}.png`, fullPage: true });
  await page.goto('/chat/');
  await expect(page).toHaveURL(/\/gianna\/$/);
  await expect(conversation(page).getByRole('heading', { name: 'Gianna', exact: true })).toBeVisible();
  const direct = await page.goto('/_gianna/?theme=invest');
  expect(direct!.status()).toBe(404);
  await expect(page.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…')).toHaveCount(0);
  await page.goto('/admin');
  await expect(page.getByRole('textbox', { name: 'Correo electrónico', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…')).toHaveCount(0);
  await expect(page.getByRole('link', { name: /volver al chat de gianna/i })).toHaveAttribute('href', '/gianna/');
  await page.getByRole('link', { name: /volver al chat de gianna/i }).click();
  await expect(conversation(page).getByRole('heading', { name: 'Gianna', exact: true })).toBeVisible();
});

test('el cupo bloquea el envío, muestra la espera y se conserva al recargar y borrar el chat', async ({ page }) => {
  let exhausted = false;
  await page.route('**/api/chat/quota', (route) => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ limit: 20, remaining: exhausted ? 0 : 1, retry_after: exhausted ? 600 : 0 }) }));
  await page.route('**/api/chat', (route) => {
    exhausted = true;
    return route.fulfill({ contentType: 'text/event-stream', headers: { 'X-Chat-Remaining': '0', 'X-Chat-Retry-After': '600' },
      body: event('token', 'Respuesta número veinte') + event('done', '') });
  });
  await page.goto('/gianna/');
  const chat = conversation(page);
  await expect(chat.getByRole('status')).toContainText('1 consultas disponibles');
  await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill('Consulta veinte');
  await chat.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(chat.getByText('Respuesta número veinte', { exact: true })).toBeVisible();
  await expect(chat.getByRole('status')).toContainText('Alcanzaste las 20 consultas');
  await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill('Otra consulta');
  await expect(chat.getByRole('button', { name: 'Enviar', exact: true })).toBeDisabled();
  const id = await page.evaluate(() => localStorage.getItem('gianna-browser-v1'));
  await chat.getByRole('button', { name: 'Nueva conversación' }).click();
  await expect(chat.getByRole('status')).toContainText('Alcanzaste las 20 consultas');
  await page.reload();
  await expect(conversation(page).getByRole('status')).toContainText('Alcanzaste las 20 consultas');
  expect(await page.evaluate(() => localStorage.getItem('gianna-browser-v1'))).toBe(id);
});

test('429 sincroniza la espera del servidor y un fallo de conexión impide enviar', async ({ page }) => {
  await page.route('**/api/chat', (route) => route.fulfill({ status: 429, contentType: 'application/json',
    headers: { 'Retry-After': '600' }, body: JSON.stringify({ detail: 'Alcanzaste las 20 consultas. Esperá 10 minutos para continuar.' }) }));
  await page.goto('/gianna/');
  const chat = conversation(page);
  await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill('Consulta');
  await chat.getByRole('button', { name: 'Enviar', exact: true }).click();
  await expect(chat.getByRole('status')).toContainText('Alcanzaste las 20 consultas');
  await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill('Reintento');
  await expect(chat.getByRole('button', { name: 'Enviar', exact: true })).toBeDisabled();
  await page.route('**/api/chat/quota', (route) => route.abort());
  await page.reload();
  await expect(conversation(page).getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…')).toBeDisabled();
  await expect(conversation(page).getByRole('button', { name: 'Enviar', exact: true })).toBeDisabled();
});

test('al terminar la espera consulta el cupo del servidor y permite continuar', async ({ page }) => {
  let unlock = 0;
  await page.route('**/api/chat/quota', (route) => {
    if (!unlock) unlock = Date.now() + 1500;
    const retry = Math.max(0, Math.ceil((unlock - Date.now()) / 1000));
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ remaining: retry ? 0 : 20, retry_after: retry }) });
  });
  await page.goto('/gianna/');
  const chat = conversation(page);
  await expect(chat.getByRole('status')).toContainText('Alcanzaste las 20 consultas');
  await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill('Continuar');
  await expect(chat.getByRole('button', { name: 'Enviar', exact: true })).toBeDisabled();
  await expect(chat.getByRole('status')).toContainText('20 consultas disponibles');
  await expect(chat.getByRole('button', { name: 'Enviar', exact: true })).toBeEnabled();
});
