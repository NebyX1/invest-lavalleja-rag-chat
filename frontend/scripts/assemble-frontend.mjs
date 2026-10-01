/** Join the original Astro portal with the existing, independently built Vite client. */
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const output = new URL('../dist/', import.meta.url);
const portal = new URL('../portal/dist/', import.meta.url);
const chatEntry = await readFile(new URL('index.html', output));
for (const entry of ['_gianna', 'admin']) {
  await mkdir(new URL(`${entry}/`, output), { recursive: true });
  await writeFile(new URL(`${entry}/index.html`, output), chatEntry);
}
await cp(fileURLToPath(portal), fileURLToPath(output), { recursive: true });
console.log('Portal y agente integrados en frontend/dist (/, /gianna/, /admin).');
