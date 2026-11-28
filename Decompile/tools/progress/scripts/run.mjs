#!/usr/bin/env node
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const mode = process.argv[2] === 'start' ? 'start' : 'dev';
const override = process.env.SMR_PROGRESS_PORT;
const candidates = override ? [Number(override)] : [3000, 3001];

if (candidates.some((port) => !Number.isInteger(port) || port < 1 || port > 65535)) {
  console.error(`Invalid SMR_PROGRESS_PORT: ${override}`);
  process.exit(1);
}

function canBind(port, host) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once('error', (error) => {
      // Another family being unavailable is not the same as a port conflict.
      resolve(error.code !== 'EADDRINUSE');
    });
    server.listen({ port, host, exclusive: true }, () => {
      server.close(() => resolve(true));
    });
  });
}

function isListening(port, host) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host });
    const finish = (listening) => {
      socket.destroy();
      resolve(listening);
    };
    socket.setTimeout(500, () => finish(false));
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
  });
}

async function isFree(port) {
  // A bind probe alone can be fooled by SO_REUSEPORT listeners, so also ask
  // both loopback addresses whether something already answers on the port.
  const [ipv4Answers, ipv6Answers, ipv4Binds, ipv6Binds] = await Promise.all([
    isListening(port, '127.0.0.1'),
    isListening(port, '::1'),
    canBind(port, '127.0.0.1'),
    canBind(port, '::1'),
  ]);
  return !ipv4Answers && !ipv6Answers && ipv4Binds && ipv6Binds;
}

let port = null;
for (const candidate of candidates) {
  if (await isFree(candidate)) {
    port = candidate;
    break;
  }
}

if (port === null) {
  console.error(
    `No free port. Tried ${candidates.join(', ')}. Stop the process using it or set SMR_PROGRESS_PORT.`,
  );
  process.exit(1);
}

const nextBin = path.join(appRoot, 'node_modules', 'next', 'dist', 'bin', 'next');
const child = spawn(
  process.execPath,
  [nextBin, mode, '--hostname', 'localhost', '--port', String(port)],
  { cwd: appRoot, env: process.env, stdio: 'inherit' },
);

child.on('error', (error) => {
  console.error(`Failed to start Next.js: ${error.message}`);
  process.exit(1);
});

child.on('exit', (code) => {
  process.exit(code ?? 0);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}

console.log(`\n  SMR decomp progress → http://localhost:${port}\n`);
