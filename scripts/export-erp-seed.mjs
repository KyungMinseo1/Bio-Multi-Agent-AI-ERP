import {build} from 'esbuild';
import {writeFile} from 'node:fs/promises';
const result=await build({entryPoints:['src/erp/model.ts'],bundle:true,platform:'node',format:'esm',write:false});
const module=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
await writeFile('public/erp-seed.json',JSON.stringify(module.createSeed(),null,2)+'\n');
console.log('public/erp-seed.json generated from src/erp/model.ts');
