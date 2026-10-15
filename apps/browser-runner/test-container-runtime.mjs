// Run this with the packaged runner image, not with a host browser/Tesseract.
import assert from 'node:assert/strict';
import {chromium} from 'playwright';
import {runImageCommand} from './image-pipe.mjs';

assert.ok(process.getuid() !== 0, 'runner runtime must be non-root');
const browser = await chromium.launch({headless:true, chromiumSandbox:true});
const result = {uid:process.getuid(), chromium:browser.version(), sandbox:true};
try {
  const page = await browser.newPage({viewport:{width:600,height:200}});
  await page.setContent('<body style="margin:0;background:white"><div id="text" style="width:560px;height:150px;font:96px monospace;color:black;display:flex;align-items:center;justify-content:center">ABC123</div></body>');
  assert.equal(await page.locator('#text').innerText(), 'ABC123');
  const image = await page.locator('#text').screenshot();
  const {stdout} = await runImageCommand('tesseract', ['stdin','stdout','-l','eng','--psm','7',
    '-c','tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'], image, {timeout:30_000});
  assert.equal(stdout.replace(/\s/g,''), 'ABC123', 'actual Tesseract must recognize the synthetic browser screenshot');
  result.ocr = {passed:true, input:'synthetic six-character text', transport:'stdin', rawOutputLogged:false};
  if (process.env.VAHAN_RUNTIME_LIVE_PROBE === '1') {
    try {
      const response = await page.goto(process.env.VAHAN_URL || 'https://analytics.parivahan.gov.in/analytics/vahanpublicreport?lang=en',
        {waitUntil:'domcontentloaded',timeout:45_000});
      result.liveVahan = {status:response?.status(), title:await page.title(), url:page.url(),
        note:'Navigation only; this does not prove a valid CAPTCHA submission or report download.'};
    } catch (error) {
      result.liveVahan = {passed:false, error:String(error.message).split('\n')[0],
        note:'External navigation failed; no TLS bypass was used.'};
    }
  }
  console.log(JSON.stringify(result,null,2));
} finally { await browser.close(); }
