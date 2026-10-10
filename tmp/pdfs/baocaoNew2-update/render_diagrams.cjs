const fs=require('fs');
const path=require('path');
const {chromium}=require('/Users/mac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=__dirname;
const diagrams=JSON.parse(fs.readFileSync(path.join(root,'diagrams.json'),'utf8'));
fs.mkdirSync(path.join(root,'diagrams'),{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:2400,height:2400},deviceScaleFactor:2});
  await page.setContent('<html><head><style>body{margin:0;background:white}#figure{display:inline-block;padding:8px}svg{max-width:none!important;height:auto}</style></head><body><div id="figure"></div></body></html>');
  await page.addScriptTag({path:'/Users/mac/Desktop/vahan-automation/tmp/docx/vahan_english/vendor/mermaid.min.js'});
  await page.evaluate(()=>mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'base',themeVariables:{fontFamily:'Arial',fontSize:'19px',primaryColor:'#F3F7FA',primaryTextColor:'#172B3A',primaryBorderColor:'#50758B',lineColor:'#50758B',clusterBkg:'#F8FAFC',clusterBorder:'#A9BEC9'},flowchart:{curve:'stepBefore',htmlLabels:true,useMaxWidth:false,nodeSpacing:20,rankSpacing:24,padding:11}}));
  for(const d of diagrams){
   const svg=await page.evaluate(async d=>{const r=await mermaid.render(d.id,d.code);document.querySelector('#figure').innerHTML=r.svg;return r.svg},d);
   fs.writeFileSync(path.join(root,'diagrams',d.id+'.svg'),svg);
   fs.writeFileSync(path.join(root,'diagrams',d.id+'.mmd'),d.code+'\n');
   await page.locator('#figure').screenshot({path:path.join(root,'diagrams',d.id+'.png')});
   console.log(d.id,await page.locator('#figure').boundingBox());
  }
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
