import { expect, test } from '@playwright/test';

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
      await page.goto(`${url}/admin`);
      await page.getByRole('textbox', { name: 'Correo electrónico', exact: true }).fill('qa@example.test');
      await page.getByLabel('Contraseña', { exact: true }).fill('Local-integration-password-2026!');
      await page.getByRole('button', { name: /ingresar|continuar|enviar código/i }).click();
      const codeInput = page.getByLabel(/código/i);
      await expect(codeInput).toBeVisible();
      const codes = (await (await request.get('http://127.0.0.1:18011/mail')).json()).codes;
      await codeInput.fill(codes.at(-1));
      await page.getByRole('button', { name: /verificar|confirmar|entrar/i }).click();
      await expect(page.getByRole('heading', { name: 'Base de conocimiento', exact: true })).toBeVisible();
      await expect(page.getByText('224', { exact: true }).first()).toBeVisible();
      const protectedResponse = await request.get('http://127.0.0.1:18010/api/admin/knowledge');
      expect(protectedResponse.status()).toBe(401);
      await page.getByRole('button', { name: /cerrar sesión|salir/i }).click();
      await expect(page.getByRole('textbox', { name: 'Correo electrónico', exact: true })).toBeVisible();
    });
  }
});
