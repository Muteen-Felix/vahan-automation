const fs = require('fs');
const path = require('path');
const {chromium} = require('/Users/mac/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = __dirname;
const diagrams = JSON.parse(fs.readFileSync(path.join(root, 'diagrams.json'),'utf8'));
const out = path.join(root,'diagrams');
fs.mkdirSync(out,{recursive:true});

(async()=>{
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:2200,height:2200},deviceScaleFactor:2});
    await page.setContent('<html><head><style>body{margin:0;background:white}#figure{display:inline-block;padding:12px}svg{max-width:none!important;height:auto}</style></head><body><div id="figure"></div></body></html>');
    await page.addScriptTag({path:path.join(root,'vendor','mermaid.min.js')});
    await page.evaluate(()=>mermaid.initialize({
      startOnLoad:false,securityLevel:'strict',theme:'base',
      themeVariables:{fontFamily:'Arial',fontSize:'20px',primaryColor:'#F3F6F8',primaryTextColor:'#111111',primaryBorderColor:'#8A969E',lineColor:'#68757D',secondaryColor:'#EDF3F7',tertiaryColor:'#FAFAFA',clusterBkg:'#FAFAFA',clusterBorder:'#C9D1D6'},
      flowchart:{curve:'stepBefore',htmlLabels:true,useMaxWidth:false,nodeSpacing:24,rankSpacing:28,padding:12}
    }));
    for(const d of diagrams){
      const svg = await page.evaluate(async ({id,code})=>{
        const result = await mermaid.render('diagram'+id,code);
        document.getElementById('figure').innerHTML=result.svg;
        return result.svg;
      },d);
      fs.writeFileSync(path.join(out,d.id+'.svg'),svg);
      fs.writeFileSync(path.join(out,d.id+'.mmd'),d.code+'\n');
      await page.locator('#figure').screenshot({path:path.join(out,d.id+'.png')});
      const box=await page.locator('#figure').boundingBox();
      console.log(d.id,Math.round(box.width)+'x'+Math.round(box.height),'Mermaid OK');
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
