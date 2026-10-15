import assert from 'node:assert/strict';
import {mkdtemp, readdir, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {imageBytes, runImageCommand} from './image-pipe.mjs';

const directory=await mkdtemp(join(tmpdir(),'vahan-image-pipe-'));
try {
  const a=Buffer.from('ordinary image bytes A'), b=Buffer.from('ordinary image bytes B');
  assert.deepEqual(imageBytes('data:image/png;base64,'+a.toString('base64')),a);
  for(const invalid of ['data:image/png;base64,?', 'data:image/png;base64,', 'data:text/plain;base64,QQ==', 'data:image/png;base64,AAA']) {
    assert.throws(()=>imageBytes(invalid));
  }
  const script="const chunks=[];process.stdin.on('data',value=>chunks.push(value));process.stdin.on('end',()=>process.stdout.write(Buffer.concat(chunks).toString('base64')));";
  const results=await Promise.all([a,b].map(bytes=>runImageCommand(process.execPath,['-e',script],bytes,{cwd:directory,timeout:2000})));
  assert.deepEqual(results.map(result=>result.stdout),[a.toString('base64'),b.toString('base64')]);
  await assert.rejects(runImageCommand(process.execPath,['-e','setInterval(()=>{},1000)'],a,{cwd:directory,timeout:50}));
  await assert.rejects(runImageCommand('vahan-nonexistent-image-processor',[],a,{cwd:directory,timeout:100}));
  assert.deepEqual(await readdir(directory),[],'image processing creates no files');
  console.log('In-memory image bytes: validation, concurrent isolated stdin, timeout/missing command and no file writes passed.');
} finally {await rm(directory,{recursive:true});}
