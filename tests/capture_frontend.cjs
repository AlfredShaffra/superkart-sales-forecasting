// Capture actual Streamlit interactions, not a simulated UI.
const fs = require('fs');
const path = require('path');
// A normal npm-installed Playwright works in Codespaces or on a local machine.
const playwrightPath = process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES
  ? path.join(process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES, 'playwright')
  : 'playwright';
const { chromium } = require(playwrightPath);
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'evidence');
fs.mkdirSync(evidence, {recursive: true});
const url = process.env.FRONTEND_URL || 'http://127.0.0.1:8501';
(async () => {
  const launchOptions = {headless:true, args:['--disable-dev-shm-usage']};
  if (process.env.CHROME_EXECUTABLE) launchOptions.executablePath = process.env.CHROME_EXECUTABLE;
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({viewport:{width:1600,height:1600},deviceScaleFactor:1});
  const captureRegion = async (start, end, name) => {
    const a=await start.boundingBox();
    const b=await end.boundingBox();
    const x=Math.max(0,Math.min(a.x,b.x)-16);
    const right=Math.min(1600,Math.max(a.x+a.width,b.x+b.width)+16);
    await page.screenshot({path:path.join(evidence,name),clip:{x,y:Math.max(0,a.y-16),width:right-x,height:Math.min(1600,b.y+b.height+20)-Math.max(0,a.y-16)}});
  };
  const errors=[];
  page.on('pageerror', e=>errors.push(e.message));
  await page.goto(url,{waitUntil:'networkidle',timeout:60000});
  await page.getByRole('button',{name:'Predict sales',exact:true}).click();
  await page.getByText('Prediction completed',{exact:true}).waitFor({timeout:60000});
  await page.getByText('HTTP 200',{exact:true}).waitFor({timeout:60000});
  await page.screenshot({path:path.join(evidence,'single_inference.png'),fullPage:true});
  await captureRegion(page.getByText('Prediction completed',{exact:true}),page.getByText('The estimate uses the most recently submitted inputs. Submit again after changing the form.',{exact:true}),'single_result_detail.png');
  const singleText=await page.locator('body').innerText();
  await page.getByRole('tab',{name:'Batch prediction',exact:true}).click();
  await page.locator('input[type=file]').setInputFiles(path.join(root,'frontend/Batch_Data_SuperKart.csv'));
  await page.getByRole('button',{name:'Predict batch sales',exact:true}).click();
  await page.getByText('10 predictions completed',{exact:true}).waitFor({timeout:60000});
  await page.getByRole('button',{name:'Download predictions CSV',exact:true}).waitFor({timeout:60000});
  await page.screenshot({path:path.join(evidence,'batch_inference.png'),fullPage:true});
  await captureRegion(page.getByText('10 predictions completed',{exact:true}),page.getByText('No observed sales targets were provided for this batch. These outputs demonstrate inference, not batch forecast accuracy.',{exact:true}),'batch_result_detail.png');
  const batchText=await page.locator('body').innerText();
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download predictions CSV',exact:true}).click();
  const download=await downloadPromise;
  await download.saveAs(path.join(evidence,'ui_downloaded_predictions.csv'));
  // A changed upload must clear the previous predictions.
  const original=fs.readFileSync(path.join(root,'frontend/Batch_Data_SuperKart.csv'));
  await page.locator('input[type=file]').setInputFiles({name:'changed_batch.csv',mimeType:'text/csv',buffer:Buffer.from(original.toString().replace('117.08','118.08'))});
  await page.getByText('10 predictions completed',{exact:true}).waitFor({state:'hidden',timeout:30000});
  const staleCleared=await page.getByText('10 predictions completed',{exact:true}).count()===0;
  const checks=[
    {test:'Single inference success in browser',passed:singleText.includes('HTTP 200')},
    {test:'Batch inference success in browser',passed:batchText.includes('10 predictions completed')},
    {test:'CSV download completed',passed:fs.statSync(path.join(evidence,'ui_downloaded_predictions.csv')).size>0},
    {test:'Changed upload clears prior batch result',passed:staleCleared},
    {test:'No browser page errors',passed:errors.length===0}
  ];
  fs.writeFileSync(path.join(evidence,'frontend_verification.json'),JSON.stringify({url,
    verified_at:new Date().toISOString(),single_success:singleText.includes('HTTP 200'),
    batch_success:batchText.includes('10 predictions completed'),download_filename:download.suggestedFilename(),
    total_checks:checks.length,passed:checks.filter(x=>x.passed).length,checks,
    browser_errors:errors,single_text:singleText,batch_text:batchText},null,2));
  // UI success alone does not prove a cloud or Docker deployment. Preserve
  // deployment_status.json, which is recorded separately from platform evidence.
  console.log(JSON.stringify({url,checks:checks.length,passed:checks.filter(x=>x.passed).length,browser_errors:errors}));
  await browser.close();
  if (checks.some(x => !x.passed)) process.exitCode = 1;
})().catch(e=>{console.error(e);process.exit(1);});
