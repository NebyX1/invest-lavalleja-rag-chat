import { expect, test } from '@playwright/test';

async function submitLogin(page: import('@playwright/test').Page) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === '/api/admin/login' && response.request().method() === 'POST');
    await page.getByRole('button', { name: /ingresar|continuar|enviar código/i }).click();
    const response = await responsePromise;
    if (response.status() !== 429) {
      expect(response.ok()).toBe(true);
      await expect(page.getByLabel(/código/i)).toBeVisible();
      return;
    }
    // Todas las pruebas comparten la IP Docker: respetar el límite real del login.
    const retryAfter = Number(response.headers()['retry-after']);
    expect(retryAfter).toBe(60);
    await expect(page.getByRole('alert')).toContainText('Demasiados intentos');
    await new Promise((resolve) => setTimeout(resolve, (retryAfter + 1) * 1000));
  }
  throw new Error('El acceso sigue limitado después de Retry-After.');
}

test.describe('contenedores independientes como Coolify', () => {
  test.skip(process.env.DEPLOYMENT_TEST !== 'true', 'Requiere la simulación Docker con Ollama y SMTP aislados.');

  for (const [mode, url] of [['proxy', 'http://127.0.0.1:18080'], ['cors', 'http://127.0.0.1:18082']]) {
    test(`streaming real del agente por ${mode}, herramientas y persistencia local`, async ({ page, request }) => {
      const calls: string[] = [];
      page.on('request', (r) => { if (new URL(r.url()).pathname === '/api/chat') calls.push(r.url()); });
      await page.goto(`${url}/gianna/`);
      const chat = page.frameLocator('.gianna-agent-frame');
      await expect(chat.getByRole('status')).toContainText('consultas disponibles');
      await chat.getByPlaceholder('Escribí tu consulta sobre inversiones en Lavalleja…').fill(`Consulta de integración ${mode}`);
      await chat.getByRole('button', { name: 'Enviar', exact: true }).click();
      await expect(chat.getByText('O12: respuesta de integración con la guía de Invest Lavalleja.', { exact: true })).toBeVisible({ timeout: 30000 });
      await expect(chat.getByText('ficha de oportunidad', { exact: true })).toBeVisible();
      await expect(chat.getByRole('button', { name: /Profundizar en O12/ })).toBeVisible();
      expect(calls).toEqual([`${mode === 'cors' ? 'http://127.0.0.1:18010' : url}/api/chat`]);
      await page.reload();
      await expect(page.frameLocator('.gianna-agent-frame').getByText(`Consulta de integración ${mode}`, { exact: true })).toBeVisible();
      const denied = await request.post('http://127.0.0.1:18010/api/chat/session', {
        headers: { Origin: 'https://external.example' }, data: { browser_id: '00000000-0000-4000-8000-000000000001' },
      });
      expect(denied.status()).toBe(403);
    });

    test(`panel 2FA, cookies y CSRF a través de ${mode}`, async ({ page, request }) => {
      test.setTimeout(120_000);
      await page.goto(`${url}/admin`);
      await page.getByRole('textbox', { name: 'Correo electrónico', exact: true }).fill('qa@example.test');
      await page.getByLabel('Contraseña', { exact: true }).fill('Local-integration-password-2026!');
      await submitLogin(page);
      const codeInput = page.getByLabel(/código/i);
      await expect(codeInput).toBeVisible();
      const codes = (await (await request.get('http://127.0.0.1:18011/mail')).json()).codes;
      await codeInput.fill(codes.at(-1));
      await page.getByRole('button', { name: /verificar|confirmar|entrar/i }).click();
      await expect(page.getByRole('heading', { name: 'Base de conocimiento', exact: true })).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/$/);
      await expect(page.getByText('224', { exact: true }).first()).toBeVisible();
      const protectedResponse = await request.get('http://127.0.0.1:18010/api/admin/knowledge');
      expect(protectedResponse.status()).toBe(401);
      await page.getByRole('button', { name: 'Administradores', exact: true }).click();
      const editorEmail = `editor-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.test`;
      await page.getByRole('textbox', { name: 'Nombre', exact: true }).fill('Editor de prueba');
      await page.getByRole('textbox', { name: 'Correo', exact: true }).fill(editorEmail);
      await page.getByLabel('Contraseña inicial', { exact: true }).fill('Local-editor-password-2026!');
      await page.getByRole('combobox', { name: 'Rol', exact: true }).selectOption('false');
      await page.getByRole('button', { name: 'Crear administrador', exact: true }).click();
      const editorRow = page.getByRole('row').filter({ hasText: editorEmail });
      await expect(editorRow).toContainText('Editor de prueba');
      await editorRow.getByRole('button', { name: 'Hacer superadministrador', exact: true }).click();
      await expect(editorRow.getByRole('cell', { name: 'Superadministrador', exact: true })).toBeVisible();
      await editorRow.getByRole('button', { name: 'Quitar superadministrador', exact: true }).click();
      await expect(editorRow.getByRole('cell', { name: 'Administrador', exact: true })).toBeVisible();
      await page.getByRole('button', { name: /cerrar sesión|salir/i }).click();
      await expect(page.getByRole('textbox', { name: 'Correo electrónico', exact: true })).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/login$/);
      await page.getByRole('textbox', { name: 'Correo electrónico', exact: true }).fill(editorEmail);
      await page.getByLabel('Contraseña', { exact: true }).fill('Local-editor-password-2026!');
      await submitLogin(page);
      const editorCodes = (await (await request.get('http://127.0.0.1:18011/mail')).json()).codes;
      await page.getByLabel(/código/i).fill(editorCodes.at(-1));
      await page.getByRole('button', { name: /verificar|confirmar|entrar/i }).click();
      await expect(page.getByRole('heading', { name: 'Base de conocimiento', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Administradores', exact: true })).toHaveCount(0);
      await expect(page.getByRole('button', { name: 'Actividad', exact: true })).toHaveCount(0);
      await page.getByRole('button', { name: 'Mi cuenta', exact: true }).click();
      await expect(page.getByRole('heading', { name: 'Cambiar mi contraseña', exact: true })).toBeVisible();
      const usersUrl = mode === 'cors' ? 'http://127.0.0.1:18010/api/admin/users' : `${url}/api/admin/users`;
      expect((await page.request.get(usersUrl)).status()).toBe(403);
      await page.getByRole('button', { name: /cerrar sesión|salir/i }).click();
    });
  }
});
