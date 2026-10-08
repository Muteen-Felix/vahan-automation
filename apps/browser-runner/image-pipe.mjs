import {execFile} from 'node:child_process';

export function imageBytes(dataUrl) {
  if (typeof dataUrl !== 'string' || dataUrl.length > 1_000_000) throw new Error('Invalid image size.');
  const match = /^data:image\/(?:png|jpeg|gif|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(dataUrl);
  if (!match) throw new Error('Invalid image data URL.');
  const bytes = Buffer.from(match[1], 'base64');
  if (!bytes.length || bytes.length > 750_000 || bytes.toString('base64') !== match[1]) throw new Error('Invalid image bytes.');
  return bytes;
}

// Supply image bytes directly to the existing processor; never create a file.
export function runImageCommand(command, args, bytes, options = {}) {
  return new Promise((resolve, reject) => {
    const child = execFile(command, args, options, (error, stdout, stderr) => {
      if (error) reject(error);
      else resolve({stdout, stderr});
    });
    // execFile owns process errors/timeouts; avoid an unhandled EPIPE when it exits early.
    child.stdin.on('error', () => {});
    child.stdin.end(bytes);
  });
}
